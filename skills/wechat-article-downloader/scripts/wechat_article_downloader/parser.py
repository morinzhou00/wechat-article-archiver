from __future__ import annotations

import html as html_module
import json
import re
from datetime import datetime
from urllib.parse import urljoin
from zoneinfo import ZoneInfo

from bs4 import BeautifulSoup
from markdownify import markdownify

from .errors import RemoteError
from .models import Article, ArticleRef, HistoryItem
from .utils import parse_url_fields


SHANGHAI = ZoneInfo("Asia/Shanghai")


def parse_article_html(url: str, source_html: str) -> Article:
    soup = BeautifulSoup(source_html, "html.parser")
    content = soup.select_one("#js_content") or soup.select_one(".rich_media_content")
    if content is None:
        raise RemoteError(
            "The response did not contain a WeChat article body.",
            details={"hint": "The article may be deleted, private, or blocked by a verification page."},
        )

    for node in content.select("script, style, noscript, iframe, object, embed, form, input, button, base"):
        node.decompose()
    _remove_runtime_hiding(content)
    for node in content.select("[data-src]"):
        source = node.get("data-src")
        if source and not node.get("src"):
            node["src"] = _absolute_url(source, url)
    for node in content.select("[src]"):
        node["src"] = _absolute_url(str(node.get("src")), url)

    runtime = extract_runtime_fields(source_html)
    url_fields = parse_url_fields(url)
    # Query-string identifiers are the canonical article address. Runtime strings
    # may contain JavaScript templates or decoys such as ``biz: " + biz + "``.
    fields = {key: value or runtime.get(key) for key, value in url_fields.items()}
    title = (
        _node_text(soup.select_one("#activity-name"))
        or _node_text(soup.select_one(".rich_media_title"))
        or _meta(soup, "og:title")
        or runtime.get("title")
        or "untitled"
    )
    account_name = (
        _node_text(soup.select_one("#js_name"))
        or _meta(soup, "author")
        or runtime.get("nickname")
    )
    author = runtime.get("author") or _node_text(soup.select_one(".rich_media_meta.rich_media_meta_text"))
    published_at = _published_at(soup, runtime)
    digest = _meta(soup, "description") or _meta(soup, "og:description") or runtime.get("digest")
    cover_url = _meta(soup, "og:image") or runtime.get("cover_url")
    content_html = str(content)
    content_markdown = markdownify(content_html, heading_style="ATX", bullets="-").strip()

    return Article(
        ref=ArticleRef(
            url=url,
            biz=fields.get("biz"),
            mid=fields.get("mid"),
            idx=fields.get("idx"),
            sn=fields.get("sn"),
        ),
        title=title.strip(),
        account_name=account_name.strip() if account_name else None,
        author=author.strip() if author else None,
        published_at=published_at,
        digest=digest.strip() if digest else None,
        content_html=content_html,
        content_markdown=content_markdown,
        source_html=source_html,
        cover_url=_absolute_url(cover_url, url) if cover_url else None,
        extra={
            key: value
            for key, value in runtime.items()
            if key not in {"biz", "mid", "idx", "sn", "title", "nickname", "author", "digest", "cover_url"}
        },
    )


def extract_runtime_fields(source_html: str) -> dict[str, str]:
    patterns: dict[str, tuple[str, ...]] = {
        "biz": (
            r'\b(?:biz|__biz)\s*[:=]\s*["\']([^"\']+)',
            r'["\']__biz["\']\s*:\s*["\']([^"\']+)',
        ),
        "mid": (
            r'\b(?:mid|appmsgid)\s*[:=]\s*["\']?(\d+)',
            r'["\']appmsgid["\']\s*:\s*["\']?(\d+)',
        ),
        "idx": (r'\bidx\s*[:=]\s*["\']?(\d+)',),
        "sn": (r'\bsn\s*[:=]\s*["\']([0-9a-fA-F]+)',),
        "title": (r'\bmsg_title\s*=\s*["\'](.+?)["\'];',),
        "nickname": (r'\bnickname\s*=\s*["\'](.+?)["\'];',),
        "author": (r'\bauthor\s*=\s*["\'](.+?)["\'];',),
        "digest": (r'\bmsg_desc\s*=\s*["\'](.+?)["\'];',),
        "cover_url": (r'\bmsg_cdn_url\s*=\s*["\'](.+?)["\'];',),
        "timestamp": (
            r'\b(?:ct|ori_create_time|create_time)\s*[:=]\s*["\']?(\d{10})',
            r'["\']create_time["\']\s*:\s*(\d{10})',
        ),
        "comment_id": (r'\bcomment_id\s*[:=]\s*["\']?(\d+)',),
    }
    result: dict[str, str] = {}
    for field, alternatives in patterns.items():
        for pattern in alternatives:
            match = re.search(pattern, source_html, flags=re.DOTALL)
            if match:
                result[field] = _decode_js_string(match.group(1))
                break
    return result


