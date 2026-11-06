from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path
from typing import Any

from .config import RuntimeConfig
from .errors import InvalidInputError, WeChatDownloaderError
from .merge import merge_archives
from .redaction import redact_value
from .service import DownloadService


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="wechat-download",
        description="Download, filter, and export WeChat public-account articles.",
    )
    parser.add_argument("--json", action="store_true", help="Emit machine-readable JSON.")
    subcommands = parser.add_subparsers(dest="command", required=True)

    article = subcommands.add_parser("article", help="Download one public article.")
    article.add_argument("url")
    _download_options(article)

    account = subcommands.add_parser("account", help="Download account history selected by count or date.")
    account.add_argument("sample_url", help="Any public article URL from the account.")
    account.add_argument("--credential", default="default")
    selection = account.add_mutually_exclusive_group(required=True)
    selection.add_argument("--latest", type=int)
    selection.add_argument("--date")
    selection.add_argument("--since")
    account.add_argument("--until")
    account.add_argument("--max-pages", type=int)
    _download_options(account)

    history = subcommands.add_parser(
        "history",
        help="Capture a fresh local WeChat credential and archive an account's complete history.",
    )
    history.add_argument("sample_url", help="Any public article URL from the target account.")
    history.add_argument("--credential", default="default")
    history.add_argument("--since", default="2000-01-01")
    history.add_argument("--until")
    history.add_argument("--max-pages", type=int, default=200)
    history.add_argument("--watch-seconds", type=int, default=180)
    history.add_argument(
        "--include-temp",
        action="store_true",
        help="Also scan recent Local/Temp files if the normal WeChat data roots cannot be found.",
    )
    history.add_argument(
        "--reuse-credential",
        action="store_true",
        help="Reuse an existing validated credential instead of waiting for a fresh one.",
    )
    _download_options(history)
    history.set_defaults(formats="md,json", assets=False)

    auth = subcommands.add_parser("auth", help="Guide, capture, inspect, or remove local credentials.")
    auth_commands = auth.add_subparsers(dest="auth_command", required=True)
    guide = auth_commands.add_parser("guide", help="Generate the account-home URL and safe steps.")
    guide.add_argument("sample_url")
    guide.add_argument("--alias", default="default")
    capture = auth_commands.add_parser("capture", help="Validate fresh credentials from the local WeChat cache.")
    capture.add_argument("sample_url")
    capture.add_argument("--alias", default="default")
    capture.add_argument("--watch-seconds", type=int, default=120)
    capture.add_argument("--since-minutes", type=int, default=10)
    capture.add_argument(
        "--include-temp",
        action="store_true",
        help="Also scan recent Local/Temp files; use only if normal WeChat roots fail.",
    )
    import_parser = auth_commands.add_parser("import", help="Fallback hidden-prompt credential import.")
    import_parser.add_argument("alias", nargs="?", default="default")
    status = auth_commands.add_parser("status", help="Show aliases and field names, never values.")
    status.add_argument("alias", nargs="?")
    delete = auth_commands.add_parser("delete", help="Delete one local credential.")
    delete.add_argument("alias")
    delete.add_argument("--yes", action="store_true")

    config = subcommands.add_parser("config", help="Show or change runtime configuration.")
    config_commands = config.add_subparsers(dest="config_command", required=True)
    config_commands.add_parser("show")
    set_config = config_commands.add_parser("set")
    set_config.add_argument("--output-dir")
    set_config.add_argument("--request-interval", type=float)
    set_config.add_argument("--timeout", type=int)
    set_config.add_argument("--max-pages", type=int)
    set_config.add_argument("--formats")
    set_config.add_argument("--include-assets", choices=("true", "false"))
    set_config.add_argument("--console-port", type=int)

    subcommands.add_parser("doctor", help="Check dependencies and runtime paths.")
    subcommands.add_parser("status", help="Show lightweight local status.")
    merge = subcommands.add_parser("merge-archive", help="Merge history downloads into a flat archive.")
    merge.add_argument("source")
    merge.add_argument("target")
    merge.add_argument("--dry-run", action="store_true")
    web = subcommands.add_parser("web", help="Run the loopback-only control console.")
    web.add_argument("--host", default="127.0.0.1")
    web.add_argument("--port", type=int)
    web.add_argument("--open", action="store_true", dest="open_browser")
    return parser


