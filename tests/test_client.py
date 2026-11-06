from __future__ import annotations

import unittest
import tempfile
from pathlib import Path
from unittest.mock import Mock

from wechat_article_downloader.client import (
    WeChatClient,
    _authenticated_article_url,
    is_allowed_article_response_url,
    is_allowed_asset_url,
)
from wechat_article_downloader.errors import RemoteError
from wechat_article_downloader.models import Article, ArticleRef


class ClientTests(unittest.TestCase):
    def test_missing_image_is_not_silently_successful(self):
        article = Article(
            ArticleRef("https://mp.weixin.qq.com/s/test"), "test", None, None, None, None,
            '<img src="https://mmbiz.qpic.cn/a.png">', "", "",
        )
        client = WeChatClient(interval_seconds=1)
        client._download_asset = Mock(return_value=None)
        with tempfile.TemporaryDirectory() as directory, self.assertRaises(RemoteError):
            client.download_assets(article, Path(directory))

    def test_authenticated_article_url_adds_short_lived_fields(self) -> None:
        value = _authenticated_article_url(
            "https://mp.weixin.qq.com/s?__biz=MzTest==&mid=1&idx=1&sn=abc",
            {
                "poc_token": "short-lived",
                "appmsg_token": "legacy-token",
                "pass_ticket": "ticket",
                "key": "not-added-to-url",
            },
        )
        self.assertIn("poc_token=short-lived", value)
        self.assertIn("appmsg_token=legacy-token", value)
        self.assertIn("pass_ticket=ticket", value)
        self.assertNotIn("key=not-added-to-url", value)

    def test_asset_allowlist_blocks_ssrf_and_third_parties(self) -> None:
        self.assertTrue(is_allowed_asset_url("https://mmbiz.qpic.cn/image.jpg"))
        self.assertTrue(is_allowed_asset_url("https://res.wx.qq.com/icon.png"))
        self.assertFalse(is_allowed_asset_url("https://mmbiz.qpic.cn:444/image.jpg"))
        self.assertFalse(is_allowed_asset_url("http://mmbiz.qpic.cn/image.jpg"))
        self.assertFalse(is_allowed_asset_url("https://127.0.0.1/private"))
        self.assertFalse(is_allowed_asset_url("https://qpic.cn.attacker.example/image.jpg"))

    def test_sanitizer_removes_active_and_untrusted_media_urls(self) -> None:
        article = Article(
            ref=ArticleRef("https://mp.weixin.qq.com/s/test"),
            title="test",
            account_name=None,
            author=None,
            published_at=None,
            digest=None,
            content_html=(
                '<div><img src="https://127.0.0.1/a" srcset="https://example.com/a 2x">'
                '<img src="https://mmbiz.qpic.cn/good.jpg">'
                '<img src="file:///C:/private.txt" onerror="alert(1)">'
                '<iframe src="https://example.com/frame"></iframe>'
                '<p style="background:url(https://example.com/t)" onclick="alert(1)">text</p></div>'
            ),
            content_markdown="",
            source_html="",
        )
        WeChatClient(interval_seconds=1).sanitize_media_urls(article)
        self.assertNotIn("127.0.0.1", article.content_html)
        self.assertNotIn("srcset", article.content_html)
        self.assertNotIn("example.com", article.content_html)
        self.assertIn("mmbiz.qpic.cn/good.jpg", article.content_html)
        self.assertNotIn("example.com", article.content_markdown)
        self.assertNotIn("file:", article.content_html)
        self.assertNotIn("onerror", article.content_html)
        self.assertNotIn("onclick", article.content_html)
        self.assertNotIn("<iframe", article.content_html)

    def test_redirect_is_checked_before_following(self) -> None:
        first = Mock(status_code=302, headers={"Location": "https://127.0.0.1/private"})
        client = WeChatClient(interval_seconds=1)
        client.session.get = Mock(return_value=first)
        with self.assertRaises(RemoteError):
            client._get_with_safe_redirects(
                "https://mp.weixin.qq.com/s/test",
                is_allowed_article_response_url,
            )
        self.assertEqual(client.session.get.call_count, 1)

    def test_no_assets_removes_remote_media_from_both_exports(self) -> None:
        article = Article(
            ref=ArticleRef("https://mp.weixin.qq.com/s/test"),
            title="test",
            account_name=None,
            author=None,
            published_at=None,
            digest=None,
            content_html=(
                '<p>before</p><img src="https://mmbiz.qpic.cn/good.jpg" '
                'data-src="https://mmbiz.qpic.cn/lazy.jpg">'
                '<video poster="https://mmbiz.qpic.cn/poster.jpg"></video>'
            ),
            content_markdown="remote",
            source_html="",
        )
        WeChatClient(interval_seconds=1).remove_remote_media(article)
        self.assertNotIn("https://", article.content_html)
        self.assertNotIn("https://", article.content_markdown)
        self.assertNotIn("data-src", article.content_html)


if __name__ == "__main__":
    unittest.main()
