from __future__ import annotations

import argparse
import hashlib
import zipfile
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]


def digest(path: Path) -> str:
    value = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            value.update(chunk)
    return value.hexdigest()


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("version")
    args = parser.parse_args()
    version = args.version.removeprefix("v")
    release = ROOT / "release"
    skill_zip = release / f"wechat-article-downloader-skill-v{version}.zip"
    portable_zip = release / f"wechat-article-downloader-v{version}.zip"
    checksum_path = release / f"SHA256SUMS-v{version}.txt"
    desktop_zip = release / f"wechat-article-archiver-windows-x64-v{version}.zip"
    expected_files = {path.name: digest(path) for path in (skill_zip, portable_zip, desktop_zip)}
    with zipfile.ZipFile(desktop_zip) as archive:
        names = archive.namelist()
        prefix = f"WechatArchiver-v{version}/"
        for name in ("WechatArchiver.exe", "LICENSE", "NOTICE.md", "公众号历史归档器-使用说明.md"):
            if prefix + name not in names:
                raise SystemExit(f"Desktop ZIP missing {name}")
        if not any(name.endswith(".dll") for name in names):
            raise SystemExit("Desktop ZIP has no bundled runtime")
        forbidden_names = {"credential-metadata.json", "gui-settings.json", "history.jsonl", "config.json"}
        if any(Path(name).name in forbidden_names for name in names):
            raise SystemExit("Desktop ZIP contains local user state")
    checksum_rows = {}
    for line in checksum_path.read_text(encoding="ascii").splitlines():
        value, name = line.split(maxsplit=1)
        checksum_rows[name.strip()] = value
    if checksum_rows != expected_files:
        raise SystemExit(f"Checksum mismatch: expected {expected_files}, file has {checksum_rows}")
    for path, required in (
        (skill_zip, ("wechat-article-downloader/SKILL.md", "wechat-article-downloader/LICENSE")),
        (
            portable_zip,
            (
                f"wechat-article-downloader-v{version}/install.ps1",
                f"wechat-article-downloader-v{version}/LICENSE",
                f"wechat-article-downloader-v{version}/docs/protocol-principles.md",
                f"wechat-article-downloader-v{version}/启动公众号归档器.cmd",
                f"wechat-article-downloader-v{version}/归档公众号历史.ps1",
                f"wechat-article-downloader-v{version}/skills/wechat-article-downloader/SKILL.md",
            ),
        ),
    ):
        with zipfile.ZipFile(path) as archive:
            names = set(archive.namelist())
            missing = [name for name in required if name not in names]
            forbidden = [
                name
                for name in names
                if "/.runtime/" in name
                or "/__pycache__/" in name
                or name.endswith((".pyc", ".pyo"))
                or ".egg-info/" in name
            ]
            if missing or forbidden:
                raise SystemExit(f"{path.name}: missing={missing}, forbidden={forbidden[:10]}")
    print("Release archives and SHA256SUMS verified.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
