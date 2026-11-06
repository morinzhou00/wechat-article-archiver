"""Build an auditable index for a downloaded account history.

The script reconciles a batch manifest, a retry report, and an optional legacy
archive. Existing articles are copied only when their title and date both match
an item whose live article page is unavailable.
"""

from __future__ import annotations

import argparse
import csv
import json
import shutil
from datetime import datetime
from pathlib import Path

from wechat_article_downloader.utils import atomic_write_json, parse_url_fields, safe_filename


PREVIEW_MARKERS = (
    "全文只有",
    "全文400字",
    "想付费看几千字",
    "本文2300余字",
)


def article_key(record: dict[str, object]) -> tuple[str, str, str]:
    from_url = parse_url_fields(str(record.get("url") or ""))
    values = []
    for field in ("biz", "mid", "idx"):
        value = str(record.get(field) or "")
        if not value or (" + " in value and value.strip().startswith("+")):
            value = str(from_url.get(field) or "")
        values.append(value)
    return tuple(values)


def markdown_body(path: Path) -> str:
    text = path.read_text(encoding="utf-8")
    marker = "- 原文："
    position = text.find(marker)
    if position >= 0:
        separator = text.find("\n\n", position)
        if separator >= 0:
            return text[separator + 2 :].strip()
    return text.strip()


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("manifest", type=Path)
    parser.add_argument("retry_report", type=Path)
    parser.add_argument("--archive", type=Path, required=True)
    parser.add_argument("--legacy-archive", type=Path)
    parser.add_argument("--account", default="东函西数")
    args = parser.parse_args()

    manifest = json.loads(args.manifest.read_text(encoding="utf-8"))
    retry = json.loads(args.retry_report.read_text(encoding="utf-8"))
    discovered = manifest["discovered"]
    successful: dict[tuple[str, str, str], dict[str, object]] = {}
    for item in manifest.get("downloads") or []:
        article = item.get("article") or {}
        successful[article_key(article)] = item

    retry_success: dict[tuple[str, str, str], dict[str, object]] = {}
    retry_failed: dict[tuple[str, str, str], dict[str, object]] = {}
    for result in retry.get("results") or []:
        if result.get("ok"):
            article = result.get("article") or {}
            retry_success[article_key(article)] = result
        else:
            source = result.get("url", "")
            match = next((item for item in manifest.get("failures") or [] if item.get("url") == source), None)
            if match:
                retry_failed[article_key(match)] = result

    legacy: dict[tuple[str, str, str], dict[str, object]] = {}
    if args.legacy_archive:
        for meta_path in args.legacy_archive.glob("*.json"):
            try:
                meta = json.loads(meta_path.read_text(encoding="utf-8"))
            except (OSError, json.JSONDecodeError):
                continue
            key = (
                str(meta.get("biz") or ""),
                str(meta.get("mid") or ""),
                str(meta.get("idx") or ""),
            )
            legacy[key] = {"meta": meta, "meta_path": meta_path, "md_path": meta_path.with_suffix(".md")}

    account_root = args.archive.resolve() / safe_filename(args.account)
    rows = []
    unresolved = []
    unresolved_keys: set[tuple[str, str, str]] = set()
    for item in discovered:
        key = article_key(item)
        published = datetime.fromisoformat(item["published_at"])
        title = str(item.get("title") or "untitled")
        target = account_root / f"{published:%Y-%m-%d}_{safe_filename(title)}"
        status = "failed_restricted"
        directory = ""
        content_chars = 0
        preview = False

        if key in successful:
            status = "downloaded"
            directory = str(successful[key].get("directory") or "")
        elif key in retry_success:
            status = "downloaded_retry"
            directory = str(retry_success[key].get("directory") or "")
        elif key in legacy:
            old = legacy[key]
            old_meta = old["meta"]
            old_date = str(old_meta.get("publish_time") or "")[:10]
            if old_date == f"{published:%Y-%m-%d}" and old["md_path"].is_file():
                target.mkdir(parents=True, exist_ok=True)
                shutil.copy2(old["md_path"], target / "article.md")
                shutil.copy2(old["meta_path"], target / "article.json")
                manifest_payload = {
                    "source": "legacy-archive",
                    "source_files": {
                        "markdown": str(old["md_path"]),
                        "metadata": str(old["meta_path"]),
                    },
                    "article": old_meta,
                }
                atomic_write_json(target / "manifest.json", manifest_payload)
                status = "legacy_archive"
                directory = str(target)
            else:
                legacy_status = "legacy_date_mismatch"
                unresolved.append({"key": key, "title": title, "reason": legacy_status})
                unresolved_keys.add(key)
        elif key in retry_failed:
            status = "failed_restricted"

        # File moves and retries can leave stale paths in older manifests. The
        # account/date/title layout is deterministic, so prefer the live path.
        if (target / "article.md").is_file():
            directory = str(target)
        if directory:
            md_path = Path(directory) / "article.md"
            if md_path.is_file():
                body = markdown_body(md_path)
                content_chars = len(body)
                preview = any(marker in body for marker in PREVIEW_MARKERS)

        if status == "failed_restricted" and key not in unresolved_keys:
            unresolved.append({"key": key, "title": title, "reason": "live body unavailable"})
            unresolved_keys.add(key)
        content_status = "not_available"
        if directory:
            content_status = "media_only" if content_chars == 0 else (
                "preview_detected" if preview else "text_available"
            )
        rows.append(
            {
                "published_at": item["published_at"],
                "title": title,
                "url": item.get("url"),
                "biz": key[0],
                "mid": key[1],
                "idx": key[2],
                "author": item.get("author"),
                "status": status,
                "preview_detected": preview,
                "content_chars": content_chars,
                "content_status": content_status,
                "directory": directory,
            }
        )

    rows.sort(key=lambda row: row["published_at"], reverse=True)
    args.archive.mkdir(parents=True, exist_ok=True)
    csv_path = args.archive / "archive_index.csv"
    with csv_path.open("w", encoding="utf-8-sig", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=list(rows[0]) if rows else [])
        writer.writeheader()
        writer.writerows(rows)

    status_counts: dict[str, int] = {}
    for row in rows:
        status_counts[row["status"]] = status_counts.get(row["status"], 0) + 1
    summary = {
        "generated_at": datetime.now().astimezone().isoformat(timespec="seconds"),
        "discovered": len(discovered),
        "status_counts": status_counts,
        "preview_detected": sum(bool(row["preview_detected"]) for row in rows),
        "content_status_counts": {
            status: sum(row["content_status"] == status for row in rows)
            for status in sorted({row["content_status"] for row in rows})
        },
        "first_published_at": rows[-1]["published_at"] if rows else None,
        "last_published_at": rows[0]["published_at"] if rows else None,
        "unresolved": unresolved,
        "index_csv": str(csv_path.resolve()),
    }
    atomic_write_json(args.archive / "archive_summary.json", summary)
    report_lines = [
        "# 东函西数历史归档审计",
        "",
        f"- 账号：{args.account}",
        f"- 历史范围：{summary['first_published_at']} 至 {summary['last_published_at']}",
        f"- 历史索引发现：{summary['discovered']} 篇",
        f"- 成功下载：{status_counts.get('downloaded', 0)} 篇",
        f"- 重试后恢复：{status_counts.get('downloaded_retry', 0)} 篇",
        f"- 旧归档交叉恢复：{status_counts.get('legacy_archive', 0)} 篇",
        f"- 无法取得正文：{status_counts.get('failed_restricted', 0)} 篇",
        f"- 识别为付费导读：{summary['preview_detected']} 篇",
        f"- 仅剩媒体或空正文：{summary['content_status_counts'].get('media_only', 0)} 篇",
        f"- 历史分页是否完整：{str(bool(manifest.get('history_scan', {}).get('complete'))).lower()}",
        "",
        "完整逐篇索引见 `archive_index.csv`。",
        "",
        "## 仍需补齐正文",
        "",
    ]
    if unresolved:
        report_lines.extend(
            f"- {row['title']}：{row['reason']}"
            for row in unresolved
        )
    else:
        report_lines.append("- 无")
    preview_rows = [row for row in rows if row["preview_detected"]]
    report_lines.extend(["", "## 付费导读", ""])
    if preview_rows:
        report_lines.extend(
            f"- {row['published_at']} {row['title']}"
            for row in preview_rows
        )
    else:
        report_lines.append("- 无")
    (args.archive / "archive_report.md").write_text("\n".join(report_lines) + "\n", encoding="utf-8")
    print(json.dumps(summary, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
