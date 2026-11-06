from __future__ import annotations

import tempfile
import unittest
from datetime import date, datetime
from pathlib import Path
from zoneinfo import ZoneInfo

from wechat_article_downloader.models import DiscoveryResult, HistoryItem
from wechat_article_downloader.resume import (
    checkpoint_path,
    item_key,
    load_checkpoint,
    make_fingerprint,
    save_checkpoint,
)


SHANGHAI = ZoneInfo("Asia/Shanghai")


class ResumeTests(unittest.TestCase):
    def test_checkpoint_round_trips_public_history_and_download_state(self) -> None:
        fingerprint = make_fingerprint(
            "MzTest==",
            latest=None,
            start_date=date(2024, 1, 1),
            end_date=date(2026, 10, 23),
            max_pages=200,
        )
        item = HistoryItem(
            url="https://mp.weixin.qq.com/s?__biz=MzTest==&mid=1&idx=1&sn=abc",
            title="测试",
            published_at=datetime(2026, 10, 23, 15, tzinfo=SHANGHAI),
            biz="MzTest==",
            mid="1",
            idx="1",
            sn="abc",
        )
        discovered = DiscoveryResult(
            items=[item],
            complete=False,
            pages_scanned=8,
            stop_reason="max_pages",
            next_offset=80,
        )
        with tempfile.TemporaryDirectory() as directory:
            path = checkpoint_path(Path(directory), fingerprint)
            save_checkpoint(
                path,
                fingerprint,
                discovered=discovered,
                downloaded_keys={item_key(item)},
            )
            restored = load_checkpoint(path, fingerprint)
            serialized = path.read_text(encoding="utf-8")
        self.assertIsNotNone(restored)
        assert restored is not None
        self.assertEqual(restored["next_offset"], 80)
        self.assertEqual(restored["pages_scanned"], 8)
        self.assertEqual(restored["items"][0].mid, "1")
        self.assertEqual(restored["downloaded_keys"], [item_key(item)])
        self.assertNotIn("key=", serialized)

    def test_checkpoint_is_ignored_for_different_selection(self) -> None:
        first = make_fingerprint(
            "MzTest==",
            latest=None,
            start_date=date(2024, 1, 1),
            end_date=date(2026, 10, 23),
            max_pages=200,
        )
        second = dict(first)
        second["since"] = "2025-01-01"
        with tempfile.TemporaryDirectory() as directory:
            path = checkpoint_path(Path(directory), first)
            save_checkpoint(
                path,
                first,
                discovered=DiscoveryResult([], False, 1, "max_pages", 10),
                downloaded_keys=set(),
            )
            self.assertIsNone(load_checkpoint(path, second))


if __name__ == "__main__":
    unittest.main()
