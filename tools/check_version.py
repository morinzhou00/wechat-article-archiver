from __future__ import annotations

import argparse
import re
import tomllib
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("version")
    args = parser.parse_args()
    expected = args.version.removeprefix("v")
    pyproject = tomllib.loads((ROOT / "pyproject.toml").read_text(encoding="utf-8"))
    project_version = str(pyproject["project"]["version"])
    init_text = (
        ROOT
        / "skills"
        / "wechat-article-downloader"
        / "scripts"
        / "wechat_article_downloader"
        / "__init__.py"
    ).read_text(encoding="utf-8")
    match = re.search(r'^__version__\s*=\s*"([^"]+)"', init_text, flags=re.MULTILINE)
    runtime_version = match.group(1) if match else ""
    if expected != project_version or expected != runtime_version:
        raise SystemExit(
            f"Version mismatch: tag={expected}, pyproject={project_version}, runtime={runtime_version}"
        )
    print(f"Version gate passed: {expected}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
