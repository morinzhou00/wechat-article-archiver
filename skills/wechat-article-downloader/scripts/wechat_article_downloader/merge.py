from __future__ import annotations

import json
import os
import re
from collections import Counter
from datetime import date, datetime
from pathlib import Path
from typing import Any

from .utils import atomic_write_json, safe_filename


HEADER_END = re.compile(r"^- 原文：.*?\r?\n\r?\n", re.MULTILINE | re.DOTALL)
WHITESPACE = re.compile(r"\s+")


def merge_archives(source_root: Path, target_root: Path, *, dry_run: bool = False) -> dict[str, Any]:
    source_root = source_root.expanduser().resolve()
    target_root = target_root.expanduser().resolve()
    if not source_root.is_dir():
        raise FileNotFoundError(f"source directory does not exist: {source_root}")
    target_root.mkdir(parents=True, exist_ok=True)

    source_items, invalid_sources, duplicate_sources = _scan_source(source_root)
    target_index = _scan_target(target_root)
    added: list[dict[str, str]] = []
    present: list[dict[str, str]] = []
    conflicts: list[dict[str, str]] = []
    failed_writes: list[dict[str, str]] = []
    target_counts = Counter()
    for item in target_index.values():
        month = _month(item.get("publish_time"))
        if month:
            target_counts[month] += 1

    for key, item in sorted(source_items.items(), key=lambda pair: pair[1]["date"], reverse=True):
        existing = target_index.get(key)
        if existing:
            old_text = str(existing.get("content_text") or "")
            if not old_text and existing.get("content_path"):
                old_text = _markdown_body(_read_text(Path(existing["content_path"])))
            if _normalize_markdown(old_text) == _normalize_markdown(item["body"]):
                present.append(_brief(item))
            else:
                conflicts.append(
                    {
                        **_brief(item),
                        "reason": "same article identity has different local content",
                        "existing_path": existing.get("json_path", ""),
                    }
                )
            continue

        target_md, target_json = _target_paths(target_root, item, set(target_index))
        if target_md.exists() or target_json.exists():
            conflicts.append(
                {
                    **_brief(item),
                    "reason": "target filename already exists for a different article identity",
                    "existing_path": str(target_md if target_md.exists() else target_json),
                }
            )
            continue
        if not dry_run:
            try:
                _atomic_write_text(target_md, item["markdown"])
                atomic_write_json(target_json, item["archive_json"])
            except OSError as exc:
                failed_writes.append({**_brief(item), "reason": str(exc)})
                target_md.unlink(missing_ok=True)
                target_json.unlink(missing_ok=True)
                continue
        added.append(_brief(item))
        target_index[key] = {
            "publish_time": item["date"],
            "content_path": str(target_md),
            "json_path": str(target_json),
        }
        month = _month(item["date"])
        if month:
            target_counts[month] += 1

    batch_reports = _batch_reports(source_root)
    expected_months = _month_range(target_counts)
    missing_months = sorted(set(expected_months) - set(target_counts))
    report: dict[str, Any] = {
        "ok": not conflicts and not failed_writes and not invalid_sources,
        "generated_at": datetime.now().astimezone().isoformat(timespec="seconds"),
        "dry_run": dry_run,
        "source_root": str(source_root),
        "target_root": str(target_root),
        "source_articles": len(source_items),
        "target_articles_before": len(target_index) - len(added),
        "added": len(added),
        "already_present": len(present),
        "conflicts": conflicts,
        "invalid_sources": invalid_sources,
        "duplicate_source_identities": duplicate_sources,
        "failed_writes": failed_writes,
        "target_articles_after": len(target_index),
        "monthly_counts": dict(sorted(target_counts.items())),
        "missing_months_in_observed_range": missing_months,
        "batch_reports": batch_reports,
        "added_items": added,
    }
    if not dry_run:
        atomic_write_json(target_root / "_merge_report.json", report)
        _atomic_write_text(target_root / "_merge_report.md", _render_markdown_report(report))
    return report


def _scan_source(root: Path) -> tuple[dict[str, dict[str, Any]], list[dict[str, str]], list[str]]:
    items: dict[str, dict[str, Any]] = {}
    invalid: list[dict[str, str]] = []
    duplicates: list[str] = []
    for json_path in sorted(root.rglob("article.json")):
        try:
            meta = json.loads(json_path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError) as exc:
            invalid.append({"path": str(json_path), "reason": str(exc)})
            continue
        key = _article_key(meta)
        md_path = json_path.with_name("article.md")
        if not key or not md_path.is_file():
            invalid.append({"path": str(json_path), "reason": "missing identity or article.md"})
            continue
        markdown = md_path.read_text(encoding="utf-8")
        body = _markdown_body(markdown)
        if not body.strip():
            invalid.append({"path": str(md_path), "reason": "empty article body"})
            continue
        if key in items:
            duplicates.append(key)
            continue
        published = str(meta.get("published_at") or "")[:10]
        if not _month(published):
            invalid.append({"path": str(json_path), "reason": "missing or invalid publication date"})
            continue
        title = str(meta.get("title") or "untitled")
        items[key] = {
            "key": key,
            "title": title,
            "date": published,
            "account": str(meta.get("account_name") or ""),
            "author": meta.get("author"),
            "url": str(meta.get("url") or ""),
            "biz": meta.get("biz"),
            "mid": str(meta.get("mid") or ""),
            "idx": str(meta.get("idx") or ""),
            "sn": meta.get("sn"),
            "digest": meta.get("digest"),
            "body": body,
            "markdown": markdown,
            "archive_json": _archive_payload(meta, body),
            "source_json": str(json_path),
        }
    return items, invalid, sorted(set(duplicates))


