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
    expected_files = {path.name: digest(path) for path in (skill_zip, portable_zip)}
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
