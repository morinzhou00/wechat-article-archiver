"""Frozen desktop entry point; --self-test does not access WeChat or stored credentials."""
from __future__ import annotations

import json
import sys
from pathlib import Path


def main() -> int:
    if len(sys.argv) == 3 and sys.argv[1] == "--self-test":
        from tkinter import Tk

        import keyring
        from keyring.backends.Windows import WinVaultKeyring

        from wechat_article_downloader import __version__
        from wechat_article_downloader.gui import ArchiveGui
        from wechat_article_downloader.parser import parse_article_html

        root = Tk()
        root.withdraw()
        app = ArchiveGui(root)
        root.update_idletasks()
        assert app.since.get() == "2000-01-01"
        assert isinstance(keyring.get_keyring(), WinVaultKeyring)
        article = parse_article_html(
            "https://mp.weixin.qq.com/s/test",
            '<h1 id="activity-name">离线检查</h1><div id="js_content"><p>正文</p></div>',
        )
        assert article.title == "离线检查"
        root.destroy()
        Path(sys.argv[2]).write_text(
            json.dumps({"ok": True, "version": __version__, "gui": True, "windows_keyring": True}),
            encoding="utf-8",
        )
        return 0
    from wechat_article_downloader.gui import main as gui_main

    gui_main()
    return 0


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except Exception as exc:
        if "--self-test" in sys.argv:
            Path(sys.argv[2]).write_text(json.dumps({"ok": False, "error": type(exc).__name__}), encoding="utf-8")
            raise SystemExit(1)
        import ctypes

        from wechat_article_downloader.redaction import redact_text

        ctypes.windll.user32.MessageBoxW(
            None, "启动失败，请完整解压新版安装包后重试。\n" + redact_text(str(exc)), "公众号归档器", 16,
        )
        raise SystemExit(1)