def _download_options(parser: argparse.ArgumentParser) -> None:
    parser.add_argument("--formats", default=None, help="Comma-separated: html,md,pdf,docx,json,csv,txt,mhtml.")
    parser.add_argument("--output")
    assets = parser.add_mutually_exclusive_group()
    assets.add_argument("--assets", action="store_true", dest="assets")
    assets.add_argument("--no-assets", action="store_false", dest="assets")
    parser.set_defaults(assets=None)


def run(argv: list[str] | None = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)
    service = DownloadService()
    try:
        result = dispatch(args, service)
    except WeChatDownloaderError as exc:
        _emit(exc.as_dict(), as_json=args.json, error=True)
        return _exit_code(exc.code)
    except KeyboardInterrupt:
        _emit(
            {"ok": False, "error": "INTERRUPTED", "message": "Operation interrupted by the user."},
            as_json=args.json,
            error=True,
        )
        return 130
    except Exception as exc:
        _emit(
            redact_value({"ok": False, "error": "UNEXPECTED_ERROR", "message": str(exc)}),
            as_json=args.json,
            error=True,
        )
        return 1
    if result is not None:
        _emit(result, as_json=args.json)
    return 0 if result is None or result.get("ok", True) else 7


def dispatch(args: argparse.Namespace, service: DownloadService) -> dict[str, object] | None:
    if args.command == "article":
        return service.download_article(
            args.url,
            formats=args.formats,
            output_dir=args.output,
            include_assets=args.assets,
        )
    if args.command == "account":
        return service.download_account(
            args.sample_url,
            credential_alias=args.credential,
            latest=args.latest,
            on_date=args.date,
            since=args.since,
            until=args.until,
            max_pages=args.max_pages,
            formats=args.formats,
            output_dir=args.output,
            include_assets=args.assets,
        )
    if args.command == "history":
        guide = service.auth_guide(args.sample_url, args.credential)
        captured = None
        if not args.reuse_credential:
            if not args.json:
                print("请把下面链接发送到微信“文件传输助手”，并在微信内打开一次：", file=sys.stderr)
                print(guide["home_url"], file=sys.stderr)
                print("正在本机验证微信登录态；不会读取或输出其他网站 Cookie。", file=sys.stderr)
            captured = service.auth_capture(
                args.sample_url,
                alias=args.credential,
                watch_seconds=args.watch_seconds,
                since_minutes=max(10, args.watch_seconds // 60 + 5),
                include_temp=args.include_temp,
                progress=None if args.json else _capture_progress,
            )
        result = service.download_account(
            args.sample_url,
            credential_alias=args.credential,
            since=args.since,
            until=args.until,
            max_pages=args.max_pages,
            formats=args.formats,
            output_dir=args.output,
            include_assets=args.assets,
            progress=None if args.json else _history_progress,
        )
        if captured is not None:
            result["auth_capture"] = captured
        return result
    if args.command == "auth":
        if args.auth_command == "guide":
            return service.auth_guide(args.sample_url, args.alias)
        if args.auth_command == "capture":
            guide = service.auth_guide(args.sample_url, args.alias)
            print("请把下面链接发送到微信“文件传输助手”，并在微信内打开：", file=sys.stderr)
            print(guide["home_url"], file=sys.stderr)
            print("正在本机扫描并验证新鲜凭据；不会输出密钥值。", file=sys.stderr)
            return service.auth_capture(
                args.sample_url,
                alias=args.alias,
                watch_seconds=args.watch_seconds,
                since_minutes=args.since_minutes,
                include_temp=args.include_temp,
                progress=None if args.json else _capture_progress,
            )
        if args.auth_command == "import":
            return {"ok": True, "credential": service.credentials.import_interactive(args.alias).to_dict()}
        if args.auth_command == "status":
            summaries = [item.to_dict() for item in service.credentials.summaries()]
            if args.alias:
                summaries = [item for item in summaries if item["alias"] == args.alias]
            return {"ok": True, "credentials": summaries}
        if args.auth_command == "delete":
            if not args.yes:
                answer = input(f"Delete local credential '{args.alias}' from Windows Credential Manager? [y/N] ")
                if answer.strip().lower() not in {"y", "yes"}:
                    return {"ok": True, "deleted": False, "cancelled": True, "alias": args.alias}
            return {"ok": True, "deleted": service.credentials.delete(args.alias), "alias": args.alias}
    if args.command == "config":
        if args.config_command == "show":
            return {"ok": True, "config": service.config_store.load().to_dict()}
        changes: dict[str, object] = {}
        mapping = {
            "output_dir": args.output_dir,
            "request_interval_seconds": args.request_interval,
            "timeout_seconds": args.timeout,
            "max_pages": args.max_pages,
            "default_formats": args.formats,
            "console_port": args.console_port,
        }
        changes.update({key: value for key, value in mapping.items() if value is not None})
        if args.include_assets is not None:
            changes["include_assets"] = args.include_assets == "true"
        if not changes:
            raise InvalidInputError("config set requires at least one option.")
        return {"ok": True, "config": service.config_store.update(changes).to_dict()}
    if args.command == "doctor":
        return service.doctor()
    if args.command == "status":
        return service.status()
    if args.command == "merge-archive":
        return merge_archives(Path(args.source), Path(args.target), dry_run=args.dry_run)
    if args.command == "web":
        from .server import run_server

        config = service.config_store.load()
        run_server(
            service,
            host=args.host,
            port=args.port or config.console_port,
            open_browser=args.open_browser,
        )
        return None
    raise InvalidInputError("Unknown command.")


def _capture_progress(event: dict[str, object]) -> None:
    print(
        f"扫描 {event.get('scanned_files', 0)} 个近期文件，发现 "
        f"{event.get('candidate_count', 0)} 个候选……",
        file=sys.stderr,
    )


def _history_progress(event: dict[str, object]) -> None:
    if event.get("phase") == "history_page":
        print(
            f"历史第 {event.get('page')} 页：本页 {event.get('items')} 条，"
            f"可继续={event.get('can_continue')}",
            file=sys.stderr,
        )
    elif event.get("phase") == "download_article":
        action = "已有，跳过" if event.get("resumed") else "下载"
        print(
            f"{action} {event.get('index')}/{event.get('total')}："
            f"{event.get('published_at')} {event.get('title')}",
            file=sys.stderr,
        )


def _emit(payload: dict[str, object], *, as_json: bool, error: bool = False) -> None:
    stream = sys.stderr if error else sys.stdout
    if as_json:
        print(json.dumps(payload, ensure_ascii=False, indent=2, default=_json_default), file=stream)
        return
    if payload.get("ok") is False:
        print(f"[{payload.get('error', 'ERROR')}] {payload.get('message', '')}", file=stream)
        details = payload.get("details")
        if details:
            print(json.dumps(details, ensure_ascii=False, indent=2, default=_json_default), file=stream)
        return
    print(json.dumps(payload, ensure_ascii=False, indent=2, default=_json_default), file=stream)


def _json_default(value: Any) -> str:
    if isinstance(value, Path):
        return str(value)
    if isinstance(value, RuntimeConfig):
        return json.dumps(value.to_dict(), ensure_ascii=False)
    return str(value)


def _exit_code(code: str) -> int:
    return {
        "INVALID_INPUT": 2,
        "AUTH_REQUIRED": 3,
        "DEPENDENCY_MISSING": 4,
        "REMOTE_ERROR": 5,
        "EXPORT_ERROR": 6,
    }.get(code, 1)


def main() -> None:
    raise SystemExit(run())


if __name__ == "__main__":
    main()
