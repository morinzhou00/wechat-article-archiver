"""Retry failed article bodies from a generated batch manifest.

This utility never prints or writes credential values. It reuses a credential
stored in Windows Credential Manager and keeps the original batch manifest
unchanged as an audit trail.
"""

from __future__ import annotations

import argparse
import json
from datetime import datetime
from pathlib import Path

from wechat_article_downloader.client import WeChatClient
from wechat_article_downloader.config import ConfigStore
from wechat_article_downloader.credentials import CredentialStore
from wechat_article_downloader.exporter import ArticleExporter
from wechat_article_downloader.utils import atomic_write_json, default_data_dir


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("manifest", type=Path)
    parser.add_argument("--output", type=Path, required=True, help="Archive root; account directories are created below it.")
    parser.add_argument("--credential", default="default")
    parser.add_argument("--report", type=Path)
    parser.add_argument("--limit", type=int)
    args = parser.parse_args()

    manifest = json.loads(args.manifest.read_text(encoding="utf-8"))
    failures = manifest.get("failures")
    if not isinstance(failures, list):
        raise SystemExit("The manifest does not contain a failures list.")
    if args.limit is not None:
        failures = failures[: args.limit]

    data_dir = default_data_dir()
    config = ConfigStore(data_dir).load()
    credential = CredentialStore(data_dir).get(args.credential)
    client = WeChatClient(
        timeout=config.timeout_seconds,
        interval_seconds=config.request_interval_seconds,
        credential=credential,
    )
    exporter = ArticleExporter()
    results: list[dict[str, object]] = []
    for index, failure in enumerate(failures, start=1):
        url = failure.get("url") if isinstance(failure, dict) else None
        title = failure.get("title") if isinstance(failure, dict) else None
        if not isinstance(url, str):
            results.append({"ok": False, "title": title, "error": "missing URL"})
            continue
        try:
            article = client.fetch_article(url, attempts=3)
            client.sanitize_media_urls(article)
            client.remove_remote_media(article)
            directory = exporter.prepare_directory(article, args.output)
            exported = exporter.export(article, directory, ["md", "json"])
            results.append({"ok": True, **exported.to_dict()})
        except Exception as exc:  # noqa: BLE001
            results.append(
                {
                    "ok": False,
                    "title": title,
                    "url": url,
                    "error": str(exc) or type(exc).__name__,
                }
            )
        print(
            f"[{index}/{len(failures)}] "
            f"{'OK' if results[-1]['ok'] else 'FAIL'} {title}",
            flush=True,
        )

    report = {
        "source_manifest": str(args.manifest.resolve()),
        "created_at": datetime.now().astimezone().isoformat(timespec="seconds"),
        "requested": len(failures),
        "succeeded": sum(bool(item.get("ok")) for item in results),
        "failed": sum(not bool(item.get("ok")) for item in results),
        "results": results,
    }
    report_path = args.report or args.manifest.with_name(
        f"retry-{datetime.now().strftime('%Y%m%d-%H%M%S')}.json"
    )
    atomic_write_json(report_path, report)
    print(json.dumps({k: report[k] for k in ("requested", "succeeded", "failed", "created_at")}, ensure_ascii=False))


if __name__ == "__main__":
    main()
