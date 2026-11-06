from __future__ import annotations

import tempfile
import unittest
from pathlib import Path
from urllib.parse import urlencode

from wechat_article_downloader.capture import build_account_home_url, scan_credentials
from wechat_article_downloader.errors import InvalidInputError


class CaptureTests(unittest.TestCase):
    def test_scans_target_biz_and_redacts_summary(self) -> None:
        biz = "MzSynthetic=="
        query = urlencode(
            {
                "action": "getmsg",
                "__biz": biz,
                "uin": "secret-uin",
                "key": "secret-key",
                "pass_ticket": "secret-ticket",
            }
        )
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            (root / "cache.bin").write_bytes(f"prefix https://mp.weixin.qq.com/mp/profile_ext?{query} suffix".encode())
            seen: set[tuple[str, int, int]] = set()
            report = scan_credentials(biz, since_minutes=10, max_files=100, roots=[root], seen_versions=seen)
            unchanged = scan_credentials(biz, since_minutes=10, max_files=100, roots=[root], seen_versions=seen)
        self.assertEqual(len(report.candidates), 1)
        summary = report.summary()
        serialized = repr(summary)
        self.assertNotIn("secret-key", serialized)
        self.assertNotIn("secret-ticket", serialized)
        self.assertIn("key", summary["candidates"][0]["field_names"])
        self.assertEqual(unchanged.scanned_files, 0)

    def test_home_url_is_encoded(self) -> None:
        url = build_account_home_url("MzTest==")
        self.assertIn("action=home", url)
        self.assertIn("__biz=MzTest%3D%3D", url)
        self.assertTrue(url.endswith("#wechat_redirect"))

    def test_scan_reports_byte_budget_truncation(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            (root / "large.bin").write_bytes(b"x" * 2048)
            report = scan_credentials(
                "MzTest==",
                since_minutes=10,
                max_files=100,
                roots=[root],
                max_total_bytes=1024,
            )
        self.assertTrue(report.truncated)
        self.assertIn("total_byte_budget", report.truncation_reasons)
        self.assertEqual(report.scanned_files, 0)

    def test_scan_budget_values_are_validated(self) -> None:
        with self.assertRaises(InvalidInputError):
            scan_credentials("MzTest==", max_files=100, roots=[], max_scan_seconds=0)


if __name__ == "__main__":
    unittest.main()
