from __future__ import annotations

import hashlib
import html
import mimetypes
import re
import threading
import time
from pathlib import Path
from typing import Callable
from urllib.parse import parse_qs, urlencode, urljoin, urlparse, urlsplit, urlunsplit

import requests
from bs4 import BeautifulSoup
from markdownify import markdownify
from requests.adapters import HTTPAdapter
from urllib3.util.retry import Retry

from .errors import RemoteError
from .models import Article, ArticleAsset
from .parser import parse_article_html
from .redaction import redact_url
from .utils import safe_filename, validate_article_url


USER_AGENT = (
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
    "AppleWebKit/537.36 (KHTML, like Gecko) Chrome/134.0.0.0 Safari/537.36"
)
ASSET_HOST_SUFFIXES = (
    ".qpic.cn",
    ".qlogo.cn",
    ".wx.qq.com",
    ".video.qq.com",
)
ASSET_HOSTS = {"mp.weixin.qq.com"}
LAZY_MEDIA_ATTRIBUTES = ("data-src", "data-original", "data-poster", "data-background", "data-bg")


class RemoteLimiter:
    _lock = threading.Lock()
    _last_request = 0.0

    def __init__(self, interval_seconds: float) -> None:
        self.interval_seconds = interval_seconds

    def wait(self) -> None:
        with self._lock:
            remaining = self.interval_seconds - (time.monotonic() - self._last_request)
            if remaining > 0:
                time.sleep(remaining)
            type(self)._last_request = time.monotonic()


