from __future__ import annotations

import hashlib
import json
from datetime import date, datetime
from pathlib import Path
from typing import Any

from .models import DiscoveryResult, HistoryItem
from .utils import atomic_write_json, read_json


CHECKPOINT_VERSION = 1


def make_fingerprint(
    biz: str,
    *,
    latest: int | None,
    start_date: date | None,
    end_date: date | None,
    max_pages: int,
) -> dict[str, object]:
    return {
        "biz": biz,
        "latest": latest,
        "since": start_date.isoformat() if start_date else None,
        "until": end_date.isoformat() if end_date else None,
        "max_pages": max_pages,
    }


def checkpoint_path(root: Path, fingerprint: dict[str, object]) -> Path:
    encoded = json.dumps(fingerprint, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
    suffix = hashlib.sha256(encoded.encode("utf-8")).hexdigest()[:16]
    return root.expanduser().resolve() / "_resume" / f"account-{suffix}.json"


def load_checkpoint(
    path: Path,
    fingerprint: dict[str, object],
) -> dict[str, Any] | None:
    raw = read_json(path, None)
    if not isinstance(raw, dict):
        return None
    if raw.get("version") != CHECKPOINT_VERSION or raw.get("fingerprint") != fingerprint:
        return None
    try:
        items = [HistoryItem.from_dict(item) for item in raw.get("items", [])]
    except (TypeError, ValueError):
        return None
    return {
        "fingerprint": fingerprint,
        "items": items,
        "next_offset": _integer(raw.get("next_offset")),
        "pages_scanned": _integer(raw.get("pages_scanned")) or 0,
        "complete": bool(raw.get("complete")),
        "stop_reason": str(raw.get("stop_reason") or "unknown"),
        "downloaded_keys": sorted(
            str(value) for value in raw.get("downloaded_keys", []) if isinstance(value, str)
        ),
        "failed_keys": {
            str(key): str(value)
            for key, value in (raw.get("failed_keys") or {}).items()
            if isinstance(key, str)
        },
    }


def save_checkpoint(
    path: Path,
    fingerprint: dict[str, object],
    *,
    discovered: DiscoveryResult,
    downloaded_keys: set[str],
    failed_keys: dict[str, str] | None = None,
) -> None:
    atomic_write_json(
        path,
        {
            "version": CHECKPOINT_VERSION,
            "fingerprint": fingerprint,
            "updated_at": datetime.now().astimezone().isoformat(timespec="seconds"),
            "next_offset": discovered.next_offset,
            "pages_scanned": discovered.pages_scanned,
            "complete": discovered.complete,
            "stop_reason": discovered.stop_reason,
            "items": [item.to_dict() for item in discovered.items],
            "downloaded_keys": sorted(downloaded_keys),
            "failed_keys": dict(sorted((failed_keys or {}).items())),
        },
    )


def item_key(item: HistoryItem) -> str:
    if item.biz and item.mid and item.idx:
        return f"{item.biz}:{item.mid}:{item.idx}"
    digest = hashlib.sha256(item.url.encode("utf-8")).hexdigest()
    return f"url:{digest}"


def scan_exported_keys(
    root: Path, biz: str, *, max_files: int = 20_000,
    formats: list[str] | None = None, include_assets: bool = False,
) -> set[str]:
    """Find successfully exported article metadata so an interrupted legacy run can resume."""
    keys: set[str] = set()
    if not root.exists():
        return keys
    stack = [root]
    examined = 0
    while stack and examined < max_files:
        directory = stack.pop()
        try:
            entries = list(directory.iterdir())
        except OSError:
            continue
        for entry in entries:
            examined += 1
            if examined >= max_files:
                break
            try:
                if entry.is_dir():
                    stack.append(entry)
                    continue
                if entry.name != "article.json" or not entry.is_file():
                    continue
                if not entry.with_name("article.md").is_file():
                    continue
                if not entry.with_name("manifest.json").is_file():
                    continue
                if any(not entry.with_name(f"article.{suffix}").is_file() for suffix in (formats or [])):
                    continue
                manifest = json.loads(entry.with_name("manifest.json").read_text(encoding="utf-8"))
                if not isinstance(manifest, dict):
                    continue
                if include_assets and manifest.get("include_assets") is not True:
                    continue
                payload = json.loads(entry.read_text(encoding="utf-8"))
            except (OSError, json.JSONDecodeError):
                continue
            if not isinstance(payload, dict) or payload.get("biz") != biz:
                continue
            if include_assets:
                assets = payload.get("assets", [])
                if not isinstance(assets, list) or any(
                    not isinstance(asset, dict)
                    or not asset.get("relative_path")
                    or not (entry.parent / str(asset["relative_path"])).is_file()
                    for asset in assets
                ):
                    continue
            biz_value = payload.get("biz")
            mid_value = payload.get("mid")
            idx_value = payload.get("idx")
            if biz_value and mid_value and idx_value:
                keys.add(f"{biz_value}:{mid_value}:{idx_value}")
    return keys


def _integer(value: object) -> int | None:
    try:
        return int(value) if value is not None else None
    except (TypeError, ValueError):
        return None