def parse_history_payload(payload: dict[str, object], *, biz: str | None = None) -> tuple[list[HistoryItem], int | None, bool]:
    raw = payload.get("general_msg_list") or payload.get("list")
    if isinstance(raw, str):
        try:
            raw = json.loads(raw)
        except json.JSONDecodeError as exc:
            raise RemoteError("WeChat returned an unreadable history list.") from exc
    if isinstance(raw, dict):
        entries = raw.get("list", [])
    elif isinstance(raw, list):
        entries = raw
    else:
        entries = []

    items: list[HistoryItem] = []
    seen: set[str] = set()
    for entry in entries if isinstance(entries, list) else []:
        if not isinstance(entry, dict):
            continue
        common = entry.get("comm_msg_info") if isinstance(entry.get("comm_msg_info"), dict) else {}
        timestamp = _integer(common.get("datetime")) or _integer(entry.get("create_time"))
        if not timestamp:
            continue
        primary = entry.get("app_msg_ext_info")
        candidates = [primary] if isinstance(primary, dict) else []
        if isinstance(primary, dict) and isinstance(primary.get("multi_app_msg_item_list"), list):
            candidates.extend(item for item in primary["multi_app_msg_item_list"] if isinstance(item, dict))
        for index, candidate in enumerate(candidates, start=1):
            url = _history_url(candidate.get("content_url"))
            if not url or url in seen:
                continue
            seen.add(url)
            fields = parse_url_fields(url)
            items.append(
                HistoryItem(
                    url=url,
                    title=str(candidate.get("title") or "untitled"),
                    published_at=datetime.fromtimestamp(timestamp, tz=SHANGHAI),
                    digest=_optional_text(candidate.get("digest")),
                    author=_optional_text(candidate.get("author")),
                    cover_url=_history_url(candidate.get("cover")),
                    biz=fields.get("biz") or biz,
                    mid=fields.get("mid") or _optional_text(common.get("id")),
                    idx=fields.get("idx") or str(index),
                    sn=fields.get("sn"),
                )
            )
    items.sort(key=lambda item: item.published_at, reverse=True)
    next_offset = _integer(payload.get("next_offset"))
    can_continue = bool(_integer(payload.get("can_msg_continue")))
    return items, next_offset, can_continue


def _published_at(soup: BeautifulSoup, runtime: dict[str, str]) -> datetime | None:
    timestamp = runtime.get("timestamp")
    if timestamp:
        return datetime.fromtimestamp(int(timestamp), tz=SHANGHAI)
    value = _meta(soup, "article:published_time") or _node_text(soup.select_one("#publish_time"))
    if not value:
        return None
    value = value.strip()
    for parser in (datetime.fromisoformat,):
        try:
            parsed = parser(value.replace("Z", "+00:00"))
            return parsed if parsed.tzinfo else parsed.replace(tzinfo=SHANGHAI)
        except ValueError:
            pass
    for format_string in ("%Y-%m-%d", "%Y年%m月%d日", "%Y/%m/%d"):
        try:
            return datetime.strptime(value[:10], format_string).replace(tzinfo=SHANGHAI)
        except ValueError:
            continue
    return None


def _node_text(node: object) -> str | None:
    if node is None:
        return None
    value = node.get_text(" ", strip=True)
    return value or None


def _remove_runtime_hiding(content: object) -> None:
    """Remove only WeChat's pre-JavaScript hiding rules from the saved article root."""
    style = str(content.get("style") or "")
    declarations: list[str] = []
    for declaration in style.split(";"):
        name, separator, value = declaration.partition(":")
        if not separator:
            continue
        if name.strip().casefold() == "visibility" and value.strip().casefold() == "hidden":
            continue
        if name.strip().casefold() == "opacity" and value.strip() == "0":
            continue
        declarations.append(f"{name.strip()}: {value.strip()}")
    if declarations:
        content["style"] = "; ".join(declarations)
    else:
        content.attrs.pop("style", None)


def _meta(soup: BeautifulSoup, name: str) -> str | None:
    node = soup.select_one(f"meta[name='{name}'],meta[property='{name}']")
    return str(node.get("content")).strip() if node and node.get("content") else None


def _decode_js_string(value: str) -> str:
    value = html_module.unescape(value)
    try:
        return json.loads(f'"{value.replace(chr(34), chr(92) + chr(34))}"')
    except (json.JSONDecodeError, UnicodeDecodeError):
        return value.replace("\\/", "/").replace("\\x26", "&")


def _absolute_url(value: str, base: str) -> str:
    value = html_module.unescape(value or "").strip()
    if value.startswith("//"):
        return "https:" + value
    return urljoin(base, value)


def _history_url(value: object) -> str | None:
    if not isinstance(value, str) or not value:
        return None
    result = html_module.unescape(value).replace("\\/", "/").strip()
    if result.startswith("//"):
        result = "https:" + result
    elif result.startswith("/"):
        result = "https://mp.weixin.qq.com" + result
    elif result.startswith("http://mp.weixin.qq.com"):
        result = "https://" + result[len("http://") :]
    return result


def _integer(value: object) -> int | None:
    try:
        return int(value) if value is not None else None
    except (TypeError, ValueError):
        return None


def _optional_text(value: object) -> str | None:
    return str(value) if value not in (None, "") else None
