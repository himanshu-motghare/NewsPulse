"""Search / filter criteria shared by the CLI, the GUI and the exporter.

An :class:`ArticleFilter` validates user input once and turns it into a
parameterised SQL ``WHERE`` clause (never string-concatenated values, so there
is no SQL-injection risk).  All criteria combine with AND.
"""
from __future__ import annotations

import re
from dataclasses import dataclass
from datetime import date
from typing import List, Optional, Tuple

from config import CATEGORIES, SORT_OPTIONS
from errors import FilterError
from utils import parse_date

MAX_KEYWORD_LENGTH = 200
_TERM_RE = re.compile(r'"([^"]+)"|(\S+)')


def _like(term: str) -> str:
    escaped = term.replace("\\", "\\\\").replace("%", "\\%").replace("_", "\\_")
    return f"%{escaped}%"


@dataclass(frozen=True)
class ArticleFilter:
    keyword: str = ""
    source: str = ""
    category: str = ""
    date_from: Optional[date] = None
    date_to: Optional[date] = None
    sort: str = "newest"
    saved_only: bool = False
    demo: Optional[bool] = None      # None = both, True = demo only, False = live only

    # ------------------------------------------------------------ build --
    @classmethod
    def from_inputs(cls, keyword: str = "", source: str = "", category: str = "",
                    date_from: str = "", date_to: str = "", sort: str = "newest",
                    saved_only: bool = False, demo: Optional[bool] = None) -> "ArticleFilter":
        """Validate raw (string) user input and build a filter."""
        keyword = (keyword or "").strip()
        if len(keyword) > MAX_KEYWORD_LENGTH:
            raise FilterError(f"Search text is too long (maximum {MAX_KEYWORD_LENGTH} characters).")

        category = (category or "").strip().lower()
        if category in ("", "all", "all categories"):
            category = ""
        elif category not in CATEGORIES:
            raise FilterError(f"Unknown category '{category}'. Choose one of: {', '.join(CATEGORIES)}.")

        source = (source or "").strip()
        if source.lower() in ("all", "all sources"):
            source = ""
        if len(source) > 100:
            raise FilterError("Source name is too long.")

        sort = (sort or "newest").strip().lower()
        if sort not in SORT_OPTIONS:
            raise FilterError(f"Unknown sort order '{sort}'. Choose one of: {', '.join(SORT_OPTIONS)}.")

        try:
            start = parse_date(date_from) if (date_from or "").strip() else None
            end = parse_date(date_to) if (date_to or "").strip() else None
        except ValueError as exc:
            raise FilterError(str(exc)) from None
        if start and end and start > end:
            raise FilterError("The start date must not be after the end date.")

        return cls(keyword, source, category, start, end, sort, saved_only, demo)

    # -------------------------------------------------------------- SQL --
    def terms(self) -> List[str]:
        return [a or b for a, b in _TERM_RE.findall(self.keyword)]

    def to_sql(self) -> Tuple[str, List]:
        """Return ``(where_clause_without_WHERE, params)``; clause may be ''."""
        clauses: List[str] = []
        params: List = []
        for term in self.terms():
            clauses.append(
                "(a.title LIKE ? ESCAPE '\\' OR a.description LIKE ? ESCAPE '\\' "
                "OR a.content LIKE ? ESCAPE '\\' OR a.category LIKE ? ESCAPE '\\' "
                "OR s.name LIKE ? ESCAPE '\\')"
            )
            params.extend([_like(term)] * 5)
        if self.source:
            clauses.append("s.name LIKE ? ESCAPE '\\'")
            params.append(_like(self.source))
        if self.category:
            clauses.append("a.category = ?")
            params.append(self.category)
        if self.date_from:
            clauses.append("a.published_at <> '' AND substr(a.published_at, 1, 10) >= ?")
            params.append(self.date_from.isoformat())
        if self.date_to:
            clauses.append("a.published_at <> '' AND substr(a.published_at, 1, 10) <= ?")
            params.append(self.date_to.isoformat())
        if self.saved_only:
            clauses.append("sa.article_id IS NOT NULL")
        if self.demo is not None:
            clauses.append("a.is_demo = ?")
            params.append(1 if self.demo else 0)
        return " AND ".join(clauses), params

    def order_sql(self) -> str:
        undated_last = "CASE WHEN a.published_at = '' THEN 1 ELSE 0 END"
        if self.sort == "oldest":
            return f"{undated_last}, a.published_at ASC, a.id ASC"
        if self.sort == "source":
            return f"s.name COLLATE NOCASE ASC, {undated_last}, a.published_at DESC, a.id DESC"
        return f"{undated_last}, a.published_at DESC, a.id DESC"

    # ---------------------------------------------------------- display --
    @property
    def is_active(self) -> bool:
        return bool(self.keyword or self.source or self.category or self.date_from or self.date_to)

    def describe(self) -> str:
        """Human-readable summary, used in exports and the CLI."""
        parts = []
        if self.keyword:
            parts.append(f"keyword='{self.keyword}'")
        if self.source:
            parts.append(f"source~'{self.source}'")
        if self.category:
            parts.append(f"category={self.category}")
        if self.date_from:
            parts.append(f"from={self.date_from.isoformat()}")
        if self.date_to:
            parts.append(f"to={self.date_to.isoformat()}")
        if self.saved_only:
            parts.append("saved only")
        parts.append(f"sort={self.sort}")
        return ", ".join(parts)