class WeChatClient:
    def __init__(
        self,
        *,
        timeout: int = 30,
        interval_seconds: float = 3.0,
        credential: dict[str, str] | None = None,
    ) -> None:
        self.timeout = timeout
        self.limiter = RemoteLimiter(interval_seconds)
        self.credential = dict(credential or {})
        self.session = requests.Session()
        self.session.headers.update({"User-Agent": USER_AGENT, "Accept-Language": "zh-CN,zh;q=0.9,en;q=0.7"})
        self.session.cookies.update(_cookies_from_credentials(self.credential))
        retry = Retry(
            total=3,
            connect=3,
            read=2,
            backoff_factor=1.0,
            status_forcelist=(429, 500, 502, 503, 504),
            allowed_methods=frozenset({"GET"}),
        )
        self.session.mount("https://", HTTPAdapter(max_retries=retry))

    def fetch_article(self, url: str, *, attempts: int = 3) -> Article:
        url = validate_article_url(url)
        request_url = _authenticated_article_url(url, self.credential)
        if not 1 <= attempts <= 5:
            raise ValueError("attempts must be between 1 and 5")
        last_error: RemoteError | None = None
        for attempt in range(1, attempts + 1):
            self.limiter.wait()
            try:
                response = self._get_with_safe_redirects(
                    request_url,
                    is_allowed_article_response_url,
                    headers=_article_headers(self.credential),
                )
                response.raise_for_status()
                if len(response.content) > 25 * 1024 * 1024:
                    raise RemoteError("The article response exceeded the 25 MiB safety limit.")
                source_html = response.content.decode(response.encoding or "utf-8", errors="replace")
                article = parse_article_html(response.url, source_html)
                article.ref.url = redact_url(article.ref.url, remove=True)
                return article
            except requests.RequestException as exc:
                last_error = RemoteError(
                    "Failed to fetch the WeChat article.",
                    details={"url": redact_url(url), "attempt": attempt},
                )
                last_error.__cause__ = exc
            except RemoteError as exc:
                last_error = exc
            if attempt < attempts:
                time.sleep(5.0 * attempt)
        assert last_error is not None
        raise last_error

    def download_assets(
        self,
        article: Article,
        article_dir: Path,
        *,
        max_asset_bytes: int = 50 * 1024 * 1024,
        max_assets: int = 200,
        max_total_bytes: int = 500 * 1024 * 1024,
    ) -> None:
        assets_dir = article_dir / "assets"
        assets_dir.mkdir(parents=True, exist_ok=True)
        soup = BeautifulSoup(article.content_html, "html.parser")
        candidates: list[tuple[object, str, str]] = []
        for node in soup.select("img[src],video[src],video[poster],audio[src],source[src]"):
            if node.get("src"):
                candidates.append((node, "src", str(node.get("src"))))
            if node.name == "video" and node.get("poster"):
                candidates.append((node, "poster", str(node.get("poster"))))

        downloaded: dict[str, ArticleAsset] = {}
        total_bytes = 0
        for index, (node, attribute, remote_url) in enumerate(candidates, start=1):
            if remote_url in downloaded:
                node[attribute] = downloaded[remote_url].relative_path
                continue
            if len(downloaded) >= max_assets or total_bytes >= max_total_bytes:
                node.attrs.pop(attribute, None)
                continue
            remaining = max_total_bytes - total_bytes
            asset = self._download_asset(remote_url, assets_dir, index, min(max_asset_bytes, remaining))
            if asset is None:
                node.attrs.pop(attribute, None)
                continue
            downloaded[remote_url] = asset
            total_bytes += asset.size
            article.assets.append(asset)
            node[attribute] = asset.relative_path
            if attribute == "src":
                node.attrs.pop("data-src", None)
        _remove_lazy_media_attributes(soup)
        article.content_html = str(soup)
        article.content_markdown = markdownify(article.content_html, heading_style="ATX", bullets="-").strip()

    def remove_remote_media(self, article: Article) -> None:
        soup = BeautifulSoup(article.content_html, "html.parser")
        for node in soup.select("[src],video[poster]"):
            for attribute in ("src", "poster"):
                value = str(node.get(attribute) or "").strip()
                if value.startswith(("http://", "https://")):
                    node.attrs.pop(attribute, None)
        _remove_lazy_media_attributes(soup)
        article.content_html = str(soup)
        article.content_markdown = markdownify(article.content_html, heading_style="ATX", bullets="-").strip()

    def sanitize_media_urls(self, article: Article) -> None:
        """Prevent the offline renderer from following arbitrary article-controlled URLs."""
        soup = BeautifulSoup(article.content_html, "html.parser")
        for node in soup.select("script,iframe,object,embed,form,input,button,base,foreignObject"):
            node.decompose()
        for node in soup.select("*"):
            for attribute in list(node.attrs):
                if str(attribute).casefold().startswith("on"):
                    node.attrs.pop(attribute, None)
        for node in soup.select("[srcset]"):
            node.attrs.pop("srcset", None)
        _remove_lazy_media_attributes(soup)
        for node in soup.select("[src],video[poster]"):
            for attribute in ("src", "poster"):
                value = str(node.get(attribute) or "").strip()
                if value and not is_allowed_asset_url(value) and not _safe_data_image(value):
                    node.attrs.pop(attribute, None)
        for node in soup.select("[style]"):
            declarations = [
                declaration
                for declaration in str(node.get("style") or "").split(";")
                if "url(" not in declaration.casefold()
            ]
            if declarations:
                node["style"] = ";".join(declarations)
            else:
                node.attrs.pop("style", None)
        for node in soup.select("image[href],image[xlink\\:href],use[href],use[xlink\\:href]"):
            for attribute in ("href", "xlink:href"):
                value = str(node.get(attribute) or "").strip()
                if value and not value.startswith("#"):
                    node.attrs.pop(attribute, None)
        for node in soup.select("a[href]"):
            value = str(node.get("href") or "").strip()
            if value and not (value.startswith("#") or _safe_external_link(value)):
                node.attrs.pop("href", None)
        article.content_html = str(soup)
        article.content_markdown = markdownify(article.content_html, heading_style="ATX", bullets="-").strip()

    def _download_asset(
        self,
        remote_url: str,
        assets_dir: Path,
        index: int,
        max_asset_bytes: int,
    ) -> ArticleAsset | None:
        if not is_allowed_asset_url(remote_url):
            return None
        self.limiter.wait()
        try:
            with self._get_with_safe_redirects(remote_url, is_allowed_asset_url, stream=True) as response:
                response.raise_for_status()
                length = int(response.headers.get("content-length") or 0)
                if length > max_asset_bytes:
                    return None
                content_type = response.headers.get("content-type", "").split(";", 1)[0].strip() or None
                kind = _kind(content_type, remote_url)
                suffix = _suffix(content_type, remote_url)
                stem = safe_filename(Path(urlparse(remote_url).path).stem, fallback=kind, limit=40)
                digest = hashlib.sha256(remote_url.encode("utf-8")).hexdigest()[:8]
                filename = f"{index:03d}_{stem}_{digest}{suffix}"
                target = assets_dir / filename
                size = 0
                with target.open("wb") as handle:
                    for chunk in response.iter_content(64 * 1024):
                        size += len(chunk)
                        if size > max_asset_bytes:
                            handle.close()
                            target.unlink(missing_ok=True)
                            return None
                        handle.write(chunk)
        except (requests.RequestException, RemoteError):
            return None
        return ArticleAsset(
            remote_url=remote_url,
            relative_path=f"assets/{filename}",
            kind=kind,
            content_type=content_type,
            size=size,
        )

    def _get_with_safe_redirects(
        self,
        url: str,
        allowed_url: Callable[[str], bool],
        *,
        stream: bool = False,
        max_redirects: int = 5,
        headers: dict[str, str] | None = None,
    ) -> requests.Response:
        current = url
        for _ in range(max_redirects + 1):
            if not allowed_url(current):
                raise RemoteError("A remote redirect left the allowed WeChat hosts.")
            response = self.session.get(
                current,
                headers=headers,
                timeout=self.timeout,
                stream=stream,
                allow_redirects=False,
            )
            if response.status_code not in {301, 302, 303, 307, 308}:
                return response
            location = response.headers.get("Location")
            response.close()
            if not location:
                raise RemoteError("A WeChat redirect did not include a destination.")
            current = urljoin(current, location)
        raise RemoteError("A WeChat request exceeded the redirect limit.")


