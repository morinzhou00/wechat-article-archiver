from __future__ import annotations

import json
import tempfile
import unittest
from pathlib import Path

from wechat_article_downloader.merge import merge_archives


def write_article(root: Path, *, title: str, mid: str, body: str) -> Path:
    directory = root / "测试号" / f"2026-10-23_{title}"
    directory.mkdir(parents=True)
    metadata = {
        "title": title,
        "account_name": "测试号",
        "author": "作者",
        "published_at": "2026-10-23T15:00:00+08:00",
        "digest": "摘要",
        "url": f"https://mp.weixin.qq.com/s?__biz=MzTest==&mid={mid}&idx=1&sn=abc",
        "biz": "MzTest==",
        "mid": mid,
        "idx": "1",
        "sn": "abc",
        "cover_url": None,
        "assets": [],
        "extra": {"timestamp": "1792719600"},
    }
    (directory / "article.json").write_text(json.dumps(metadata, ensure_ascii=False), encoding="utf-8")
    (directory / "article.md").write_text(
        f"# {title}\n\n- 公众号：测试号\n- 发布时间：2026-10-23T15:00+08:00\n"
        f"- 原文：{metadata['url']}\n\n{body}\n",
        encoding="utf-8",
    )
    return directory


class MergeTests(unittest.TestCase):
    def test_image_placeholders_do_not_create_false_conflicts(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            source = root / "source"
            target = root / "target"
            write_article(source, title="甲", mid="1", body="正文\n\n![]( )")
            target.mkdir()
            (target / "2026-10-23 甲.json").write_text(
                json.dumps(
                    {
                        "biz": "MzTest==",
                        "mid": "1",
                        "idx": "1",
                        "publish_time": "2026-10-23 15:00",
                        "content_text": "正文",
                    },
                    ensure_ascii=False,
                ),
                encoding="utf-8",
            )
            report = merge_archives(source, target, dry_run=True)
        self.assertEqual(report["added"], 0)
        self.assertEqual(report["already_present"], 1)
        self.assertEqual(report["conflicts"], [])

    def test_merge_adds_missing_and_preserves_existing(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            source = root / "source"
            target = root / "target"
            write_article(source, title="甲", mid="1", body="甲正文")
            write_article(source, title="乙", mid="2", body="乙正文")
            target.mkdir()
            existing_md = target / "2026-10-23 甲.md"
            existing_md.write_text("旧正文", encoding="utf-8")
            (target / "2026-10-23 甲.json").write_text(
                json.dumps(
                    {"biz": "MzTest==", "mid": "1", "idx": "1", "publish_time": "2026-10-23 15:00"},
                    ensure_ascii=False,
                ),
                encoding="utf-8",
            )

            report = merge_archives(source, target)

            self.assertEqual(report["added"], 1)
            self.assertEqual(len(report["conflicts"]), 1)
            self.assertTrue((target / "2026-10-23 乙.md").exists())
            self.assertEqual(existing_md.read_text(encoding="utf-8"), "旧正文")
            self.assertTrue((target / "_merge_report.json").exists())
            self.assertTrue((target / "_merge_report.md").exists())

    def test_dry_run_does_not_write_article_files(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            source = root / "source"
            target = root / "target"
            write_article(source, title="甲", mid="1", body="正文")
            report = merge_archives(source, target, dry_run=True)
            self.assertEqual(report["added"], 1)
            self.assertFalse((target / "2026-10-23 甲.md").exists())
            self.assertFalse((target / "_merge_report.json").exists())


if __name__ == "__main__":
    unittest.main()
