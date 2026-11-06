from __future__ import annotations

import unittest

from wechat_article_downloader.presets import ACCOUNT_PRESETS, preset_for_key, preset_for_label
from wechat_article_downloader.utils import parse_url_fields


class AccountPresetTests(unittest.TestCase):
    def test_fupeng_preset_has_valid_account_identity(self) -> None:
        preset = preset_for_key("fupeng-finance")
        self.assertIsNotNone(preset)
        self.assertEqual(preset.label, "付鹏的财经世界")
        self.assertEqual(preset.credential_alias, "fupeng-finance")
        self.assertTrue(preset.sample_url.startswith("https://mp.weixin.qq.com/s?"))
        self.assertEqual(parse_url_fields(preset.sample_url)["biz"], "MzkyNjQzMzY5OQ==")

    def test_preset_keys_and_labels_are_unique(self) -> None:
        self.assertEqual(len({preset.key for preset in ACCOUNT_PRESETS}), len(ACCOUNT_PRESETS))
        self.assertEqual(len({preset.label for preset in ACCOUNT_PRESETS}), len(ACCOUNT_PRESETS))
        self.assertIs(preset_for_label("付鹏的财经世界"), preset_for_key("fupeng-finance"))

