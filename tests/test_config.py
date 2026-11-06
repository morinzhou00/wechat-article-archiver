from __future__ import annotations

import tempfile
import unittest
from pathlib import Path

from wechat_article_downloader.config import RuntimeConfig
from wechat_article_downloader.errors import InvalidInputError


class ConfigTests(unittest.TestCase):
    def test_numeric_and_boolean_types_are_strict(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            output = str(Path(directory) / "output")
            for changes in (
                {"timeout_seconds": 5.5},
                {"max_pages": "30"},
                {"console_port": True},
                {"include_assets": 1},
                {"request_interval_seconds": float("nan")},
            ):
                with self.subTest(changes=changes), self.assertRaises(InvalidInputError):
                    RuntimeConfig(output_dir=output, **changes).validate()

    def test_output_cannot_be_filesystem_root(self) -> None:
        with self.assertRaises(InvalidInputError):
            RuntimeConfig(output_dir=Path.cwd().anchor).validate()

    def test_valid_config_normalizes_formats_and_interval(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            config = RuntimeConfig(
                output_dir=str(Path(directory) / "output"),
                request_interval_seconds="3",
                default_formats="md,pdf",
            ).validate()
        self.assertEqual(config.request_interval_seconds, 3.0)
        self.assertEqual(config.default_formats, ("md", "pdf"))


if __name__ == "__main__":
    unittest.main()
