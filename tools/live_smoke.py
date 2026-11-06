from __future__ import annotations

import argparse
import json
import tempfile

from wechat_article_downloader.service import DownloadService


def main() -> int:
    parser = argparse.ArgumentParser(description="Explicit live WeChat public-article smoke test.")
    parser.add_argument("url")
    parser.add_argument("--output")
    args = parser.parse_args()
    temporary = None
    output = args.output
    if output is None:
        temporary = tempfile.TemporaryDirectory(prefix="wechat-live-")
        output = temporary.name
    result = DownloadService().download_article(
        args.url,
        formats=["html", "md", "json", "pdf"],
        output_dir=output,
        include_assets=False,
        trigger="live-smoke",
    )
    print(json.dumps(result, ensure_ascii=False, indent=2))
    if temporary:
        print(f"Temporary output retained until process exit: {output}")
        temporary.cleanup()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
