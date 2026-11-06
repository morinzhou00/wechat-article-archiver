from __future__ import annotations

import json
import secrets
import threading
import uuid
import webbrowser
from concurrent.futures import ThreadPoolExecutor
from dataclasses import dataclass, field
from datetime import datetime
from http import HTTPStatus
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from typing import Callable
from urllib.parse import urlparse

from .errors import InvalidInputError, WeChatDownloaderError
from .ledger import parity_summary
from .redaction import redact_value
from .service import DownloadService


STATIC_DIR = Path(__file__).with_name("static")
LOOPBACK_HOSTS = {"127.0.0.1", "::1", "localhost"}


@dataclass(slots=True)
class Job:
    id: str
    kind: str
    state: str = "queued"
    created_at: str = field(default_factory=lambda: datetime.now().astimezone().isoformat(timespec="seconds"))
    result: dict[str, object] | None = None
    error: dict[str, object] | None = None

    def to_dict(self) -> dict[str, object]:
        return {
            "id": self.id,
            "kind": self.kind,
            "state": self.state,
            "created_at": self.created_at,
            "result": self.result,
            "error": self.error,
        }


class JobQueue:
    def __init__(self, workers: int = 2, capacity: int = 8) -> None:
        self._executor = ThreadPoolExecutor(max_workers=workers, thread_name_prefix="wechat-console")
        self._slots = threading.BoundedSemaphore(capacity)
        self._lock = threading.Lock()
        self._jobs: dict[str, Job] = {}

    def submit(self, kind: str, operation: Callable[[], dict[str, object]]) -> Job:
        if not self._slots.acquire(blocking=False):
            raise InvalidInputError("The local job queue is full; wait for an existing operation to finish.")
        job = Job(id=uuid.uuid4().hex, kind=kind)
        with self._lock:
            self._jobs[job.id] = job
            self._trim()
        self._executor.submit(self._run, job, operation)
        return job

    def _run(self, job: Job, operation: Callable[[], dict[str, object]]) -> None:
        job.state = "running"
        try:
            job.result = operation()
            job.state = "succeeded" if job.result.get("ok", True) else "partial"
        except WeChatDownloaderError as exc:
            job.error = exc.as_dict()
            job.state = "failed"
        except Exception as exc:
            job.error = redact_value({"ok": False, "error": "UNEXPECTED_ERROR", "message": str(exc)})
            job.state = "failed"
        finally:
            self._slots.release()

    def get(self, job_id: str) -> Job | None:
        with self._lock:
            return self._jobs.get(job_id)

    def list(self) -> list[dict[str, object]]:
        with self._lock:
            return [job.to_dict() for job in reversed(list(self._jobs.values()))]

    def _trim(self) -> None:
        if len(self._jobs) <= 100:
            return
        removable = [key for key, value in self._jobs.items() if value.state in {"succeeded", "failed"}]
        for key in removable[: len(self._jobs) - 100]:
            self._jobs.pop(key, None)


class ConsoleServer(ThreadingHTTPServer):
    daemon_threads = True

    def __init__(self, address: tuple[str, int], service: DownloadService) -> None:
        super().__init__(address, ConsoleHandler)
        self.service = service
        self.session_token = secrets.token_urlsafe(24)
        self.jobs = JobQueue()


