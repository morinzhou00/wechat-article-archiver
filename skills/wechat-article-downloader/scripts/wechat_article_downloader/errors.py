from __future__ import annotations

from .redaction import redact_value


class WeChatDownloaderError(RuntimeError):
    """Base error with a stable machine-readable code."""

    code = "DOWNLOAD_ERROR"

    def __init__(self, message: str, *, details: dict[str, object] | None = None) -> None:
        super().__init__(message)
        self.details = details or {}

    def as_dict(self) -> dict[str, object]:
        return {
            "ok": False,
            "error": self.code,
            "message": redact_value(str(self)),
            "details": redact_value(self.details),
        }


class InvalidInputError(WeChatDownloaderError):
    code = "INVALID_INPUT"


class AuthRequiredError(WeChatDownloaderError):
    code = "AUTH_REQUIRED"


class RemoteError(WeChatDownloaderError):
    code = "REMOTE_ERROR"


class ExportError(WeChatDownloaderError):
    code = "EXPORT_ERROR"


class DependencyError(WeChatDownloaderError):
    code = "DEPENDENCY_MISSING"