def _kind(content_type: str | None, url: str) -> str:
    marker = (content_type or "") + " " + url.lower()
    if "video" in marker or ".mp4" in marker:
        return "video"
    if "audio" in marker or ".mp3" in marker or ".m4a" in marker:
        return "audio"
    return "image"


def is_allowed_asset_url(url: str) -> bool:
    try:
        parsed = urlparse(url)
        port = parsed.port
    except ValueError:
        return False
    host = (parsed.hostname or "").casefold()
    return parsed.scheme == "https" and port in (None, 443) and (
        host in ASSET_HOSTS or any(host.endswith(suffix) for suffix in ASSET_HOST_SUFFIXES)
    )


def is_allowed_article_response_url(url: str) -> bool:
    try:
        parsed = urlparse(url)
        port = parsed.port
    except ValueError:
        return False
    return parsed.scheme == "https" and port in (None, 443) and (parsed.hostname or "").casefold() in {
        "mp.weixin.qq.com",
        "weixin.qq.com",
    }


def _safe_data_image(value: str) -> bool:
    return bool(re.match(r"^data:image/(?:png|jpeg|gif|webp);base64,", value, flags=re.IGNORECASE))


def _safe_external_link(value: str) -> bool:
    parsed = urlparse(value)
    return parsed.scheme == "https" and bool(parsed.hostname)


def _remove_lazy_media_attributes(soup: BeautifulSoup) -> None:
    for attribute in LAZY_MEDIA_ATTRIBUTES:
        for node in soup.select(f"[{attribute}]"):
            node.attrs.pop(attribute, None)


def _suffix(content_type: str | None, url: str) -> str:
    suffix = Path(urlparse(url).path).suffix.lower()
    if suffix and len(suffix) <= 6:
        return suffix
    guessed = mimetypes.guess_extension(content_type or "")
    if guessed == ".jpe":
        return ".jpg"
    return guessed or ".bin"


def _authenticated_article_url(url: str, credential: dict[str, str]) -> str:
    """Attach only the short-lived query fields needed by WeChat's article page."""
    if not credential:
        return url
    parsed = urlsplit(url)
    query = parse_qs(parsed.query, keep_blank_values=True)
    for key in ("poc_token", "appmsg_token", "pass_ticket"):
        if credential.get(key) and key not in query:
            query[key] = [credential[key]]
    return urlunsplit(
        (
            parsed.scheme,
            parsed.netloc,
            parsed.path,
            urlencode(query, doseq=True),
            parsed.fragment,
        )
    )


def _article_headers(credential: dict[str, str]) -> dict[str, str] | None:
    biz = credential.get("biz")
    if not biz:
        return None
    return {
        "Referer": (
            "https://mp.weixin.qq.com/mp/profile_ext?"
            + urlencode({"action": "home", "__biz": biz, "scene": "124"})
            + "#wechat_redirect"
        )
    }


def _cookies_from_credentials(credential: dict[str, str]) -> dict[str, str]:
    cookies: dict[str, str] = {}
    raw = credential.get("cookie", "")
    for item in raw.split(";"):
        if "=" in item:
            key, value = item.split("=", 1)
            cookies[key.strip()] = html.unescape(value.strip())
    for key in ("pass_ticket", "wap_sid2", "wxuin", "wxtokenkey", "rewardsn", "poc_sid"):
        if credential.get(key):
            cookies[key] = credential[key]
    return cookies
