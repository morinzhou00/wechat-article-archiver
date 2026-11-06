"""Exercise real parsing, exporting and resume with only network responses replaced."""
import base64
import tempfile
import unittest
from pathlib import Path
from unittest.mock import Mock, patch

from bs4 import BeautifulSoup

from wechat_article_downloader.parser import parse_article_html
from wechat_article_downloader.models import HistoryItem
from wechat_article_downloader.service import DownloadService


class ArchiveFlowTests(unittest.TestCase):
    def test_export_move_and_repair_missing_image(self):
        url = "https://mp.weixin.qq.com/s?__biz=MzTestBiz==&mid=12345&idx=1&sn=abc"
        source = (Path(__file__).parent / "fixtures/article.html").read_text(encoding="utf-8")
        sample = parse_article_html(url, source)
        item = HistoryItem(url, sample.title, sample.published_at, biz="MzTestBiz==", mid="12345", idx="1")
        png = base64.b64decode("iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAQAAAC1HAwCAAAAC0lEQVR42mNk+A8AAQUBAScY42YAAAAASUVORK5CYII=")
        response = Mock(headers={"content-type": "image/png"})
        response.__enter__ = Mock(return_value=response)
        response.__exit__ = Mock(return_value=False)
        response.iter_content = Mock(side_effect=lambda *_: iter([png]))
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            output = root / "中文 图文"
            service = DownloadService(root / "profile")
            service.credentials = Mock()
            service.credentials.get.return_value = {"biz": "MzTestBiz=="}
            with (
                patch("wechat_article_downloader.service.WeChatHistoryProvider") as provider,
                patch("wechat_article_downloader.client.RemoteLimiter.wait"),
                patch("wechat_article_downloader.client.WeChatClient.fetch_article", side_effect=lambda *_: parse_article_html(url, source)),
                patch("wechat_article_downloader.client.WeChatClient._get_with_safe_redirects", return_value=response),
            ):
                provider.return_value.list_page.return_value = ([item], None, False)
                options = dict(since="2025-01-01", until="2026-12-31", formats="html,md,json", include_assets=True)
                first = service.download_account(url, output_dir=output, **options)
                self.assertTrue(first["ok"])
                moved = root / "搬到新目录"
                output.rename(moved)
                html = next(moved.rglob("article.html"))
                soup = BeautifulSoup(html.read_text(encoding="utf-8"), "html.parser")
                refs = [node["src"] for node in soup.select("img[src]")]
                self.assertEqual(len(refs), 1)
                image = html.parent / refs[0]
                self.assertTrue(image.is_file())
                self.assertIn(refs[0], html.with_suffix(".md").read_text(encoding="utf-8"))
                second = service.download_account(url, output_dir=moved, **options)
                self.assertEqual(second["resume"]["skipped_existing"], 1)
                image.unlink()
                third = service.download_account(url, output_dir=moved, **options)
                self.assertEqual(third["resume"]["downloaded_this_run"], 1)
                self.assertTrue(image.is_file())
