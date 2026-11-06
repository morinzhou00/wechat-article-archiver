from __future__ import annotations

import json
import tempfile
import threading
import unittest
from http.client import HTTPConnection
from pathlib import Path
from urllib.error import HTTPError
from urllib.request import Request, urlopen

from wechat_article_downloader.server import ConsoleServer
from wechat_article_downloader.service import DownloadService


class ServerTests(unittest.TestCase):
    def setUp(self) -> None:
        self.temporary = tempfile.TemporaryDirectory()
        self.server = ConsoleServer(("127.0.0.1", 0), DownloadService(Path(self.temporary.name)))
        self.thread = threading.Thread(target=self.server.serve_forever, daemon=True)
        self.thread.start()
        self.base = f"http://127.0.0.1:{self.server.server_port}"

    def tearDown(self) -> None:
        self.server.shutdown()
        self.server.server_close()
        self.thread.join(timeout=3)
        self.temporary.cleanup()

    def test_status_and_security_headers(self) -> None:
        with urlopen(self.base + "/api/status") as response:
            payload = json.loads(response.read())
            self.assertTrue(payload["ok"])
            self.assertEqual(response.headers["X-Frame-Options"], "DENY")

    def test_mutation_requires_session_header(self) -> None:
        request = Request(
            self.base + "/api/article",
            data=b'{"url":"https://mp.weixin.qq.com/s/example"}',
            headers={"Content-Type": "application/json"},
            method="POST",
        )
        with self.assertRaises(HTTPError) as caught:
            urlopen(request)
        self.assertEqual(caught.exception.code, 403)

    def test_wrong_origin_is_rejected(self) -> None:
        request = Request(
            self.base + "/api/config",
            data=b'{"max_pages":10}',
            headers={
                "Content-Type": "application/json",
                "X-Wechat-Console": self.server.session_token,
                "Origin": "https://example.com",
            },
            method="POST",
        )
        with self.assertRaises(HTTPError) as caught:
            urlopen(request)
        self.assertEqual(caught.exception.code, 403)

    def test_untrusted_host_header_is_rejected(self) -> None:
        connection = HTTPConnection("127.0.0.1", self.server.server_port, timeout=3)
        connection.request(
            "GET",
            "/api/session",
            headers={"Host": f"attacker.example:{self.server.server_port}"},
        )
        response = connection.getresponse()
        payload = json.loads(response.read())
        connection.close()
        self.assertEqual(response.status, 403)
        self.assertEqual(payload["error"], "HOST_REJECTED")


if __name__ == "__main__":
    unittest.main()
