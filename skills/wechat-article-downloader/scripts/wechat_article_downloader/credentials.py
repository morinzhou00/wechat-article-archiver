from __future__ import annotations

import getpass
import json
from dataclasses import dataclass
from pathlib import Path
from urllib.parse import parse_qs, urlparse

import keyring
from keyring.errors import KeyringError

from .errors import AuthRequiredError, InvalidInputError
from .utils import atomic_write_json, default_data_dir, now_iso, read_json


SERVICE_NAME = "wechat-article-downloader"
@dataclass(slots=True)
class CredentialSummary:
    alias: str
    created_at: str
    origin: str
    fields: list[str]

    def to_dict(self) -> dict[str, object]:
        return {
            "alias": self.alias,
            "created_at": self.created_at,
            "origin": self.origin,
            "fields": self.fields,
        }


class CredentialStore:
    def __init__(self, data_dir: Path | None = None) -> None:
        self.data_dir = data_dir or default_data_dir()
        self.metadata_path = self.data_dir / "credential-metadata.json"

    def import_request(
        self,
        alias: str,
        request_url: str,
        cookie_header: str = "",
        *,
        origin: str = "interactive",
    ) -> CredentialSummary:
        alias = _validate_alias(alias)
        parsed = urlparse(request_url.strip())
        if parsed.scheme != "https" or (parsed.hostname or "").lower() != "mp.weixin.qq.com":
            raise InvalidInputError("Authenticated request URL must use https://mp.weixin.qq.com.")
        query = parse_qs(parsed.query)
        secret = {key.lstrip("_"): values[0] for key, values in query.items() if values}
        if "__biz" in query:
            secret["biz"] = query["__biz"][0]
        cookies = parse_cookie_header(cookie_header)
        secret.update(cookies)
        secret["request_url"] = request_url.strip()
        secret["cookie"] = cookie_header.strip()
        return self.save_fields(alias, secret, origin=origin)

    def save_fields(
        self,
        alias: str,
        secret: dict[str, str],
        *,
        origin: str,
    ) -> CredentialSummary:
        alias = _validate_alias(alias)
        required_sets = [
            {"biz", "key", "uin", "pass_ticket"},
            {"biz", "appmsg_token", "pass_ticket"},
        ]
        if not any(fields.issubset(secret) for fields in required_sets):
            raise InvalidInputError(
                "The request is missing account-history credentials.",
                details={
                    "accepted_sets": [sorted(fields) for fields in required_sets],
                    "present_fields": sorted(key for key in secret if key not in {"cookie", "request_url"}),
                },
            )
        try:
            keyring.set_password(SERVICE_NAME, alias, json.dumps(secret, ensure_ascii=False))
        except KeyringError as exc:
            raise AuthRequiredError(
                "Windows Credential Manager is unavailable; credentials were not saved.",
                details={"action": "Run auth import again in a normal Windows desktop session."},
            ) from exc
        summary = CredentialSummary(
            alias=alias,
            created_at=now_iso(),
            origin=origin,
            fields=sorted(key for key in secret if key not in {"cookie", "request_url"}),
        )
        metadata = self._metadata()
        metadata[alias] = summary.to_dict()
        atomic_write_json(self.metadata_path, metadata)
        return summary

    def import_interactive(self, alias: str) -> CredentialSummary:
        print(
            "Paste an authenticated mp.weixin.qq.com/mp/profile_ext?action=getmsg request.\n"
            "The values are read locally and stored in Windows Credential Manager; they are not echoed."
        )
        request_url = getpass.getpass("Authenticated request URL: ").strip()
        cookie_header = getpass.getpass("Cookie header (optional if URL has all fields): ").strip()
        return self.import_request(alias, request_url, cookie_header)

    def get(self, alias: str) -> dict[str, str]:
        alias = _validate_alias(alias)
        try:
            raw = keyring.get_password(SERVICE_NAME, alias)
        except KeyringError as exc:
            raise AuthRequiredError("Windows Credential Manager could not be read.") from exc
        if not raw:
            raise AuthRequiredError(
                f"No credential named '{alias}' is stored.",
                details=auth_guidance(alias),
            )
        payload = json.loads(raw)
        if not isinstance(payload, dict):
            raise AuthRequiredError(f"Credential '{alias}' is invalid; import it again.")
        return {str(key): str(value) for key, value in payload.items() if value is not None}

    def summaries(self) -> list[CredentialSummary]:
        values: list[CredentialSummary] = []
        for alias, item in self._metadata().items():
            if isinstance(item, dict):
                values.append(
                    CredentialSummary(
                        alias=alias,
                        created_at=str(item.get("created_at", "")),
                        origin=str(item.get("origin", "")),
                        fields=sorted(str(field) for field in item.get("fields", [])),
                    )
                )
        return sorted(values, key=lambda item: item.alias)

    def delete(self, alias: str) -> bool:
        alias = _validate_alias(alias)
        try:
            existed = keyring.get_password(SERVICE_NAME, alias) is not None
            keyring.delete_password(SERVICE_NAME, alias)
        except keyring.errors.PasswordDeleteError:
            existed = False
        except KeyringError as exc:
            raise AuthRequiredError("Windows Credential Manager could not delete the credential.") from exc
        metadata = self._metadata()
        metadata.pop(alias, None)
        atomic_write_json(self.metadata_path, metadata)
        return existed

    def _metadata(self) -> dict[str, dict[str, object]]:
        raw = read_json(self.metadata_path, {}) or {}
        return raw if isinstance(raw, dict) else {}


def parse_cookie_header(value: str) -> dict[str, str]:
    cookies: dict[str, str] = {}
    for item in value.split(";"):
        if "=" not in item:
            continue
        key, content = item.split("=", 1)
        key = key.strip()
        if key:
            cookies[key] = content.strip()
    return cookies


def auth_guidance(alias: str = "default") -> dict[str, object]:
    return {
        "credential_alias": alias,
        "safe_handling": "Do not paste credentials into chat. Run the interactive command locally.",
        "steps": [
            f"Run: wechat-download.ps1 auth capture <sample-article-url> --alias {alias}",
            "Copy the generated account-home URL into WeChat's File Transfer Assistant and open it inside WeChat.",
            "The local scanner validates candidates against WeChat and stores only an accepted credential.",
            f"Verify without exposing values: wechat-download.ps1 auth status {alias}",
        ],
        "fallback": f"Run: wechat-download.ps1 auth import {alias} and use the hidden local prompts.",
    }


def _validate_alias(alias: str) -> str:
    normalized = alias.strip()
    if not normalized or len(normalized) > 64 or not all(char.isalnum() or char in "-_." for char in normalized):
        raise InvalidInputError("Credential alias must be 1-64 letters, digits, dots, underscores, or hyphens.")
    return normalized