def _scan_target(root: Path) -> dict[str, dict[str, Any]]:
    result: dict[str, dict[str, Any]] = {}
    for json_path in root.glob("*.json"):
        try:
            payload = json.loads(json_path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            continue
        key = _article_key(payload)
        if not key:
            continue
        result[key] = {
            "publish_time": str(payload.get("publish_time") or payload.get("published_at") or ""),
            "content_text": str(payload.get("content_text") or payload.get("content_md") or ""),
            "content_path": str(json_path.with_suffix(".md")),
            "json_path": str(json_path),
        }
    return result


def _article_key(payload: object) -> str | None:
    if not isinstance(payload, dict):
        return None
    biz = payload.get("biz")
    mid = payload.get("mid")
    idx = payload.get("idx")
    if biz and mid and idx:
        return f"{biz}:{mid}:{idx}"
    return None


def _archive_payload(meta: dict[str, Any], body: str) -> dict[str, Any]:
    return {
        "key": _article_key(meta),
        "url": meta.get("url"),
        "fetched_at": datetime.now().astimezone().isoformat(timespec="seconds"),
        "title": meta.get("title"),
        "account": meta.get("account_name"),
        "author": meta.get("author"),
        "gh_id": None,
        "biz": meta.get("biz"),
        "mid": meta.get("mid"),
        "idx": meta.get("idx"),
        "sn": meta.get("sn"),
        "ct": meta.get("extra", {}).get("timestamp") if isinstance(meta.get("extra"), dict) else None,
        "publish_time": meta.get("published_at"),
        "content_text": body.strip(),
        "content_md": body.strip(),
        "images": [],
        "image_files": [],
        "source": "wechat-history-archiver",
        "char_count": len(body.strip()),
    }


def _target_paths(
    root: Path,
    item: dict[str, Any],
    occupied_keys: set[str],
) -> tuple[Path, Path]:
    stem = safe_filename(f"{item['date']} {item['title']}")
    markdown = root / f"{stem}.md"
    metadata = root / f"{stem}.json"
    if markdown.exists() or metadata.exists():
        stem = safe_filename(f"{item['date']} {item['title']} [{item['mid']}-{item['idx']}]")
        markdown = root / f"{stem}.md"
        metadata = root / f"{stem}.json"
    return markdown, metadata


def _markdown_body(markdown: str) -> str:
    match = HEADER_END.search(markdown)
    return markdown[match.end() :] if match else markdown


def _normalize_markdown(value: str) -> str:
    without_images = re.sub(r"!\[[^\]]*\]\([^)]*\)", "", value)
    return WHITESPACE.sub("", without_images)


def _month(value: object) -> str | None:
    text = str(value or "")
    if len(text) >= 7 and re.fullmatch(r"\d{4}-\d{2}", text[:7]):
        try:
            date.fromisoformat(text[:7] + "-01")
        except ValueError:
            return None
        return text[:7]
    return None


def _month_range(counts: Counter[str]) -> list[str]:
    if not counts:
        return []
    start = min(counts)
    end = max(counts)
    start_date = date.fromisoformat(start + "-01")
    end_date = date.fromisoformat(end + "-01")
    result: list[str] = []
    year, month = start_date.year, start_date.month
    while (year, month) <= (end_date.year, end_date.month):
        result.append(f"{year:04d}-{month:02d}")
        month += 1
        if month > 12:
            year += 1
            month = 1
    return result


def _batch_reports(root: Path) -> list[dict[str, Any]]:
    reports: list[dict[str, Any]] = []
    batch_dir = root / "_batches"
    if not batch_dir.is_dir():
        return reports
    for path in sorted(batch_dir.glob("*.json")):
        try:
            payload = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            continue
        if not isinstance(payload, dict):
            continue
        reports.append(
            {
                "path": str(path),
                "ok": payload.get("ok"),
                "history_scan": payload.get("history_scan"),
                "failures": len(payload.get("failures", [])) if isinstance(payload.get("failures"), list) else None,
            }
        )
    return reports


def _render_markdown_report(report: dict[str, Any]) -> str:
    lines = [
        "# 公众号历史合并报告",
        "",
        f"- 生成时间：{report['generated_at']}",
        f"- 来源目录：`{report['source_root']}`",
        f"- 目标目录：`{report['target_root']}`",
        f"- 来源文章：{report['source_articles']}",
        f"- 新增：{report['added']}",
        f"- 已存在：{report['already_present']}",
        f"- 冲突：{len(report['conflicts'])}",
        f"- 无效来源：{len(report['invalid_sources'])}",
        f"- 合并后文章：{report['target_articles_after']}",
        f"- 观察范围内缺失月份：{', '.join(report['missing_months_in_observed_range']) or '无'}",
        "",
        "## 月度覆盖",
        "",
    ]
    for month, count in report["monthly_counts"].items():
        lines.append(f"- {month}：{count} 篇")
    if report["conflicts"]:
        lines.extend(["", "## 冲突", ""])
        for item in report["conflicts"]:
            lines.append(f"- {item['date']}《{item['title']}》：{item['reason']}")
    if report["invalid_sources"]:
        lines.extend(["", "## 无效来源", ""])
        for item in report["invalid_sources"]:
            lines.append(f"- `{item['path']}`：{item['reason']}")
    return "\n".join(lines).rstrip() + "\n"


def _brief(item: dict[str, Any]) -> dict[str, str]:
    return {
        "key": item["key"],
        "date": item["date"],
        "title": item["title"],
        "account": item["account"],
        "source_json": item["source_json"],
    }


def _read_text(path: Path) -> str:
    try:
        return path.read_text(encoding="utf-8")
    except OSError:
        return ""


def _atomic_write_text(path: Path, value: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_suffix(path.suffix + f".{os.getpid()}.tmp")
    temporary.write_text(value, encoding="utf-8")
    os.replace(temporary, path)
