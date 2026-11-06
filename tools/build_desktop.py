"""Build a relocatable Windows x64 app in a clean build environment."""
from __future__ import annotations

import argparse
import importlib.metadata
import json
import os
import shutil
import subprocess
import sys
import zipfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("version")
    args = parser.parse_args()
    version = args.version.removeprefix("v")
    build = ROOT / "build" / "desktop"
    dist = ROOT / "dist" / "desktop"
    subprocess.run([
        sys.executable, "-m", "PyInstaller", "--noconfirm", "--clean", "--windowed", "--onedir",
        "--name", "WechatArchiver", "--distpath", str(dist), "--workpath", str(build),
        "--specpath", str(build), "--paths", str(ROOT / "skills/wechat-article-downloader/scripts"),
        "--hidden-import", "keyring.backends.Windows", "--collect-all", "tzdata",
        "--copy-metadata", "keyring", str(ROOT / "tools/desktop_entry.py"),
    ], check=True)
    app = dist / "WechatArchiver"
    for name in ("LICENSE", "NOTICE.md", "公众号历史归档器-使用说明.md"):
        shutil.copy2(ROOT / name, app / name)
    # Ship the dependency license texts alongside the executable.
    licenses = app / "third-party-licenses"
    licenses.mkdir(exist_ok=True)
    for distribution in importlib.metadata.distributions():
        name = distribution.metadata["Name"]
        for file in distribution.files or []:
            if any(word in file.name.lower() for word in ("license", "copying", "notice")):
                source = Path(distribution.locate_file(file))
                if source.is_file():
                    target = licenses / name / str(file).replace("..", "_")
                    target.parent.mkdir(parents=True, exist_ok=True)
                    shutil.copy2(source, target)
    python_license = Path(sys.base_prefix) / "LICENSE.txt"
    if python_license.exists():
        shutil.copy2(python_license, licenses / "Python-LICENSE.txt")
    release = ROOT / "release"
    release.mkdir(exist_ok=True)
    archive = release / f"wechat-article-archiver-windows-x64-v{version}.zip"
    with zipfile.ZipFile(archive, "w", zipfile.ZIP_DEFLATED) as handle:
        for path in sorted(app.rglob("*")):
            if path.is_file():
                handle.write(path, Path(f"WechatArchiver-v{version}") / path.relative_to(app))
    # Test the actual ZIP after relocation, with Python absent from PATH.
    extracted = build / "全新解压 中文路径" / f"WechatArchiver-v{version}"
    with zipfile.ZipFile(archive) as handle:
        handle.extractall(extracted.parent)
    report = build / "desktop-smoke.json"
    report.unlink(missing_ok=True)
    env = dict(os.environ)
    env["PATH"] = str(Path(os.environ["SystemRoot"]) / "System32")
    env.pop("PYTHONPATH", None)
    env.pop("PYTHONHOME", None)
    env["WECHAT_DOWNLOADER_HOME"] = str(build / "fresh-profile")
    subprocess.run(
        [str(extracted / "WechatArchiver.exe"), "--self-test", str(report)],
        cwd=extracted.parent, env=env, check=True, timeout=60,
    )
    if not json.loads(report.read_text(encoding="utf-8"))["ok"]:
        raise SystemExit("Desktop ZIP smoke test failed")
    print(f"Desktop ZIP verified without Python on PATH: {archive.name}")


if __name__ == "__main__":
    main()
