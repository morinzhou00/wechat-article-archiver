from __future__ import annotations

from dataclasses import asdict, dataclass, field
from datetime import date, datetime
from pathlib import Path
from typing import Any

from .redaction import redact_url, redact_value


@dataclass(slots=True)
class ArticleRef:
    url: str
    biz: str | None = None
    mid: str | None = None
    idx: str | None = None
    sn: str | None = None


@dataclass(slots=True)
class ArticleAsset:
    remote_url: str
    relative_path: str
    kind: str
    content_type: str | None = None
    size: int = 0


@dataclass(slots=True)
class Article:
    ref: ArticleRef
    title: str
    account_name: str | None
    author: str | None
    published_at: datetime | None
    digest: str | None
    content_html: str
    content_markdown: str
    source_html: str
    cover_url: str | None = None
    assets: list[ArticleAsset] = field(default_factory=list)
    extra: dict[str, Any] = field(default_factory=dict)

    @property
    def published_date(self) -> date | None:
        return self.published_at.date() if self.published_at else None

    def metadata(self) -> dict[str, Any]:
        return {
            "title": self.title,
            "account_name": self.account_name,
            "author": self.author,
            "published_at": self.published_at.isoformat() if self.published_at else None,
            "digest": self.digest,
            "url": redact_url(self.ref.url),
            "biz": self.ref.biz,
            "mid": self.ref.mid,
            "idx": self.ref.idx,
            "sn": self.ref.sn,
            "cover_url": redact_url(self.cover_url) if self.cover_url else None,
            "assets": redact_value([asdict(item) for item in self.assets]),
            "extra": redact_value(self.extra),
        }


@dataclass(slots=True)
class HistoryItem:
    url: str
    title: str
    published_at: datetime
    digest: str | None = None
    author: str | None = None
    cover_url: str | None = None
    biz: str | None = None
    mid: str | None = None
    idx: str | None = None
    sn: str | None = None

    def to_dict(self) -> dict[str, Any]:
        payload = asdict(self)
        payload["published_at"] = self.published_at.isoformat()
        payload["url"] = redact_url(self.url)
        if self.cover_url:
            payload["cover_url"] = redact_url(self.cover_url)
        return redact_value(payload)

    @classmethod
    def from_dict(cls, payload: dict[str, Any]) -> "HistoryItem":
        published_at = payload.get("published_at")
        if not isinstance(published_at, str):
            raise ValueError("History item is missing published_at.")
        return cls(
            url=str(payload["url"]),
            title=str(payload.get("title") or "untitled"),
            published_at=datetime.fromisoformat(published_at),
            digest=payload.get("digest"),
            author=payload.get("author"),
            cover_url=payload.get("cover_url"),
            biz=payload.get("biz"),
            mid=payload.get("mid"),
            idx=payload.get("idx"),
            sn=payload.get("sn"),
        )


@dataclass(slots=True)
class ExportResult:
    directory: Path
    files: list[Path]
    article: Article

    def to_dict(self) -> dict[str, Any]:
        return {
            "directory": str(self.directory.resolve()),
            "files": [str(path.resolve()) for path in self.files],
            "article": self.article.metadata(),
        }


@dataclass(slots=True)
class DiscoveryResult:
    items: list[HistoryItem]
    complete: bool
    pages_scanned: int
    stop_reason: str
    next_offset: int | None

    def __iter__(self):
        return iter(self.items)

    def __len__(self) -> int:
        return len(self.items)

    def __getitem__(self, index: int) -> HistoryItem:
        return self.items[index]

    def summary(self) -> dict[str, object]:
        return {
            "complete": self.complete,
            "truncated": not self.complete,
            "pages_scanned": self.pages_scanned,
            "stop_reason": self.stop_reason,
            "next_offset": self.next_offset,
        }
