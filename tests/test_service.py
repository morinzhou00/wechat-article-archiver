from __future__ import annotations

import tempfile
import unittest
from datetime import datetime
from pathlib import Path
from unittest.mock import Mock
from zoneinfo import ZoneInfo

from wechat_article_downloader.errors import InvalidInputError
from wechat_article_downloader.models import HistoryItem
from wechat_article_downloader.service import DownloadService, _biz_from_sample_url, _scan_output


SHANGHAI = ZoneInfo("Asia/Shanghai")


class FakeProvider:
    def list_page(self, *_args, **_kwargs):
        return (
            [
                HistoryItem("https://mp.weixin.qq.com/s/a", "A", datetime(2026, 7, 16, 12, tzinfo=SHANGHAI)),
                HistoryItem("https://mp.weixin.qq.com/s/b", "B", datetime(2026, 7, 15, 12, tzinfo=SHANGHAI)),
            ],
            None,
            False,
        )


class EmptyThenArticleProvider:
    def __init__(self) -> None:
        self.calls = 0

    def list_page(self, *_args, **_kwargs):
        self.calls += 1
        if self.calls == 1:
            return [], 10, True
        return (
            [HistoryItem("https://mp.weixin.qq.com/s/a", "A", datetime(2026, 7, 16, 12, tzinfo=SHANGHAI))],
            None,
            False,
        )


class ContinuingProvider:
    def list_page(self, *_args, **_kwargs):
        return (
            [HistoryItem("https://mp.weixin.qq.com/s/a", "A", datetime(2026, 7, 16, 12, tzinfo=SHANGHAI))],
            10,
            True,
        )


class ServiceTests(unittest.TestCase):
    def test_short_url_resolves_target_instead_of_reusing_previous_account(self):
        client = Mock()
        client.fetch_article.return_value.ref.biz = "new-account"
        self.assertEqual(
            _biz_from_sample_url("https://mp.weixin.qq.com/s/short", client, {"biz": "old-account"}),
            "new-account",
        )

    def test_biz_is_taken_from_article_url_without_fetching_captcha_page(self) -> None:
        client = Mock()
        client.fetch_article.side_effect = AssertionError("network fetch should not be needed")
        biz = _biz_from_sample_url(
            "https://mp.weixin.qq.com/s?__biz=MzTest%3D%3D&mid=1&idx=1&sn=abc",
            client,
            {},
        )
        self.assertEqual(biz, "MzTest==")
        client.fetch_article.assert_not_called()

    def test_discovery_checkpoint_resumes_at_next_offset(self) -> None:
        class PagedProvider:
            def __init__(self) -> None:
                self.offsets: list[int] = []

            def list_page(self, _biz, _credential, *, offset, **_kwargs):
                self.offsets.append(offset)
                return (
                    [
                        HistoryItem(
                            f"https://mp.weixin.qq.com/s?__biz=MzTest==&mid={offset}&idx=1&sn=abc",
                            f"第 {offset} 页",
                            datetime(2026, 10, 23, 15, tzinfo=SHANGHAI),
                            biz="MzTest==",
                            mid=str(offset),
                            idx="1",
                        )
                    ],
                    offset + 10,
                    True,
                )

        with tempfile.TemporaryDirectory() as directory:
            service = DownloadService(Path(directory))
            provider = PagedProvider()
            checkpoints = []
            first = service._discover(
                provider,
                "MzTest==",
                {},
                sample_url="https://mp.weixin.qq.com/s/test",
                latest=None,
                start_date=None,
                end_date=None,
                max_pages=1,
                on_checkpoint=checkpoints.append,
            )
            second = service._discover(
                provider,
                "MzTest==",
                {},
                sample_url="https://mp.weixin.qq.com/s/test",
                latest=None,
                start_date=None,
                end_date=None,
                max_pages=1,
                start_offset=first.next_offset or 0,
                initial_items=first.items,
                pages_scanned=first.pages_scanned,
            )
        self.assertFalse(first.complete)
        self.assertEqual(first.next_offset, 10)
        self.assertEqual(checkpoints[-1].next_offset, 10)
        self.assertEqual(provider.offsets, [0, 10])
        self.assertEqual(len(second.items), 2)

    def test_discovery_exact_inclusive_date(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            service = DownloadService(Path(directory))
            items = service._discover(
                FakeProvider(),
                "biz",
                {},
                sample_url="https://mp.weixin.qq.com/s/sample",
                latest=None,
                start_date=datetime(2026, 7, 16).date(),
                end_date=datetime(2026, 7, 16).date(),
                max_pages=1,
            )
        self.assertEqual([item.title for item in items], ["A"])

    def test_requires_selection(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            service = DownloadService(Path(directory))
            with self.assertRaises(InvalidInputError):
                service.download_account("https://mp.weixin.qq.com/s/sample")

    def test_latest_conflicts_with_exact_or_since(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            service = DownloadService(Path(directory))
            with self.assertRaises(InvalidInputError):
                service.download_account(
                    "https://mp.weixin.qq.com/s/sample",
                    latest=3,
                    on_date="2026-07-16",
                )

    def test_boolean_is_not_accepted_as_numeric_or_asset_flag(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            service = DownloadService(Path(directory))
            with self.assertRaises(InvalidInputError):
                service.download_account("https://mp.weixin.qq.com/s/sample", latest=True)
            with self.assertRaises(InvalidInputError):
                service.download_article("https://mp.weixin.qq.com/s/sample", include_assets="false")

    def test_discovery_skips_empty_nonterminal_page(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            service = DownloadService(Path(directory))
            provider = EmptyThenArticleProvider()
            items = service._discover(
                provider,
                "biz",
                {},
                sample_url="https://mp.weixin.qq.com/s/sample",
                latest=1,
                start_date=None,
                end_date=None,
                max_pages=2,
            )
        self.assertEqual([item.title for item in items], ["A"])
        self.assertEqual(provider.calls, 2)

    def test_discovery_marks_page_limit_as_incomplete(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            service = DownloadService(Path(directory))
            result = service._discover(
                ContinuingProvider(),
                "biz",
                {},
                sample_url="https://mp.weixin.qq.com/s/sample",
                latest=None,
                start_date=None,
                end_date=None,
                max_pages=1,
            )
        self.assertFalse(result.complete)
        self.assertEqual(result.stop_reason, "max_pages")

    def test_output_scan_is_bounded(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            (root / "a").mkdir()
            (root / "a" / "manifest.json").write_text("{}", encoding="utf-8")
            (root / "extra.txt").write_text("x", encoding="utf-8")
            result = _scan_output(root, max_entries=1, max_directories=10, max_seconds=1)
        self.assertTrue(result["truncated"])
        self.assertIn("entry_budget", result["truncation_reasons"])


if __name__ == "__main__":
    unittest.main()
