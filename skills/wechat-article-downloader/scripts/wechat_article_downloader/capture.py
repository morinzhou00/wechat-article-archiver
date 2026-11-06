from __future__ import annotations

import heapq
import html
import os
import re
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Callable, Iterator
from urllib.parse import parse_qs, unquote, urlencode, urlparse

from .errors import AuthRequiredError, InvalidInputError


URL_PATTERN = re.compile(rb"https?://[A-Za-z0-9:/?.&=+%_~#;,@!\-*()]+")
SKIP_DIRECTORIES = {
    "video",
    "filestorage",
    "avatar",
    "image",
    "attachment",
    "music",
    "emoji",
    "crashpad",
    "gpucache",
}
MAX_SCAN_FILE_BYTES = 64 * 1024 * 1024
MAX_SCAN_TOTAL_BYTES = 512 * 1024 * 1024
MAX_SCAN_DIRECTORIES = 20_000
MAX_SCAN_SECONDS = 20.0
MAX_URL_BYTES = 16 * 1024


@dataclass(slots=True)
class CaptureCandidate:
    request_url: str
    fields: dict[str, str]
    modified_at: float
    source_root: str

    def summary(self) -> dict[str, object]:
        return {
            "field_names": sorted(self.fields),
            "modified_at": self.modified_at,
            "source_root": self.source_root,
        }


@dataclass(slots=True)
class ScanReport:
    scanned_files: int
    scanned_bytes: int
    roots: list[str]
    candidates: list[CaptureCandidate]
    duration_seconds: float
    truncated: bool = False
    truncation_reasons: list[str] | None = None

    def summary(self) -> dict[str, object]:
        return {
            "scanned_files": self.scanned_files,
            "scanned_bytes": self.scanned_bytes,
            "roots": self.roots,
            "candidate_count": len(self.candidates),
            "candidates": [candidate.summary() for candidate in self.candidates],
            "duration_seconds": self.duration_seconds,
            "truncated": self.truncated,
            "truncation_reasons": self.truncation_reasons or [],
        }


def default_wechat_roots(*, include_temp: bool = False) -> list[Path]:
    home = Path(os.environ.get("USERPROFILE", str(Path.home())))
    appdata = Path(os.environ.get("APPDATA", home / "AppData" / "Roaming"))
    local = Path(os.environ.get("LOCALAPPDATA", home / "AppData" / "Local"))
    candidates: list[Path] = [
        appdata / "Tencent" / "xwechat",
        appdata / "Tencent" / "WeChat",
        home / "Documents" / "xwechat_files",
        home / "Documents" / "WeChat Files",
        home / "Library" / "Containers" / "com.tencent.xinWeChat",
    ]
    if include_temp:
        candidates.append(local / "Temp")
    return [path for path in candidates if path.exists()]


def build_account_home_url(biz: str) -> str:
    if not biz or len(biz) > 256:
        raise InvalidInputError("A valid WeChat account identifier is required.")
    return "https://mp.weixin.qq.com/mp/profile_ext?" + urlencode(
        {"action": "home", "__biz": biz, "scene": "124"}
    ) + "#wechat_redirect"


def scan_credentials(
    target_biz: str,
    *,
    since_minutes: int = 60,
    max_files: int = 5000,
    roots: list[Path] | None = None,
    seen_versions: set[tuple[str, int, int]] | None = None,
    max_total_bytes: int = MAX_SCAN_TOTAL_BYTES,
    max_directories: int = MAX_SCAN_DIRECTORIES,
    max_scan_seconds: float = MAX_SCAN_SECONDS,
) -> ScanReport:
    if not 1 <= since_minutes <= 1440:
        raise InvalidInputError("since_minutes must be between 1 and 1440.")
    if not 100 <= max_files <= 50000:
        raise InvalidInputError("max_files must be between 100 and 50000.")
    if not 1024 <= max_total_bytes <= 2 * 1024 * 1024 * 1024:
        raise InvalidInputError("max_total_bytes must be between 1 KiB and 2 GiB.")
    if not 1 <= max_directories <= 100_000:
        raise InvalidInputError("max_directories must be between 1 and 100000.")
    if not 1.0 <= max_scan_seconds <= 300.0:
        raise InvalidInputError("max_scan_seconds must be between 1 and 300.")
    selected_roots = roots or default_wechat_roots()
    cutoff = time.time() - since_minutes * 60
    started = time.monotonic()
    deadline = started + max_scan_seconds
    recent_files, truncation_reasons = _recent_files(
        selected_roots,
        cutoff,
        max_files,
        max_directories=max_directories,
        deadline=deadline,
    )
    candidates_by_key: dict[tuple[str, ...], CaptureCandidate] = {}
    scanned_files = 0
    scanned_bytes = 0
    for modified_at, size, path, root_label in recent_files:
        if time.monotonic() > deadline:
            truncation_reasons.append("scan_time_budget")
            break
        if scanned_bytes + size > max_total_bytes:
            truncation_reasons.append("total_byte_budget")
            break
        version = (str(path), size, int(modified_at * 1_000_000_000))
        if seen_versions is not None and version in seen_versions:
            continue
        if seen_versions is not None:
            seen_versions.add(version)
        scanned_files += 1
        scanned_bytes += size
        for request_url in _urls_in_file(path):
            candidate = _candidate_from_url(request_url, target_biz, modified_at, root_label)
            if candidate is None:
                continue
            identity = tuple(candidate.fields.get(field, "") for field in ("biz", "uin", "key", "pass_ticket", "poc_token"))
            current = candidates_by_key.get(identity)
            if current is None or candidate.modified_at > current.modified_at:
                candidates_by_key[identity] = candidate
    candidates = sorted(candidates_by_key.values(), key=lambda item: item.modified_at, reverse=True)
    return ScanReport(
        scanned_files=scanned_files,
        scanned_bytes=scanned_bytes,
        roots=[_root_label(path) for path in selected_roots],
        candidates=candidates,
        duration_seconds=round(time.monotonic() - started, 3),
        truncated=bool(truncation_reasons),
        truncation_reasons=sorted(set(truncation_reasons)),
    )


