from __future__ import annotations

import re
from typing import Any
from urllib.parse import parse_qsl, urlencode, urlsplit, urlunsplit


SECRET_FIELDS = {
    "key",
    "uin",
    "pass_ticket",
    "appmsg_token",
    "poc_token",
    "poc_sid",
    "wap_sid2",
    "wxuin",
    "wxtoken",
    "wxtokenkey",
    "rewardsn",
    "cookie",
    "authorization",
    "request_url",
}
URL_PATTERN = re.compile(r"https?://[^\s\"'<>]+", flags=re.IGNORECASE)


def is_secret_field(name: object) -> bool:
    normalized = str(name).lstrip("_").casefold()
    return normalized in SECRET_FIELDS or normalized.endswith(("_token", "_ticket"))


def redact_url(value: str, *, remove: bool = False) -> str:
    try:
        parsed = urlsplit(value)
    except ValueError:
        return value
    if parsed.scheme not in {"http", "https"}:
        return value
    query = []
    for key, content in parse_qsl(parsed.query, keep_blank_values=True):
        if is_secret_field(key):
            if not remove:
                query.append((key, "[REDACTED]"))
        else:
            query.append((key, content))
    return urlunsplit((parsed.scheme, parsed.netloc, parsed.path, urlencode(query, doseq=True), parsed.fragment))


def redact_text(value: str) -> str:
    return URL_PATTERN.sub(lambda match: redact_url(match.group()), value)


def redact_value(value: Any, *, field: object | None = None) -> Any:
    if field is not None and is_secret_field(field):
        return "[REDACTED]"
    if isinstance(value, dict):
        return {str(key): redact_value(content, field=key) for key, content in value.items()}
    if isinstance(value, (list, tuple)):
        return [redact_value(item) for item in value]
    if isinstance(value, str):
        return redact_text(value)
    return value
