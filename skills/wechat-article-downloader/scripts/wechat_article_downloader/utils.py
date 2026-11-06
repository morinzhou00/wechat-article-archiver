from __future__ import annotations

import html
import json
import os
import re
import tempfile
import threading
from datetime import date, datetime
from pathlib import Path
from urllib.parse import parse_qs, urlparse

from .errors import InvalidInputError


WECHAT_HOSTS = {"mp.weixin.qq.com", "weixin.qq.com"}
SAFE_NAME = re.compile(r'[<>:"/\\|?*\x00-\x1f]+')
_FILE_WRITE_LOCK = threading.RLock()


def default_data_dir() -> Path:
    override = os.environ.get("WECHAT_DOWNLOADER_HOME")
    if override:
        return Path(override).expanduser()
    if os.name == "nt":
        home = os.environ.get("USERPROFILE")
        base = str(Path(home) / "AppData" / "Local") if home else tempfile.gettempdir()
    else:
        base = os.environ.get("LOCALAPPDATA") or tempfile.gettempdir()
    return Path(base) / "WechatArticleDownloader"


def default_output_dir() -> Path:
    return Path(os.environ.get("USERPROFILE", str(Path.home()))) / "Downloads" / "WeChatArticles"


def atomic_write_json(path: Path, payload: object) -> None:
    with _FILE_WRITE_LOCK:
        path.parent.mkdir(parents=True, exist_ok=True)
        temporary = path.with_suffix(path.suffix + f".{os.getpid()}.{threading.get_ident()}.tmp")
        temporary.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
        os.replace(temporary, path)


def append_jsonl(path: Path, payload: object, *, max_lines: int = 200) -> None:
    with _FILE_WRITE_LOCK:
        path.parent.mkdir(parents=True, exist_ok=True)
        lines: list[str] = []
        if path.exists():
            lines = path.read_text(encoding="utf-8").splitlines()[-(max_lines - 1) :]
        lines.append(json.dumps(payload, ensure_ascii=False, separators=(",", ":")))
        temporary = path.with_suffix(path.suffix + f".{os.getpid()}.{threading.get_ident()}.tmp")
        temporary.write_text("\n".join(lines) + "\n", encoding="utf-8")
        os.replace(temporary, path)


def read_json(path: Path, default: object | None = None) -> object:
    if not path.exists():
        return default
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return default


def safe_filename(value: str, fallback: str = "article", limit: int = 120) -> str:
    normalized = re.sub(r"\s+", " ", html.unescape(value or "")).strip()
    normalized = SAFE_NAME.sub("_", normalized).strip(" ._")
    return (normalized[:limit].rstrip(" .") or fallback)


def validate_article_url(url: str) -> str:
    parsed = urlparse(url.strip())
    if parsed.scheme != "https" or (parsed.hostname or "").lower() not in WECHAT_HOSTS:
        raise InvalidInputError(
            "Only https://mp.weixin.qq.com article or collection URLs are accepted.",
            details={"field": "url"},
        )
    if not (parsed.path.startswith("/s") or parsed.path.startswith("/mp/appmsgalbum")):
        raise InvalidInputError("The URL is not a supported WeChat article or collection URL.")
    return url.strip()


def parse_url_fields(url: str) -> dict[str, str | None]:
    query = parse_qs(urlparse(html.unescape(url)).query)
    return {
        "biz": _first(query.get("__biz")),
        "mid": _first(query.get("mid")) or _first(query.get("appmsgid")),
        "idx": _first(query.get("idx")),
        "sn": _first(query.get("sn")),
    }


def parse_iso_date(value: str | None, field: str) -> date | None:
    if not value:
        return None
    try:
        return date.fromisoformat(value)
    except ValueError as exc:
        raise InvalidInputError(f"{field} must use YYYY-MM-DD.", details={"field": field}) from exc


def parse_formats(value: str | list[str] | tuple[str, ...]) -> list[str]:
    if isinstance(value, str):
        candidates = value.split(",")
    else:
        candidates = list(value)
        if not all(isinstance(item, str) for item in candidates):
            raise InvalidInputError("Formats must be strings.")
    allowed = {"html", "md", "json", "csv", "txt", "pdf", "docx", "mhtml"}
    formats = list(dict.fromkeys(item.strip().lower() for item in candidates if item.strip()))
    invalid = sorted(set(formats) - allowed)
    if invalid or not formats:
        raise InvalidInputError(
            f"Unsupported format(s): {', '.join(invalid) if invalid else 'none'}.",
            details={"allowed": sorted(allowed)},
        )
    return formats


def now_iso() -> str:
    return datetime.now().astimezone().isoformat(timespec="seconds")


def _first(values: list[str] | None) -> str | None:
    return values[0] if values else None
