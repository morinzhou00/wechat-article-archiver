from __future__ import annotations

import os
import time
import uuid
from datetime import date, datetime
from pathlib import Path
from typing import Callable

import psutil

from . import __version__
from .client import WeChatClient
from .capture import build_account_home_url, default_wechat_roots, scan_credentials
from .config import ConfigStore
from .credentials import CredentialStore, auth_guidance
from .errors import AuthRequiredError, InvalidInputError, WeChatDownloaderError
from .exporter import ArticleExporter, discover_browser
from .ledger import parity_summary
from .models import DiscoveryResult, HistoryItem
from .provider import WeChatHistoryProvider
from .redaction import redact_value
from .resume import (
    checkpoint_path,
    item_key,
    load_checkpoint,
    make_fingerprint,
    save_checkpoint,
    scan_exported_keys,
)
from .utils import (
    append_jsonl,
    default_data_dir,
    now_iso,
    parse_formats,
    parse_iso_date,
    parse_url_fields,
)


class DownloadService:
    def __init__(self, data_dir: Path | None = None) -> None:
        self.data_dir = data_dir or default_data_dir()
        self.config_store = ConfigStore(self.data_dir)
        self.credentials = CredentialStore(self.data_dir)
        self.history_path = self.data_dir / "history.jsonl"
        self.started_at = time.time()
        self._overview_cache: tuple[float, dict[str, object]] | None = None

    def download_article(
        self,
        url: str,
        *,
        formats: list[str] | str | None = None,
        output_dir: str | Path | None = None,
        include_assets: bool | None = None,
        trigger: str = "cli",
    ) -> dict[str, object]:
        config = self.config_store.load()
        selected_formats = parse_formats(formats or config.default_formats)
        root = Path(output_dir or config.output_dir)
        if include_assets is not None and not isinstance(include_assets, bool):
            raise InvalidInputError("include_assets must be true or false.")
        include = config.include_assets if include_assets is None else include_assets

        def operation() -> dict[str, object]:
            client = WeChatClient(
                timeout=config.timeout_seconds,
                interval_seconds=config.request_interval_seconds,
            )
            article = client.fetch_article(url)
            client.sanitize_media_urls(article)
            exporter = ArticleExporter()
            directory = exporter.prepare_directory(article, root)
            if include:
                client.download_assets(article, directory)
            else:
                client.remove_remote_media(article)
            result = exporter.export(article, directory, selected_formats)
            return {"ok": True, "kind": "article", **result.to_dict()}

        return self._run("article", trigger, operation, {"url": url, "formats": selected_formats})

    def download_account(
        self,
        sample_url: str,
        *,
        credential_alias: str = "default",
        latest: int | None = None,
        on_date: str | None = None,
        since: str | None = None,
        until: str | None = None,
        max_pages: int | None = None,
        formats: list[str] | str | None = None,
        output_dir: str | Path | None = None,
        include_assets: bool | None = None,
        trigger: str = "cli",
        progress: Callable[[dict[str, object]], None] | None = None,
        resume: bool = True,
    ) -> dict[str, object]:
        config = self.config_store.load()
        selected_formats = parse_formats(formats or config.default_formats)
        exact_date = parse_iso_date(on_date, "date")
        start_date = parse_iso_date(since, "since")
        end_date = parse_iso_date(until, "until")
        if exact_date:
            start_date = end_date = exact_date
        if latest is None and start_date is None and end_date is None:
            raise InvalidInputError("Choose --latest, --date, --since, or --until for an account download.")
        if latest is not None and (on_date or since):
            raise InvalidInputError("--latest cannot be combined with --date or --since.")
        if latest is not None and (not isinstance(latest, int) or isinstance(latest, bool)):
            raise InvalidInputError("latest must be an integer.")
        if latest is not None and not 1 <= latest <= 100:
            raise InvalidInputError("latest must be between 1 and 100.")
        if start_date and end_date and start_date > end_date:
            raise InvalidInputError("since cannot be later than until.")
        page_limit = config.max_pages if max_pages is None else max_pages
        if not isinstance(page_limit, int) or isinstance(page_limit, bool):
            raise InvalidInputError("max_pages must be an integer.")
        if not 1 <= page_limit <= 200:
            raise InvalidInputError("max_pages must be between 1 and 200.")
        root = Path(output_dir or config.output_dir)
        if include_assets is not None and not isinstance(include_assets, bool):
            raise InvalidInputError("include_assets must be true or false.")
        include = config.include_assets if include_assets is None else include_assets

        def operation() -> dict[str, object]:
            credential = self.credentials.get(credential_alias)
            client = WeChatClient(
                timeout=config.timeout_seconds,
                interval_seconds=config.request_interval_seconds,
                credential=credential,
            )
            biz = _biz_from_sample_url(sample_url, client, credential)
            if not biz:
                raise AuthRequiredError(
                    "The account identifier could not be derived from the article or credential.",
                    details=auth_guidance(credential_alias),
                )
            provider = WeChatHistoryProvider(
                timeout=config.timeout_seconds,
                interval_seconds=config.request_interval_seconds,
            )
            fingerprint = make_fingerprint(
                biz,
                latest=latest,
                start_date=start_date,
                end_date=end_date,
                max_pages=page_limit,
            )
            resume_path = checkpoint_path(root, fingerprint)
            checkpoint = load_checkpoint(resume_path, fingerprint) if resume else None
            downloaded_keys: set[str] = scan_exported_keys(root, biz) if resume else set()
            if checkpoint:
                downloaded_keys.update(checkpoint["downloaded_keys"])
            failed_keys: dict[str, str] = dict(checkpoint["failed_keys"]) if checkpoint else {}

            def persist_progress(current: DiscoveryResult) -> None:
                save_checkpoint(
                    resume_path,
                    fingerprint,
                    discovered=current,
                    downloaded_keys=downloaded_keys,
                    failed_keys=failed_keys,
                )

            if checkpoint and checkpoint["complete"]:
                discovered = DiscoveryResult(
                    items=checkpoint["items"],
                    complete=True,
                    pages_scanned=checkpoint["pages_scanned"],
                    stop_reason=checkpoint["stop_reason"],
                    next_offset=checkpoint["next_offset"],
                )
            else:
                discovered = self._discover(
                    provider,
                    biz,
                    credential,
                    sample_url=sample_url,
                    latest=latest,
                    start_date=start_date,
                    end_date=end_date,
                    max_pages=page_limit,
                    progress=progress,
                    start_offset=checkpoint["next_offset"] if checkpoint else 0,
                    initial_items=checkpoint["items"] if checkpoint else None,
                    pages_scanned=checkpoint["pages_scanned"] if checkpoint else 0,
                    on_checkpoint=persist_progress,
                )
            exporter = ArticleExporter()
            results: list[dict[str, object]] = []
            failures: list[dict[str, str]] = []
            skipped_existing = 0
            for index, item in enumerate(discovered, start=1):
                key = item_key(item)
                if progress:
                    progress(
                        {
                            "phase": "download_article",
                            "index": index,
                            "total": len(discovered),
                            "title": item.title,
                            "published_at": item.published_at.isoformat(timespec="minutes"),
                            "resumed": key in downloaded_keys,
                        }
                    )
                if resume and key in downloaded_keys:
                    skipped_existing += 1
                    continue
                try:
                    article = client.fetch_article(item.url)
                    client.sanitize_media_urls(article)
                    directory = exporter.prepare_directory(article, root)
                    if include:
                        client.download_assets(article, directory)
                    else:
                        client.remove_remote_media(article)
                    exported = exporter.export(article, directory, selected_formats)
                    results.append(exported.to_dict())
                    downloaded_keys.add(key)
                    failed_keys.pop(key, None)
                    persist_progress(discovered)
                except WeChatDownloaderError as exc:
                    failed_keys[key] = f"{exc.code}: {exc}"
                    persist_progress(discovered)
                    failures.append(
                        redact_value({"url": item.url, "title": item.title, "error": str(exc), "code": exc.code})
                    )
            batch_directory = root.expanduser().resolve() / "_batches"
            batch_directory.mkdir(parents=True, exist_ok=True)
            manifest_path = batch_directory / f"{datetime.now().strftime('%Y%m%d-%H%M%S')}-{uuid.uuid4().hex[:8]}.json"
            manifest = {
                "ok": not failures,
                "kind": "account",
                "account_biz": biz,
                "selection": {
                    "latest": latest,
                    "date": on_date,
                    "since": since,
                    "until": until,
                    "max_pages": page_limit,
                },
                "discovered": [item.to_dict() for item in discovered],
                "history_scan": discovered.summary(),
                "resume": {
                    "enabled": resume,
                    "checkpoint": str(resume_path),
                    "resumed_discovery": bool(checkpoint),
                    "skipped_existing": skipped_existing,
                    "downloaded_this_run": len(results),
                    "failed": len(failures),
                },
                "downloads": results,
                "failures": failures,
                "warnings": (
                    []
                    if discovered.complete
                    else ["History scan reached max_pages before proving the requested range was complete."]
                ),
                "manifest": str(manifest_path.resolve()),
            }
            manifest["ok"] = not failures and discovered.complete
            persist_progress(discovered)
            manifest_path.write_text(__import__("json").dumps(manifest, ensure_ascii=False, indent=2), encoding="utf-8")
            return manifest

        return self._run(
            "account",
            trigger,
            operation,
            {
                "sample_url": sample_url,
                "credential_alias": credential_alias,
                "latest": latest,
                "date": on_date,
                "since": since,
                "until": until,
                "formats": selected_formats,
            },
        )

    def auth_capture(
        self,
        sample_url: str,
        *,
        alias: str = "default",
        watch_seconds: int = 120,
        since_minutes: int = 10,
        include_temp: bool = False,
        progress: Callable[[dict[str, object]], None] | None = None,
    ) -> dict[str, object]:
        if not 5 <= watch_seconds <= 600:
            raise InvalidInputError("watch_seconds must be between 5 and 600.")
        config = self.config_store.load()
        client = WeChatClient(
            timeout=config.timeout_seconds,
            interval_seconds=config.request_interval_seconds,
        )
        biz = _biz_from_sample_url(sample_url, client, {})
        if not biz:
            raise InvalidInputError("The sample article did not expose a public-account identifier.")
        home_url = build_account_home_url(biz)
        deadline = time.monotonic() + watch_seconds
        attempted: set[tuple[str, ...]] = set()
        seen_versions: set[tuple[str, int, int]] = set()
        roots = default_wechat_roots(include_temp=include_temp)
        last_report: dict[str, object] | None = None
        last_error = ""
        while time.monotonic() <= deadline:
            report = scan_credentials(
                biz,
                since_minutes=since_minutes,
                seen_versions=seen_versions,
                roots=roots,
            )
            last_report = report.summary()
            if progress:
                progress(
                    {
                        "phase": "scan",
                        "home_url": home_url,
                        "candidate_count": len(report.candidates),
                        "scanned_files": report.scanned_files,
                        "scanned_bytes": report.scanned_bytes,
                    }
                )
            for candidate in report.candidates:
                identity = tuple(
                    candidate.fields.get(field, "")
                    for field in ("biz", "uin", "key", "pass_ticket", "appmsg_token", "poc_token")
                )
                if identity in attempted:
                    continue
                attempted.add(identity)
                credential = dict(candidate.fields)
                credential["request_url"] = candidate.request_url
                provider = WeChatHistoryProvider(
                    timeout=config.timeout_seconds,
                    interval_seconds=config.request_interval_seconds,
                )
                try:
                    items, _next, _more = provider.list_page(
                        biz,
                        credential,
                        offset=0,
                        count=1,
                        referer=sample_url,
                    )
                except WeChatDownloaderError as exc:
                    last_error = f"{exc.code}: {exc}"
                    continue
                if not items:
                    last_error = "REMOTE_ERROR: the accepted response contained no history articles"
                    continue
                summary = self.credentials.save_fields(alias, credential, origin="local-wechat-cache")
                return {
                    "ok": True,
                    "credential": summary.to_dict(),
                    "validated_articles": len(items),
                    "home_url": home_url,
                    "scan": last_report,
                }
            time.sleep(5.0)
        raise AuthRequiredError(
            "No WeChat credential was accepted before the capture window expired.",
            details={
                "home_url": home_url,
                "action": "Keep WeChat signed in and open this URL inside WeChat, then run auth capture again.",
                "last_validation_error": last_error or None,
                "last_scan": last_report,
            },
        )

    def auth_guide(self, sample_url: str, alias: str = "default") -> dict[str, object]:
        config = self.config_store.load()
        client = WeChatClient(
            timeout=config.timeout_seconds,
            interval_seconds=config.request_interval_seconds,
        )
        biz = _biz_from_sample_url(sample_url, client, {})
        if not biz:
            raise InvalidInputError("The sample article did not expose a public-account identifier.")
        return {
            "ok": True,
            "biz": biz,
            "account_name": None,
            "home_url": build_account_home_url(biz),
            **auth_guidance(alias),
        }

    def validate_credential(self, sample_url: str, alias: str = "default") -> dict[str, object]:
        """Check a stored credential with one bounded history request."""
        config = self.config_store.load()
        credential = self.credentials.get(alias)
        client = WeChatClient(
            timeout=config.timeout_seconds,
            interval_seconds=config.request_interval_seconds,
            credential=credential,
        )
        biz = _biz_from_sample_url(sample_url, client, credential)
        if not biz:
            raise InvalidInputError("The sample article did not expose a public-account identifier.")
        provider = WeChatHistoryProvider(
            timeout=config.timeout_seconds,
            interval_seconds=config.request_interval_seconds,
        )
        items, _, _ = provider.list_page(
            biz,
            credential,
            offset=0,
            count=1,
            referer=sample_url,
        )
        return {"ok": True, "alias": alias, "validated_articles": len(items)}

    def _discover(
        self,
        provider: WeChatHistoryProvider,
        biz: str,
        credential: dict[str, str],
        *,
        sample_url: str,
        latest: int | None,
        start_date: date | None,
        end_date: date | None,
        max_pages: int,
        progress: Callable[[dict[str, object]], None] | None = None,
        start_offset: int = 0,
        initial_items: list[HistoryItem] | None = None,
        pages_scanned: int = 0,
        on_checkpoint: Callable[[DiscoveryResult], None] | None = None,
    ) -> DiscoveryResult:
        selected: list[HistoryItem] = list(initial_items or [])
        seen: set[str] = {item.url for item in selected}
        offset = start_offset
        stop_reason = "max_pages"
        complete = False
        next_unread_offset: int | None = offset
        for _ in range(max_pages):
            pages_scanned += 1
            items, next_offset, can_continue = provider.list_page(
                biz,
                credential,
                offset=offset,
                count=10,
                referer=sample_url,
            )
            if progress:
                progress(
                    {
                        "phase": "history_page",
                        "page": pages_scanned,
                        "items": len(items),
                        "can_continue": can_continue,
                    }
                )
            if not items:
                if can_continue:
                    candidate_offset = next_offset if next_offset is not None else offset + 10
                    if candidate_offset > offset:
                        offset = candidate_offset
                        next_unread_offset = offset
                        if on_checkpoint:
                            on_checkpoint(
                                DiscoveryResult(
                                    items=sorted(selected, key=lambda item: item.published_at, reverse=True),
                                    complete=False,
                                    pages_scanned=pages_scanned,
                                    stop_reason="in_progress",
                                    next_offset=offset,
                                )
                            )
                        continue
                complete = True
                stop_reason = "end_of_history"
                next_unread_offset = None
                break
            for item in items:
                if item.url in seen:
                    continue
                seen.add(item.url)
                item_date = item.published_at.date()
                if end_date and item_date > end_date:
                    continue
                if start_date and item_date < start_date:
                    continue
                selected.append(item)
                if latest and len(selected) >= latest:
                        result = DiscoveryResult(
                        items=selected[:latest],
                        complete=True,
                        pages_scanned=pages_scanned,
                        stop_reason="selection_satisfied",
                        next_offset=next_offset,
                    )
                        if on_checkpoint:
                            on_checkpoint(result)
                        return result
            oldest = min(item.published_at.date() for item in items)
            if start_date and oldest < start_date:
                complete = True
                stop_reason = "date_boundary_reached"
                next_unread_offset = next_offset
                break
            if not can_continue:
                complete = True
                stop_reason = "end_of_history"
                next_unread_offset = None
                break
            candidate_offset = next_offset if next_offset is not None else offset + len(items)
            if candidate_offset <= offset:
                stop_reason = "non_advancing_offset"
                next_unread_offset = candidate_offset
                break
            offset = candidate_offset
            next_unread_offset = offset
            if on_checkpoint:
                on_checkpoint(
                    DiscoveryResult(
                        items=sorted(selected, key=lambda item: item.published_at, reverse=True),
                        complete=False,
                        pages_scanned=pages_scanned,
                        stop_reason="in_progress",
                        next_offset=offset,
                    )
                )
        selected.sort(key=lambda item: item.published_at, reverse=True)
        result = DiscoveryResult(
            items=selected[:latest] if latest else selected,
            complete=complete,
            pages_scanned=pages_scanned,
            stop_reason=stop_reason,
            next_offset=next_unread_offset,
        )
        if on_checkpoint:
            on_checkpoint(result)
        return result

    def status(self) -> dict[str, object]:
        process = psutil.Process(os.getpid())
        config = self.config_store.load()
        history = self.recent_history(200)
        return {
            "ok": True,
            "version": __version__,
            "pid": os.getpid(),
            "uptime_seconds": round(time.time() - self.started_at, 1),
            "cpu_percent": process.cpu_percent(interval=None),
            "memory_rss_bytes": process.memory_info().rss,
            "handles": process.num_handles() if hasattr(process, "num_handles") else None,
            "history_count": len(history),
            "last_operation": history[-1] if history else None,
            "credential_aliases": [summary.to_dict() for summary in self.credentials.summaries()],
            "output_dir": config.output_dir,
            "revision": self.history_path.stat().st_mtime_ns if self.history_path.exists() else 0,
        }

    def overview(self) -> dict[str, object]:
        if self._overview_cache and time.monotonic() - self._overview_cache[0] < 5.0:
            return self._overview_cache[1]
        config = self.config_store.load()
        output = Path(config.output_dir).expanduser()
        output_scan = _scan_output(output)
        result = {
            "status": self.status(),
            "config": config.to_dict(),
            "data": {
                "article_manifests": output_scan["article_manifests"],
                "batch_manifests": output_scan["batch_manifests"],
                "data_dir": str(self.data_dir.resolve()),
                "history_path": str(self.history_path.resolve()),
                "output_exists": output.exists(),
                "output_size_bytes": output_scan["size_bytes"],
                "integrity": output_scan["integrity"],
                "scan": {
                    "files_seen": output_scan["files_seen"],
                    "directories_seen": output_scan["directories_seen"],
                    "truncated": output_scan["truncated"],
                    "truncation_reasons": output_scan["truncation_reasons"],
                },
            },
            "sources": [
                {"name": "Article HTML/assets", "endpoint": "https://mp.weixin.qq.com", "mode": "read-only HTTPS"},
                {
                    "name": "Account history",
                    "endpoint": "https://mp.weixin.qq.com/mp/profile_ext",
                    "mode": "read-only HTTPS with user credential",
                },
                {
                    "name": "Credentials",
                    "endpoint": "Windows Credential Manager",
                    "mode": "local secret storage; values never returned by API",
                },
            ],
            "pipeline": [
                "Validate WeChat URL and selection",
                "Fetch public article or authenticated history list",
                "Parse metadata and article body",
                "Download selected media with size limits",
                "Export requested formats",
                "Persist redacted manifest and bounded operation history",
            ],
            "security": {
                "bind": "loopback only",
                "mutation_protection": "application/json + X-Wechat-Console header + same-origin check",
                "secrets_in_web": False,
                "remote_fallback": False,
                "destructive_web_actions": False,
            },
            "parity": parity_summary(),
            "doctor": self.doctor(),
            "history": self.recent_history(50),
        }
        self._overview_cache = (time.monotonic(), result)
        return result

    def doctor(self) -> dict[str, object]:
        browser = discover_browser()
        return {
            "ok": True,
            "version": __version__,
            "python": os.sys.version.split()[0],
            "data_dir": str(self.data_dir.resolve()),
            "config_path": str(self.config_store.path.resolve()),
            "pdf_browser": str(browser) if browser else None,
            "pdf_ready": browser is not None,
            "credential_store": "Windows Credential Manager via keyring",
            "credentials": [summary.to_dict() for summary in self.credentials.summaries()],
            "network_endpoints": [
                "https://mp.weixin.qq.com",
                "HTTPS WeChat/Tencent CDN hosts ending in qpic.cn, qlogo.cn, wx.qq.com, or video.qq.com",
            ],
        }

    def recent_history(self, limit: int = 50) -> list[dict[str, object]]:
        if not self.history_path.exists():
            return []
        rows: list[dict[str, object]] = []
        for line in self.history_path.read_text(encoding="utf-8").splitlines()[-limit:]:
            try:
                item = __import__("json").loads(line)
                if isinstance(item, dict):
                    rows.append(item)
            except ValueError:
                continue
        return rows

    def _run(
        self,
        kind: str,
        trigger: str,
        operation: Callable[[], dict[str, object]],
        inputs: dict[str, object],
    ) -> dict[str, object]:
        operation_id = uuid.uuid4().hex
        started = time.monotonic()
        started_at = now_iso()
        try:
            result = operation()
            record = {
                "id": operation_id,
                "kind": kind,
                "trigger": trigger,
                "started_at": started_at,
                "duration_seconds": round(time.monotonic() - started, 3),
                "result": "ok" if result.get("ok", True) else "partial",
                "inputs": _redact_inputs(inputs),
                "error": None,
                "retry_backoff": "shared minimum interval",
            }
            append_jsonl(self.history_path, record)
            result["operation_id"] = operation_id
            return result
        except Exception as exc:
            record = {
                "id": operation_id,
                "kind": kind,
                "trigger": trigger,
                "started_at": started_at,
                "duration_seconds": round(time.monotonic() - started, 3),
                "result": "error",
                "inputs": _redact_inputs(inputs),
                "error": redact_value(
                    {"code": getattr(exc, "code", "UNEXPECTED_ERROR"), "message": str(exc)}
                ),
                "retry_backoff": "shared minimum interval",
            }
            append_jsonl(self.history_path, record)
            raise