def watch_for_credentials(
    target_biz: str,
    *,
    seconds: int = 120,
    poll_seconds: float = 3.0,
    since_minutes: int = 60,
    progress: Callable[[dict[str, object]], None] | None = None,
) -> tuple[CaptureCandidate, ScanReport]:
    if not 5 <= seconds <= 600:
        raise InvalidInputError("watch seconds must be between 5 and 600.")
    deadline = time.monotonic() + seconds
    last_report: ScanReport | None = None
    seen_versions: set[tuple[str, int, int]] = set()
    while time.monotonic() <= deadline:
        last_report = scan_credentials(
            target_biz,
            since_minutes=since_minutes,
            seen_versions=seen_versions,
        )
        if progress:
            progress(last_report.summary())
        if last_report.candidates:
            return last_report.candidates[0], last_report
        time.sleep(max(poll_seconds, 3.0))
    raise AuthRequiredError(
        "No fresh WeChat account-history credential was found.",
        details={
            "action": "Keep WeChat signed in, open the generated account-home link inside WeChat, then retry.",
            "last_scan": last_report.summary() if last_report else None,
        },
    )


def _recent_files(
    roots: list[Path],
    cutoff: float,
    max_files: int,
    *,
    max_directories: int,
    deadline: float,
) -> tuple[list[tuple[float, int, Path, str]], list[str]]:
    newest: list[tuple[float, int, str, Path, str]] = []
    reasons: list[str] = []
    directory_count = 0
    for root in roots:
        label = _root_label(root)
        stack = [root]
        while stack:
            if time.monotonic() > deadline:
                reasons.append("enumeration_time_budget")
                stack.clear()
                break
            if directory_count >= max_directories:
                reasons.append("directory_budget")
                stack.clear()
                break
            directory = stack.pop()
            directory_count += 1
            try:
                entries = list(os.scandir(directory))
            except OSError:
                continue
            for entry in entries:
                try:
                    if entry.is_dir(follow_symlinks=False):
                        if entry.name.casefold() not in SKIP_DIRECTORIES:
                            stack.append(Path(entry.path))
                        continue
                    if not entry.is_file(follow_symlinks=False):
                        continue
                    stat = entry.stat(follow_symlinks=False)
                except OSError:
                    continue
                if stat.st_mtime < cutoff or stat.st_size <= 0 or stat.st_size > MAX_SCAN_FILE_BYTES:
                    continue
                path = Path(entry.path)
                item = (stat.st_mtime, stat.st_size, str(path), path, label)
                if len(newest) < max_files:
                    heapq.heappush(newest, item)
                elif item[:3] > newest[0][:3]:
                    heapq.heapreplace(newest, item)
    if len(newest) >= max_files:
        reasons.append("file_count_budget")
    rows = [(mtime, size, path, label) for mtime, size, _name, path, label in sorted(newest, reverse=True)]
    return rows, reasons


def _urls_in_file(path: Path) -> Iterator[str]:
    overlap = b""
    try:
        with path.open("rb") as handle:
            while chunk := handle.read(1024 * 1024):
                data = overlap + chunk
                for match in URL_PATTERN.finditer(data):
                    if len(match.group()) <= MAX_URL_BYTES:
                        yield match.group().decode("ascii", errors="ignore")
                overlap = data[-MAX_URL_BYTES:]
    except OSError:
        return


def _candidate_from_url(
    raw_url: str,
    target_biz: str,
    modified_at: float,
    root_label: str,
) -> CaptureCandidate | None:
    value = html.unescape(raw_url)
    for _ in range(2):
        value = unquote(value)
    parsed = urlparse(value)
    if (parsed.hostname or "").lower() != "mp.weixin.qq.com":
        return None
    query = parse_qs(parsed.query)
    fields = {key.lstrip("_"): values[0] for key, values in query.items() if values}
    if "__biz" in query:
        fields["biz"] = query["__biz"][0]
    if fields.get("biz") != target_biz:
        return None
    legacy_ready = all(fields.get(field) for field in ("uin", "key", "pass_ticket"))
    token_ready = all(fields.get(field) for field in ("appmsg_token", "pass_ticket"))
    if not (legacy_ready or token_ready):
        return None
    return CaptureCandidate(
        request_url=value,
        fields=fields,
        modified_at=modified_at,
        source_root=root_label,
    )


def _root_label(path: Path) -> str:
    lowered = str(path).lower()
    if "xwechat" in lowered:
        return "Tencent/xwechat"
    if lowered.endswith("\\wechat") or lowered.endswith("/wechat"):
        return "Tencent/WeChat"
    if "temp" in path.name.lower() or lowered.endswith("\\temp"):
        return "Local/Temp"
    if "xinwechat" in lowered:
        return "com.tencent.xinWeChat"
    return path.name