class ConsoleHandler(BaseHTTPRequestHandler):
    server: ConsoleServer

    def do_GET(self) -> None:  # noqa: N802
        if not self._valid_host():
            return
        path = urlparse(self.path).path
        if path == "/":
            return self._static("index.html", "text/html; charset=utf-8")
        if path == "/app.css":
            return self._static("app.css", "text/css; charset=utf-8")
        if path == "/app.js":
            return self._static("app.js", "application/javascript; charset=utf-8")
        if path == "/api/session":
            return self._json({"ok": True, "token": self.server.session_token})
        if path == "/api/status":
            return self._json(self.server.service.status())
        if path == "/api/overview":
            return self._json(self.server.service.overview())
        if path == "/api/history":
            return self._json({"ok": True, "history": self.server.service.recent_history(100)})
        if path == "/api/parity":
            return self._json({"ok": True, **parity_summary()})
        if path == "/api/config":
            return self._json({"ok": True, "config": self.server.service.config_store.load().to_dict()})
        if path == "/api/jobs":
            return self._json({"ok": True, "jobs": self.server.jobs.list()})
        if path.startswith("/api/jobs/"):
            job = self.server.jobs.get(path.rsplit("/", 1)[-1])
            return self._json(job.to_dict() if job else {"ok": False, "error": "NOT_FOUND"}, 200 if job else 404)
        return self._json({"ok": False, "error": "NOT_FOUND"}, HTTPStatus.NOT_FOUND)

    def do_POST(self) -> None:  # noqa: N802
        if not self._valid_host():
            return
        path = urlparse(self.path).path
        if not self._authorized_mutation():
            return
        try:
            payload = self._read_json()
            if path == "/api/article":
                job = self.server.jobs.submit(
                    "article",
                    lambda: self.server.service.download_article(
                        str(payload.get("url", "")),
                        formats=payload.get("formats"),
                        output_dir=_optional(payload, "output"),
                        include_assets=_optional_boolean(payload, "assets"),
                        trigger="web",
                    ),
                )
                return self._json({"ok": True, "job": job.to_dict()}, HTTPStatus.ACCEPTED)
            if path == "/api/account":
                job = self.server.jobs.submit(
                    "account",
                    lambda: self.server.service.download_account(
                        str(payload.get("sample_url", "")),
                        credential_alias=str(payload.get("credential") or "default"),
                        latest=_integer(payload.get("latest")),
                        on_date=_optional(payload, "date"),
                        since=_optional(payload, "since"),
                        until=_optional(payload, "until"),
                        max_pages=_integer(payload.get("max_pages")),
                        formats=payload.get("formats"),
                        output_dir=_optional(payload, "output"),
                        include_assets=_optional_boolean(payload, "assets"),
                        trigger="web",
                    ),
                )
                return self._json({"ok": True, "job": job.to_dict()}, HTTPStatus.ACCEPTED)
            if path == "/api/config":
                allowed = {
                    "output_dir",
                    "request_interval_seconds",
                    "timeout_seconds",
                    "max_pages",
                    "include_assets",
                    "default_formats",
                    "console_port",
                }
                changes = {key: value for key, value in payload.items() if key in allowed}
                if set(payload) - allowed:
                    raise InvalidInputError("The configuration payload contains unsupported fields.")
                config = self.server.service.config_store.update(changes)
                return self._json({"ok": True, "config": config.to_dict()})
            return self._json({"ok": False, "error": "NOT_FOUND"}, HTTPStatus.NOT_FOUND)
        except WeChatDownloaderError as exc:
            return self._json(exc.as_dict(), HTTPStatus.BAD_REQUEST)
        except (ValueError, TypeError) as exc:
            return self._json(
                redact_value({"ok": False, "error": "INVALID_INPUT", "message": str(exc)}),
                HTTPStatus.BAD_REQUEST,
            )

    def do_OPTIONS(self) -> None:  # noqa: N802
        if not self._valid_host():
            return
        self.send_response(HTTPStatus.METHOD_NOT_ALLOWED)
        self._security_headers()
        self.end_headers()

    def _authorized_mutation(self) -> bool:
        if self.headers.get("Content-Type", "").split(";", 1)[0].strip() != "application/json":
            self._json({"ok": False, "error": "JSON_REQUIRED"}, HTTPStatus.UNSUPPORTED_MEDIA_TYPE)
            return False
        if not secrets.compare_digest(self.headers.get("X-Wechat-Console", ""), self.server.session_token):
            self._json({"ok": False, "error": "SESSION_REQUIRED"}, HTTPStatus.FORBIDDEN)
            return False
        origin = self.headers.get("Origin")
        if origin:
            parsed = urlparse(origin)
            if parsed.hostname not in LOOPBACK_HOSTS or parsed.port != self.server.server_port:
                self._json({"ok": False, "error": "ORIGIN_REJECTED"}, HTTPStatus.FORBIDDEN)
                return False
        return True

    def _valid_host(self) -> bool:
        value = self.headers.get("Host", "")
        try:
            parsed = urlparse("//" + value)
            hostname = (parsed.hostname or "").casefold()
            port = parsed.port
        except ValueError:
            hostname, port = "", None
        if hostname not in LOOPBACK_HOSTS or port != self.server.server_port:
            self._json({"ok": False, "error": "HOST_REJECTED"}, HTTPStatus.FORBIDDEN)
            return False
        return True

    def _read_json(self) -> dict[str, object]:
        length = int(self.headers.get("Content-Length") or 0)
        if not 0 < length <= 32 * 1024:
            raise InvalidInputError("JSON body must be between 1 byte and 32 KiB.")
        payload = json.loads(self.rfile.read(length))
        if not isinstance(payload, dict):
            raise InvalidInputError("JSON body must be an object.")
        return payload

    def _static(self, filename: str, content_type: str) -> None:
        content = (STATIC_DIR / filename).read_bytes()
        self.send_response(HTTPStatus.OK)
        self.send_header("Content-Type", content_type)
        self.send_header("Content-Length", str(len(content)))
        self._security_headers()
        self.end_headers()
        self.wfile.write(content)

    def _json(self, payload: dict[str, object], status: int = HTTPStatus.OK) -> None:
        content = json.dumps(payload, ensure_ascii=False, separators=(",", ":")).encode("utf-8")
        self.send_response(status)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Content-Length", str(len(content)))
        self._security_headers()
        self.end_headers()
        self.wfile.write(content)

    def _security_headers(self) -> None:
        self.send_header(
            "Content-Security-Policy",
            "default-src 'self'; script-src 'self'; style-src 'self'; img-src 'self' data:; "
            "connect-src 'self'; object-src 'none'; frame-ancestors 'none'; base-uri 'none'; form-action 'self'",
        )
        self.send_header("X-Content-Type-Options", "nosniff")
        self.send_header("X-Frame-Options", "DENY")
        self.send_header("Referrer-Policy", "no-referrer")
        self.send_header("Cache-Control", "no-store")

    def log_message(self, format: str, *args: object) -> None:
        print(f"[web] {self.address_string()} {self.command} {urlparse(self.path).path}")


