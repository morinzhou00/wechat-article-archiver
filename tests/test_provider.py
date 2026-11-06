from __future__ import annotations

import unittest
from unittest.mock import Mock

from wechat_article_downloader.errors import AuthRequiredError, RemoteError
from wechat_article_downloader.provider import WeChatHistoryProvider


class ProviderTests(unittest.TestCase):
    def test_params_include_bounded_history_contract(self) -> None:
        params = WeChatHistoryProvider._params(
            "MzTest==",
            {"uin": "u", "key": "k", "pass_ticket": "p"},
            offset=20,
            count=99,
        )
        self.assertEqual(params["action"], "getmsg")
        self.assertEqual(params["is_ok"], "1")
        self.assertEqual(params["count"], "20")
        self.assertEqual(params["offset"], "20")
        self.assertEqual(params["scene"], "124")

    def test_empty_json_is_not_accepted_as_history(self) -> None:
        response = Mock()
        response.status_code = 200
        response.raise_for_status.return_value = None
        response.json.return_value = {}
        provider = WeChatHistoryProvider(interval_seconds=1)
        provider._refresh_poc_if_needed = Mock()
        provider.session.get = Mock(return_value=response)
        with self.assertRaises(RemoteError):
            provider.list_page(
                "MzTest==",
                {"uin": "u", "key": "k", "pass_ticket": "p"},
            )

    def test_only_known_auth_return_codes_request_recapture(self) -> None:
        response = Mock()
        response.raise_for_status.return_value = None
        provider = WeChatHistoryProvider(interval_seconds=1)
        provider._refresh_poc_if_needed = Mock()
        provider.session.get = Mock(return_value=response)

        response.json.return_value = {"ret": -3, "errmsg": "expired"}
        with self.assertRaises(AuthRequiredError):
            provider.list_page("MzTest==", {"uin": "u", "key": "k", "pass_ticket": "p"})

        response.json.return_value = {"ret": 99999, "errmsg": "new response"}
        with self.assertRaises(RemoteError):
            provider.list_page("MzTest==", {"uin": "u", "key": "k", "pass_ticket": "p"})


if __name__ == "__main__":
    unittest.main()
