"""Plain data classes shared between layers."""
from __future__ import annotations

from dataclasses import dataclass, field, asdict
from typing import Any, Dict, List, Optional


@dataclass
class Article:
    """A single news article."""

    title: str
    url: str
    source_name: str
    description: str = ""
    content: str = ""
    author: str = ""
    image_url: str = ""
    published_at: str = ""          # ISO-8601 UTC, e.g. 2026-10-31T10:15:00Z
    category: str = "general"
    source_api_id: str = ""
    is_demo: bool = False
    # Populated when read back from the database:
    id: Optional[int] = None
    fetched_at: str = ""
    is_saved: bool = False
    note: str = ""

    def to_dict(self) -> Dict[str, Any]:
        return asdict(self)

    @classmethod
    def from_row(cls, row: Any) -> "Article":
        return cls(
            id=row["id"], url=row["url"], title=row["title"],
            description=row["description"], content=row["content"],
            author=row["author"], image_url=row["image_url"],
            published_at=row["published_at"], category=row["category"],
            source_name=row["source_name"], source_api_id=row["source_api_id"],
            fetched_at=row["fetched_at"], is_demo=bool(row["is_demo"]),
            is_saved=bool(row["is_saved"]), note=row["note"],
        )


@dataclass
class InsertResult:
    inserted: int = 0
    duplicates: int = 0
    skipped: int = 0   # invalid (no title / bad URL)


@dataclass
class FetchResult:
    """Outcome of one fetch operation."""

    fetched: int = 0
    inserted: int = 0
    duplicates: int = 0
    skipped: int = 0
    demo: bool = False
    errors: List[str] = field(default_factory=list)

    def summary(self) -> str:
        label = "demo articles" if self.demo else "articles"
        text = (f"Fetched {self.fetched} {label}: {self.inserted} new, "
                f"{self.duplicates} already stored")
        if self.skipped:
            text += f", {self.skipped} skipped"
        if self.errors:
            text += f". Warnings: {'; '.join(self.errors)}"
        return text + ("" if text.endswith(".") else ".")


@dataclass
class Page:
    """One page of query results."""

    items: List[Article]
    total: int
    page: int
    page_size: int

    @property
    def pages(self) -> int:
        return max(1, -(-self.total // self.page_size))