def run_server(
    service: DownloadService,
    *,
    host: str = "127.0.0.1",
    port: int = 8765,
    open_browser: bool = False,
) -> None:
    if host not in {"127.0.0.1", "::1"}:
        raise InvalidInputError("The Web console may bind only to 127.0.0.1 or ::1.")
    server = ConsoleServer((host, port), service)
    url = f"http://{host}:{server.server_port}/"
    print(f"WeChat Article Downloader console: {url}")
    print("Secrets cannot be entered or viewed in the Web console. Press Ctrl+C to stop.")
    if open_browser:
        webbrowser.open(url)
    try:
        server.serve_forever(poll_interval=0.5)
    except KeyboardInterrupt:
        pass
    finally:
        server.server_close()


def _optional(payload: dict[str, object], key: str) -> str | None:
    value = payload.get(key)
    if value in (None, ""):
        return None
    if not isinstance(value, str):
        raise InvalidInputError(f"{key} must be a string.")
    return value


def _optional_boolean(payload: dict[str, object], key: str) -> bool | None:
    value = payload.get(key)
    if value is None:
        return None
    if not isinstance(value, bool):
        raise InvalidInputError(f"{key} must be true or false.")
    return value


def _integer(value: object) -> int | None:
    if isinstance(value, bool):
        raise InvalidInputError("Numeric fields must be integers.")
    return int(value) if value not in (None, "") else None
