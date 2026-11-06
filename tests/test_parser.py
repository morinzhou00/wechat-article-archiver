from __future__ import annotations

import json
import unittest
from pathlib import Path

from wechat_article_downloader.exporter import render_offline_html
from wechat_article_downloader.parser import parse_article_html, parse_history_payload


FIXTURES = Path(__file__).with_name("fixtures")


class ParserTests(unittest.TestCase):
    def test_query_identifiers_override_runtime_biz_template(self) -> None:
        source = """
        <html><body>
          <h1 id="activity-name">测试</h1>
          <div id="js_content"><p>正文</p></div>
          <script>
            var biz = " + biz + ";
            var mid = " + mid + ";
            var idx = " + idx + ";
          </script>
        </body></html>
        """
        article = parse_article_html(
            "https://mp.weixin.qq.com/s?__biz=MzUrlBiz%3D%3D&mid=2247&idx=3&sn=abc",
            source,
        )
        self.assertEqual(article.ref.biz, "MzUrlBiz==")
        self.assertEqual(article.ref.mid, "2247")
        self.assertEqual(article.ref.idx, "3")
        self.assertEqual(article.ref.sn, "abc")

    def test_article_identity_content_and_runtime_visibility(self) -> None:
        source = (FIXTURES / "article.html").read_text(encoding="utf-8")
        article = parse_article_html("https://mp.weixin.qq.com/s/TestSlug", source)
        self.assertEqual(article.title, "测试文章")
        self.assertEqual(article.account_name, "测试公众号")
        self.assertEqual(article.author, "测试作者")
        self.assertEqual(article.ref.biz, "MzTestBiz==")
        self.assertIn("第一段正文", article.content_markdown)
        self.assertIn('src="https://mmbiz.qpic.cn/test.jpg"', article.content_html)
        offline = render_offline_html(article)
        self.assertNotIn("visibility: hidden", offline)
        self.assertNotIn("opacity: 0", offline)
        self.assertIn("color: rgb(1, 2, 3)", offline)
        self.assertNotIn("<iframe", offline)

    def test_history_main_and_multi_articles(self) -> None:
        payload = json.loads((FIXTURES / "history.json").read_text(encoding="utf-8"))
        items, next_offset, more = parse_history_payload(payload, biz="MzTestBiz==")
        self.assertEqual([item.title for item in items], ["主文章", "次文章"])
        self.assertEqual([item.idx for item in items], ["1", "2"])
        self.assertTrue(all(item.url.startswith("https://mp.weixin.qq.com/") for item in items))
        self.assertEqual(next_offset, 10)
        self.assertTrue(more)


if __name__ == "__main__":
    unittest.main()
