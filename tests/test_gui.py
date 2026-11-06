import unittest

from wechat_article_downloader.gui import completion_message


class GuiResultTests(unittest.TestCase):
    def test_page_limit_is_not_reported_as_complete(self):
        self.assertFalse(completion_message({"ok": False, "history_scan": {"complete": False}})[2])

    def test_failed_article_is_not_reported_as_complete(self):
        result = {"ok": False, "history_scan": {"complete": True}, "failures": [{"code": "REMOTE_ERROR"}]}
        self.assertFalse(completion_message(result)[2])

    def test_complete_result(self):
        self.assertTrue(completion_message({"ok": True, "history_scan": {"complete": True}})[2])
