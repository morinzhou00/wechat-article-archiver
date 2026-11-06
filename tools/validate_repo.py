from __future__ import annotations

import compileall
import os
import re
import sys
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
SKILL = ROOT / "skills" / "wechat-article-downloader"
SKIP = {
    ".git",
    ".venv",
    ".runtime",
    ".test-runtime",
    "artifacts",
    "tmp",
    "dist",
    "build",
    "release",
    "__pycache__",
}


def main() -> int:
    errors: list[str] = []
    required = [
        ROOT / "README.md",
        ROOT / "LICENSE",
        ROOT / "SECURITY.md",
        ROOT / "pyproject.toml",
        SKILL / "SKILL.md",
        SKILL / "agents" / "openai.yaml",
        SKILL / "scripts" / "wechat-download.ps1",
        SKILL / "scripts" / "bootstrap.ps1",
        SKILL / "scripts" / "wechat_article_downloader" / "static" / "index.html",
    ]
    for path in required:
        if not path.is_file():
            errors.append(f"missing: {path.relative_to(ROOT)}")

    skill_text = (SKILL / "SKILL.md").read_text(encoding="utf-8")
    if "[TODO" in skill_text or not skill_text.startswith("---\n"):
        errors.append("SKILL.md contains a TODO or invalid frontmatter start")
    frontmatter = skill_text.split("---", 2)[1]
    if not re.search(r"^name:\s*wechat-article-downloader\s*$", frontmatter, re.MULTILINE):
        errors.append("SKILL.md name is invalid")
    description = re.search(r"^description:\s*(.+)$", frontmatter, re.MULTILINE)
    if not description or len(description.group(1)) > 1024:
        errors.append("SKILL.md description is missing or too long")

    readme = (ROOT / "README.md").read_text(encoding="utf-8")
    for expected in (
        "qiye45/wechatDownload",
        "二次开发",
        "未提供应用源码",
        "Windows Credential Manager",
    ):
        if expected not in readme:
            errors.append(f"README attribution/security text missing: {expected}")

    binaries = []
    walk_errors: list[str] = []
    for directory, names, filenames in os.walk(
        ROOT,
        topdown=True,
        followlinks=False,
        onerror=lambda exc: walk_errors.append(str(exc)),
    ):
        names[:] = [name for name in names if name not in SKIP and not name.endswith(".egg-info")]
        for filename in filenames:
            path = Path(directory) / filename
            if path.suffix.casefold() in {".exe", ".dll", ".bin", ".zip", ".7z"}:
                binaries.append(str(path.relative_to(ROOT)))
    if walk_errors:
        errors.append(f"repository scan failed: {walk_errors[:3]}")
    if binaries:
        errors.append(f"repository source contains forbidden binary payloads: {binaries}")

    requirements = (SKILL / "scripts" / "requirements.txt").read_text(encoding="utf-8").splitlines()
    if any(line.strip() and "==" not in line for line in requirements):
        errors.append("requirements.txt must use exact pins")

    package = SKILL / "scripts" / "wechat_article_downloader"
    if not compileall.compile_dir(package, quiet=1):
        errors.append("Python compileall failed")

    if errors:
        print("\n".join(f"ERROR: {error}" for error in errors), file=sys.stderr)
        return 1
    print("Repository validation passed.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