def _biz_from_sample_url(sample_url: str, client: WeChatClient, credential: dict[str, str]) -> str | None:
    """Prefer the public identifier embedded in the URL so auth never depends on a captcha page."""
    biz = parse_url_fields(sample_url).get("biz")
    if biz:
        return biz
    if credential.get("biz"):
        return credential["biz"]
    article = client.fetch_article(sample_url)
    return article.ref.biz


def _redact_inputs(inputs: dict[str, object]) -> dict[str, object]:
    return redact_value(inputs)


def _scan_output(
    path: Path,
    *,
    max_entries: int = 10_000,
    max_directories: int = 5_000,
    max_seconds: float = 2.0,
) -> dict[str, object]:
    result: dict[str, object] = {
        "article_manifests": 0,
        "batch_manifests": 0,
        "size_bytes": 0,
        "files_seen": 0,
        "directories_seen": 0,
        "integrity": "ok",
        "truncated": False,
        "truncation_reasons": [],
    }
    if not path.exists():
        return result
    deadline = time.monotonic() + max_seconds
    stack = [path]
    reasons: list[str] = []
    while stack:
        if time.monotonic() > deadline:
            reasons.append("time_budget")
            break
        if int(result["directories_seen"]) >= max_directories:
            reasons.append("directory_budget")
            break
        directory = stack.pop()
        result["directories_seen"] = int(result["directories_seen"]) + 1
        try:
            entries = os.scandir(directory)
        except OSError:
            continue
        with entries:
            for entry in entries:
                if int(result["files_seen"]) >= max_entries:
                    reasons.append("entry_budget")
                    stack.clear()
                    break
                try:
                    if entry.is_dir(follow_symlinks=False):
                        stack.append(Path(entry.path))
                        continue
                    if not entry.is_file(follow_symlinks=False):
                        continue
                    size = entry.stat(follow_symlinks=False).st_size
                except OSError:
                    continue
                result["files_seen"] = int(result["files_seen"]) + 1
                result["size_bytes"] = int(result["size_bytes"]) + size
                if entry.name == "manifest.json":
                    result["article_manifests"] = int(result["article_manifests"]) + 1
                    if size <= 0:
                        result["integrity"] = "needs-review"
                elif Path(entry.path).parent.name == "_batches" and entry.name.endswith(".json"):
                    result["batch_manifests"] = int(result["batch_manifests"]) + 1
    result["truncated"] = bool(reasons)
    result["truncation_reasons"] = sorted(set(reasons))
    if reasons and result["integrity"] == "ok":
        result["integrity"] = "incomplete-scan"
    return result
