from __future__ import annotations

import csv
import html
import json
import mimetypes
import os
import shutil
import subprocess
import tempfile
from email.mime.application import MIMEApplication
from email.mime.multipart import MIMEMultipart
from email.mime.text import MIMEText
from email.policy import SMTP
from pathlib import Path

from bs4 import BeautifulSoup
from docx import Document
from docx.shared import Inches

from .errors import ExportError
from .models import Article, ExportResult
from .utils import safe_filename


ARTICLE_CSS = """
body{font-family:"Microsoft YaHei","Noto Sans CJK SC",sans-serif;max-width:760px;margin:40px auto;padding:0 24px;color:#24292f;line-height:1.75}
header{border-bottom:1px solid #d0d7de;margin-bottom:28px;padding-bottom:18px}h1{line-height:1.35}.meta{color:#57606a;font-size:14px}
img,video{max-width:100%;height:auto}pre{white-space:pre-wrap}.source{margin-top:36px;border-top:1px solid #d0d7de;padding-top:16px}
@media print{body{margin:0;max-width:none}.source{page-break-before:auto}}
""".strip()


class ArticleExporter:
    def prepare_directory(self, article: Article, output_root: Path) -> Path:
        account = safe_filename(article.account_name or "wechat")
        prefix = article.published_at.strftime("%Y-%m-%d_") if article.published_at else ""
        title = safe_filename(prefix + article.title)
        directory = output_root.expanduser().resolve() / account / title
        directory.mkdir(parents=True, exist_ok=True)
        return directory

    def export(self, article: Article, directory: Path, formats: list[str]) -> ExportResult:
        files: list[Path] = []
        offline_html = render_offline_html(article)
        html_path = directory / "article.html"
        if "html" in formats or "pdf" in formats or "mhtml" in formats:
            html_path.write_text(offline_html, encoding="utf-8")
            if "html" in formats:
                files.append(html_path)
        if "md" in formats:
            path = directory / "article.md"
            path.write_text(render_markdown(article), encoding="utf-8")
            files.append(path)
        if "json" in formats:
            path = directory / "article.json"
            path.write_text(json.dumps(article.metadata(), ensure_ascii=False, indent=2), encoding="utf-8")
            files.append(path)
        if "csv" in formats:
            path = directory / "article.csv"
            write_csv(path, article)
            files.append(path)
        if "txt" in formats:
            path = directory / "article.txt"
            path.write_text(render_text(article), encoding="utf-8")
            files.append(path)
        if "docx" in formats:
            path = directory / "article.docx"
            write_docx(path, article, directory)
            files.append(path)
        if "mhtml" in formats:
            path = directory / "article.mhtml"
            write_mhtml(path, offline_html, article, directory)
            files.append(path)
        if "pdf" in formats:
            path = directory / "article.pdf"
            print_pdf(html_path, path)
            files.append(path)
        manifest = directory / "manifest.json"
        manifest.write_text(
            json.dumps(
                {
                    "article": article.metadata(),
                    "files": [str(path.resolve()) for path in files],
                    "directory": str(directory.resolve()),
                },
                ensure_ascii=False,
                indent=2,
            ),
            encoding="utf-8",
        )
        files.append(manifest)
        if "html" not in formats:
            html_path.unlink(missing_ok=True)
        return ExportResult(directory=directory, files=files, article=article)


def render_offline_html(article: Article) -> str:
    metadata = " · ".join(
        value
        for value in (
            article.account_name,
            article.author,
            article.published_at.isoformat(timespec="minutes") if article.published_at else None,
        )
        if value
    )
    title = html.escape(article.title)
    meta = html.escape(metadata)
    source = html.escape(article.ref.url)
    source_url = html.escape(article.ref.url, quote=True)
    return (
        "<!doctype html><html lang=\"zh-CN\"><head><meta charset=\"utf-8\">"
        "<meta http-equiv=\"Content-Security-Policy\" content=\"default-src 'none'; "
        "img-src 'self' data:; media-src 'self'; style-src 'unsafe-inline'\">"
        f"<meta name=\"viewport\" content=\"width=device-width,initial-scale=1\"><title>{title}</title>"
        f"<style>{ARTICLE_CSS}</style></head><body><header><h1>{title}</h1>"
        f"<div class=\"meta\">{meta}</div></header><main>{article.content_html}</main>"
        f"<p class=\"source\">原文：<a href=\"{source_url}\">{source}</a></p></body></html>"
    )


def render_markdown(article: Article) -> str:
    lines = [f"# {article.title}", ""]
    if article.account_name:
        lines.append(f"- 公众号：{article.account_name}")
    if article.author:
        lines.append(f"- 作者：{article.author}")
    if article.published_at:
        lines.append(f"- 发布时间：{article.published_at.isoformat(timespec='minutes')}")
    lines.extend([f"- 原文：{article.ref.url}", "", article.content_markdown.strip(), ""])
    return "\n".join(lines)


