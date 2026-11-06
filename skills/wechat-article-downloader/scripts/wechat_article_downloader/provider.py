from __future__ import annotations

import html
import re
from urllib.parse import parse_qs, urlparse

import requests

from .client import USER_AGENT, RemoteLimiter
from .errors import AuthRequiredError, RemoteError
from .models import HistoryItem
from .parser import parse_history_payload


PROFILE_ENDPOINT = "https://mp.weixin.qq.com/mp/profile_ext"
AUTH_RET_CODES = {-3, -6, -8, -13}


class WeChatHistoryProvider:
    def __init__(self, *, timeout: int = 30, interval_seconds: float = 3.0) -> None:
        self.timeout = timeout
        self.limiter = RemoteLimiter(interval_seconds)
        self.session = requests.Session()
        self.session.headers.update({"User-Agent": USER_AGENT, "Accept": "application/json,text/plain,*/*"})

    def list_page(
        self,
        biz: str,
        credentials: dict[str, str],
        *,
        offset: int = 0,
        count: int = 10,
        referer: str | None = None,
    ) -> tuple[list[HistoryItem], int | None, bool]:
        self._refresh_poc_if_needed(biz, credentials)
        params = self._params(biz, credentials, offset, count)
        cookies = _cookies(credentials)
        headers = {
            "Referer": referer
            or f"https://mp.weixin.qq.com/mp/profile_ext?action=home&__biz={biz}&scene=124#wechat_redirect"
        }
        self.limiter.wait()
        try:
            response = self.session.get(
                PROFILE_ENDPOINT,
                params=params,
                headers=headers,
                cookies=cookies,
                timeout=self.timeout,
                allow_redirects=False,
            )
            response.raise_for_status()
        except requests.RequestException as exc:
            raise RemoteError("Failed to query WeChat account history.") from exc
        try:
            payload = response.json()
        except requests.JSONDecodeError as exc:
            raise AuthRequiredError(
                "WeChat did not return account history; the credential may be expired.",
                details={"action": "Open the account in WeChat again and re-import a fresh request."},
            ) from exc
        if not isinstance(payload, dict):
            raise RemoteError("WeChat returned an unexpected history response.")
        base_response = payload.get("base_resp") if isinstance(payload.get("base_resp"), dict) else {}
        ret = payload.get("ret", base_response.get("ret"))
        if ret not in (None, 0, "0"):
            try:
                numeric_ret = int(ret)
            except (TypeError, ValueError):
                numeric_ret = None
            error_type = AuthRequiredError if numeric_ret in AUTH_RET_CODES else RemoteError
            raise error_type(
                f"WeChat rejected the history request (ret={ret}).",
                details={
                    "errmsg": str(payload.get("errmsg", "")),
                    "action": (
                        "Import a fresh account-history request."
                        if error_type is AuthRequiredError
                        else "Inspect the provider response shape and retry later."
                    ),
                },
            )
        if "general_msg_list" not in payload and "list" not in payload:
            raise RemoteError(
                "WeChat returned JSON without a recognizable account-history list.",
                details={"response_fields": sorted(str(key) for key in payload)[:30]},
            )
        return parse_history_payload(payload, biz=biz)

    def _refresh_poc_if_needed(self, biz: str, credentials: dict[str, str]) -> None:
        if credentials.get("poc_token") or not (
            credentials.get("uin") and credentials.get("key") and credentials.get("pass_ticket")
        ):
            return
        params = {
            "action": "home",
            "__biz": biz,
            "scene": "124",
            "uin": credentials["uin"],
            "key": credentials["key"],
            "pass_ticket": credentials["pass_ticket"],
        }
        cookies = _cookies(credentials)
        cookies.setdefault("wxtokenkey", "777")
        self.limiter.wait()
        try:
            response = self.session.get(
                PROFILE_ENDPOINT,
                params=params,
                cookies=cookies,
                timeout=self.timeout,
                allow_redirects=False,
            )
            response.raise_for_status()
        except requests.RequestException:
            return
        poc_sid = response.cookies.get("poc_sid")
        token_match = re.search(r"""poc_token\s*:\s*["']([^"']+)""", response.text)
        if poc_sid:
            credentials["poc_sid"] = poc_sid
        if token_match:
            credentials["poc_token"] = token_match.group(1)

    @staticmethod
    def _params(biz: str, credentials: dict[str, str], offset: int, count: int) -> dict[str, str]:
        params: dict[str, str] = {}
        request_url = credentials.get("request_url")
        if request_url:
            params.update({key: values[0] for key, values in parse_qs(urlparse(request_url).query).items() if values})
        params.update(
            {
                "action": "getmsg",
                "__biz": biz,
                "offset": str(offset),
                "count": str(min(max(count, 1), 20)),
                "f": "json",
                "is_ok": "1",
                "scene": params.get("scene") or credentials.get("scene", "124"),
                "x5": params.get("x5", "0"),
            }
        )
        for field in ("uin", "key", "pass_ticket", "appmsg_token", "wxtoken", "poc_token"):
            if credentials.get(field):
                params[field] = credentials[field]
        if not (params.get("key") and params.get("uin")) and not (
            params.get("pass_ticket") and params.get("appmsg_token")
        ):
            raise AuthRequiredError(
                "The stored credential lacks the fields required for account history.",
                details={"present_fields": sorted(key for key in credentials if key not in {"cookie", "request_url"})},
            )
        return params


def _cookies(credentials: dict[str, str]) -> dict[str, str]:
    cookies: dict[str, str] = {}
    raw = credentials.get("cookie", "")
    for item in raw.split(";"):
        if "=" in item:
            key, value = item.split("=", 1)
            cookies[key.strip()] = html.unescape(value.strip())
    for key in ("pass_ticket", "wap_sid2", "wxuin", "wxtokenkey", "rewardsn", "poc_sid"):
        if credentials.get(key):
            cookies[key] = credentials[key]
    return cookies
