from __future__ import annotations

import unittest

from wechat_article_downloader.errors import RemoteError
from wechat_article_downloader.models import Article, ArticleAsset, ArticleRef
from wechat_article_downloader.redaction import redact_text, redact_value


class SecurityTests(unittest.TestCase):
    def test_recursive_redaction_covers_urls_and_nested_fields(self) -> None:
        value = {
            "message": (
                "failed https://mp.weixin.qq.com/mp/profile_ext?"
                "__biz=public&key=secret-key&pass_ticket=secret-ticket"
            ),
            "nested": [{"appmsg_token": "secret-token", "safe": "visible"}],
        }
        serialized = repr(redact_value(value))
        self.assertNotIn("secret-key", serialized)
        self.assertNotIn("secret-ticket", serialized)
        self.assertNotIn("secret-token", serialized)
        self.assertIn("visible", serialized)

    def test_error_and_article_metadata_do_not_leak_credentials(self) -> None:
        secret_url = "https://mp.weixin.qq.com/s/test?key=secret-key&pass_ticket=secret-ticket"
        error = RemoteError("request failed " + secret_url, details={"request_url": secret_url})
        article = Article(
            ref=ArticleRef(secret_url),
            title="test",
            account_name=None,
            author=None,
            published_at=None,
            digest=None,
            content_html="",
            content_markdown="",
            source_html="",
            assets=[
                ArticleAsset(
                    remote_url="https://mmbiz.qpic.cn/a?key=secret-key",
                    relative_path="assets/a.jpg",
                    kind="image",
                )
            ],
            extra={"pass_ticket": "secret-ticket"},
        )
        serialized = repr({"error": error.as_dict(), "article": article.metadata()})
        self.assertNotIn("secret-key", serialized)
        self.assertNotIn("secret-ticket", serialized)

    def test_redaction_preserves_safe_url_fields(self) -> None:
        text = redact_text("see https://mp.weixin.qq.com/s/test?scene=124&key=secret")
        self.assertIn("scene=124", text)
        self.assertNotIn("key=secret", text)


if __name__ == "__main__":
    unittest.main()