def render_text(article: Article) -> str:
    soup = BeautifulSoup(article.content_html, "html.parser")
    return f"{article.title}\n{article.ref.url}\n\n{soup.get_text(chr(10), strip=True)}\n"


def write_csv(path: Path, article: Article) -> None:
    fields = ["title", "account_name", "author", "published_at", "url", "biz", "mid", "idx", "sn", "digest"]
    metadata = article.metadata()
    with path.open("w", encoding="utf-8-sig", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=fields)
        writer.writeheader()
        writer.writerow({field: metadata.get(field) or "" for field in fields})


def write_docx(path: Path, article: Article, directory: Path) -> None:
    document = Document()
    document.add_heading(article.title, level=0)
    if article.account_name:
        document.add_paragraph(f"公众号：{article.account_name}")
    if article.author:
        document.add_paragraph(f"作者：{article.author}")
    if article.published_at:
        document.add_paragraph(f"发布时间：{article.published_at.isoformat(timespec='minutes')}")
    document.add_paragraph(f"原文：{article.ref.url}")
    soup = BeautifulSoup(article.content_html, "html.parser")
    for node in soup.find_all(["h1", "h2", "h3", "h4", "p", "li", "blockquote", "img"]):
        if node.name == "img":
            source = node.get("src")
            if not source:
                continue
            image_path = directory / str(source)
            if image_path.exists():
                try:
                    document.add_picture(str(image_path), width=Inches(6))
                except Exception:
                    document.add_paragraph(f"[图片：{source}]")
            continue
        text = node.get_text(" ", strip=True)
        if not text:
            continue
        if node.name and node.name.startswith("h"):
            document.add_heading(text, level=min(int(node.name[1]), 4))
        elif node.name == "li":
            document.add_paragraph(text, style="List Bullet")
        elif node.name == "blockquote":
            document.add_paragraph(text, style="Quote")
        else:
            document.add_paragraph(text)
    document.save(path)


def write_mhtml(path: Path, offline_html: str, article: Article, directory: Path) -> None:
    root = MIMEMultipart("related", type="text/html")
    root["Subject"] = article.title
    root["From"] = "Saved by WeChat Article Downloader"
    html_part = MIMEText(offline_html, "html", "utf-8")
    html_part["Content-Location"] = article.ref.url
    root.attach(html_part)
    for asset in article.assets:
        local_path = directory / asset.relative_path
        if not local_path.exists():
            continue
        content_type = asset.content_type or mimetypes.guess_type(local_path.name)[0] or "application/octet-stream"
        major, minor = content_type.split("/", 1)
        part = MIMEApplication(local_path.read_bytes(), _subtype=minor)
        part.replace_header("Content-Type", f"{major}/{minor}")
        part["Content-Location"] = asset.relative_path
        root.attach(part)
    path.write_bytes(root.as_bytes(policy=SMTP))


def discover_browser() -> Path | None:
    candidates = [
        Path(os.environ.get("PROGRAMFILES(X86)", "")) / "Microsoft/Edge/Application/msedge.exe",
        Path(os.environ.get("PROGRAMFILES", "")) / "Microsoft/Edge/Application/msedge.exe",
        Path(os.environ.get("LOCALAPPDATA", "")) / "Microsoft/Edge/Application/msedge.exe",
        Path(os.environ.get("PROGRAMFILES", "")) / "Google/Chrome/Application/chrome.exe",
        Path(os.environ.get("PROGRAMFILES(X86)", "")) / "Google/Chrome/Application/chrome.exe",
        Path(os.environ.get("LOCALAPPDATA", "")) / "Google/Chrome/Application/chrome.exe",
    ]
    for candidate in candidates:
        if candidate.is_file():
            return candidate
    for name in ("msedge", "chrome", "chromium"):
        located = shutil.which(name)
        if located:
            return Path(located)
    return None


def print_pdf(html_path: Path, pdf_path: Path) -> None:
    browser = discover_browser()
    if browser is None:
        raise ExportError(
            "PDF export requires Microsoft Edge, Google Chrome, or Chromium.",
            details={"completed_html": str(html_path.resolve())},
        )
    with tempfile.TemporaryDirectory(prefix="wechat-pdf-") as user_data_dir:
        command = [
            str(browser),
            "--headless",
            "--disable-gpu",
            "--no-pdf-header-footer",
            f"--user-data-dir={user_data_dir}",
            f"--print-to-pdf={pdf_path.resolve()}",
            html_path.resolve().as_uri(),
        ]
        completed = subprocess.run(
            command,
            capture_output=True,
            text=True,
            encoding="utf-8",
            errors="replace",
            timeout=90,
            check=False,
        )
    if completed.returncode != 0 or not pdf_path.exists() or pdf_path.stat().st_size < 1000:
        raise ExportError(
            "The browser failed to create a PDF.",
            details={"browser": str(browser), "diagnostic": (completed.stderr or completed.stdout)[-500:]},
        )
