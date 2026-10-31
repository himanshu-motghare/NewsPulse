"""Application service layer - the single entry point used by both CLI and GUI.

It orchestrates the database, NewsAPI client, demo provider, scraper, exporter
and analytics so that neither front-end contains business logic.  Everything
here is plain Python (no GUI imports) and therefore unit-testable.
"""
from __future__ import annotations

import dataclasses
from datetime import date
from pathlib import Path
from typing import Callable, Dict, List, Optional, Tuple

import pandas as pd

import analytics
import exporter
from config import (APPEARANCE_MODES, CATEGORIES, COUNTRIES, DEFAULT_PREFERENCES,
                    FETCH_SIZES, PAGE_SIZES, Config)
from database import Database
from demo_data import build_demo_articles
from errors import (InvalidAPIKeyError, MissingAPIKeyError, NewsAPIError,
                    RateLimitError, ServiceError)
from filters import ArticleFilter
from logger import get_logger
from models import Article, FetchResult, Page
from news_fetcher import NewsAPIClient
from scraper import ArticleScraper
from utils import extract_keywords, utc_now_iso

log = get_logger("service")
ProgressFn = Callable[[int, int, str], None]


class Preferences:
    """Typed, validated access to the user preferences stored in SQLite."""

    def __init__(self, db: Database) -> None:
        self._db = db

    def _raw(self, key: str) -> str:
        value = self._db.get_setting(key)
        return DEFAULT_PREFERENCES[key] if value is None else value

    @property
    def country(self) -> str:
        value = self._raw("country")
        return value if value in COUNTRIES else DEFAULT_PREFERENCES["country"]

    @property
    def categories(self) -> List[str]:
        chosen = [c for c in self._raw("categories").split(",") if c in CATEGORIES]
        return chosen or list(CATEGORIES)

    @property
    def fetch_size(self) -> int:
        try:
            return int(self._raw("fetch_size"))
        except ValueError:
            return int(DEFAULT_PREFERENCES["fetch_size"])

    @property
    def page_size(self) -> int:
        try:
            value = int(self._raw("page_size"))
        except ValueError:
            return int(DEFAULT_PREFERENCES["page_size"])
        return value if value in PAGE_SIZES else int(DEFAULT_PREFERENCES["page_size"])

    @property
    def demo_mode(self) -> bool:
        return self._raw("demo_mode") == "1"

    @property
    def appearance(self) -> str:
        value = self._raw("appearance")
        return value if value in APPEARANCE_MODES else "Dark"

    def set(self, key: str, value) -> None:
        """Validate and persist one preference."""
        if key not in DEFAULT_PREFERENCES:
            raise ServiceError(f"Unknown setting '{key}'.")
        if key == "country":
            value = str(value).lower()
            if value not in COUNTRIES:
                raise ServiceError(f"Unsupported country code '{value}'.")
        elif key == "categories":
            items = [c.strip().lower() for c in (value.split(",") if isinstance(value, str) else value)]
            if not items or any(c not in CATEGORIES for c in items):
                raise ServiceError("Choose at least one valid category.")
            value = ",".join(dict.fromkeys(items))
        elif key in ("fetch_size", "page_size"):
            allowed = FETCH_SIZES if key == "fetch_size" else PAGE_SIZES
            try:
                value = int(value)
            except (TypeError, ValueError):
                raise ServiceError(f"{key} must be a number.") from None
            if value not in allowed:
                raise ServiceError(f"{key} must be one of {', '.join(map(str, allowed))}.")
        elif key == "demo_mode":
            value = "1" if value in (True, 1, "1", "true", "True") else "0"
        elif key == "appearance":
            if value not in APPEARANCE_MODES:
                raise ServiceError(f"Appearance must be one of {', '.join(APPEARANCE_MODES)}.")
        self._db.set_setting(key, str(value))


class NewsService:
    """High-level operations for the application."""

    def __init__(self, config: Optional[Config] = None, db: Optional[Database] = None,
                 client_factory: Optional[Callable[[str], NewsAPIClient]] = None,
                 scraper: Optional[ArticleScraper] = None) -> None:
        self.config = config or Config()
        self.db = db or Database(self.config.paths.db_path)
        self.prefs = Preferences(self.db)
        self._client_factory = client_factory or (lambda key: NewsAPIClient(key))
        self._scraper = scraper

    # ------------------------------------------------------------ mode --
    @property
    def demo_mode(self) -> bool:
        return self.prefs.demo_mode

    @property
    def needs_setup(self) -> bool:
        """True when live mode is selected but no API key exists."""
        return not self.demo_mode and not self.config.has_api_key

    @property
    def mode_label(self) -> str:
        return "DEMO MODE - sample data" if self.demo_mode else "Live"

    def _client(self) -> NewsAPIClient:
        key = self.config.api_key
        if not key:
            raise MissingAPIKeyError(
                "No NewsAPI key found. Get a free key at https://newsapi.org/register, add it to "
                "Settings (or NEWSAPI_KEY in .env), or switch to demo mode to explore with sample data."
            )
        return self._client_factory(key)

    def _scoped(self, flt: Optional[ArticleFilter]) -> ArticleFilter:
        """Apply the live/demo scope so sample and real news never mix."""
        flt = flt or ArticleFilter()
        return dataclasses.replace(flt, demo=None if flt.saved_only else self.demo_mode)

    # ----------------------------------------------------------- fetch --
    def fetch_latest(self, progress: Optional[ProgressFn] = None) -> FetchResult:
        """Fetch top headlines for the configured country/categories (or load demo data)."""
        if self.demo_mode:
            result = self._store(build_demo_articles(), demo=True)
            self.db.log_fetch("demo", result.fetched, result.inserted, result.duplicates, "ok")
            return result

        client = self._client()
        categories = self.prefs.categories
        result = FetchResult(demo=False)
        successes, last_error = 0, None
        for i, category in enumerate(categories):
            if progress:
                progress(i, len(categories), f"Fetching {category} headlines…")
            try:
                articles = client.top_headlines(country=self.prefs.country, category=category,
                                                page_size=self.prefs.fetch_size)
            except InvalidAPIKeyError as exc:
                self.db.log_fetch("headlines", 0, 0, 0, "error", str(exc))
                raise
            except RateLimitError as exc:
                last_error = exc
                result.errors.append(str(exc))
                break
            except NewsAPIError as exc:
                last_error = exc
                result.errors.append(f"{category}: {exc}")
                continue
            successes += 1
            self._merge(result, articles)
        if progress:
            progress(len(categories), len(categories), "Done")
        if successes == 0 and last_error is not None:
            self.db.log_fetch("headlines", 0, 0, 0, "error", str(last_error))
            raise last_error
        self.db.log_fetch("headlines", result.fetched, result.inserted, result.duplicates,
                          "ok" if not result.errors else "partial", "; ".join(result.errors))
        return result

    def search_online(self, query: str, date_from: Optional[date] = None,
                      date_to: Optional[date] = None) -> FetchResult:
        """Search NewsAPI's archive for ``query`` and store the results."""
        if self.demo_mode:
            raise ServiceError("Online search needs live mode. Switch off demo mode in Settings and add an API key.")
        query = (query or "").strip()
        if len(query) < 2:
            raise ServiceError("Enter at least 2 characters to search online.")
        if date_from and date_to and date_from > date_to:
            raise ServiceError("The start date must not be after the end date.")
        client = self._client()
        articles = client.search(query, date_from=date_from, date_to=date_to, page_size=self.prefs.fetch_size)
        result = FetchResult(demo=False)
        self._merge(result, articles)
        self.db.log_fetch("search", result.fetched, result.inserted, result.duplicates, "ok", query)
        return result

    def refresh_sources(self) -> int:
        """Download the list of available sources from NewsAPI."""
        if self.demo_mode:
            raise ServiceError("The source directory comes from NewsAPI - switch to live mode first.")
        sources = self._client().list_sources(language="en")
        stored = self.db.upsert_sources(sources)
        self.db.log_fetch("sources", stored, stored, 0, "ok")
        return stored

    def test_api_key(self, key: Optional[str] = None) -> Tuple[bool, str]:
        """Check a key (the saved one if ``key`` is None) with one tiny request."""
        key = (key if key is not None else self.config.api_key).strip()
        if not key:
            return False, "No API key entered."
        try:
            self._client_factory(key).verify_key()
        except NewsAPIError as exc:
            return False, str(exc)
        return True, "Connection successful - your API key works."

    def _store(self, articles: List[Article], demo: bool) -> FetchResult:
        result = FetchResult(demo=demo)
        self._merge(result, articles)
        return result

    def _merge(self, result: FetchResult, articles: List[Article]) -> None:
        outcome = self.db.insert_articles(articles)
        result.fetched += len(articles)
        result.inserted += outcome.inserted
        result.duplicates += outcome.duplicates
        result.skipped += outcome.skipped

    # ------------------------------------------------------------ read --
    def query(self, flt: Optional[ArticleFilter] = None, page: int = 1,
              page_size: Optional[int] = None) -> Page:
        flt = self._scoped(flt)
        page_size = page_size or self.prefs.page_size
        total = self.db.count_articles(flt)
        pages = max(1, -(-total // page_size))
        page = min(max(1, page), pages)
        items = self.db.query_articles(flt, limit=page_size, offset=(page - 1) * page_size)
        return Page(items=items, total=total, page=page, page_size=page_size)

    def all_matching(self, flt: Optional[ArticleFilter] = None) -> List[Article]:
        return self.db.query_articles(self._scoped(flt))

    def get_article(self, article_id: int) -> Optional[Article]:
        return self.db.get_article(article_id)

    def category_counts(self) -> Dict[str, int]:
        """Article count for every supported category (zero-filled) in the current mode."""
        counts = dict(self.db.count_by_category(self.demo_mode))
        return {c: counts.get(c, 0) for c in CATEGORIES}

    def source_names(self) -> List[str]:
        return [s["name"] for s in self.db.list_sources(self.demo_mode, only_with_articles=True)]

    def list_sources(self) -> List[Dict]:
        return self.db.list_sources(self.demo_mode)

    # ------------------------------------------------------ bookmarks --
    def save_article(self, article_id: int, note: str = "") -> None:
        if not self.db.save_article(article_id, note):
            raise ServiceError(f"Article {article_id} does not exist.")

    def unsave_article(self, article_id: int) -> None:
        if not self.db.unsave_article(article_id):
            raise ServiceError(f"Article {article_id} is not in your saved list.")

    def update_note(self, article_id: int, note: str) -> None:
        if not self.db.update_note(article_id, note):
            raise ServiceError("Save the article first, then add a note.")

    def delete_article(self, article_id: int) -> None:
        if not self.db.delete_article(article_id):
            raise ServiceError(f"Article {article_id} does not exist.")

    # ----------------------------------------------------- enrichment --
    def enrich_article(self, article_id: int) -> Article:
        """Read the original web page and fill in a missing image/description."""
        article = self.db.get_article(article_id)
        if not article:
            raise ServiceError(f"Article {article_id} does not exist.")
        if article.is_demo:
            raise ServiceError("Demo articles link to example.com and have no real page to read.")
        scraper = self._scraper or ArticleScraper()
        meta = scraper.fetch_metadata(article.url)
        self.db.update_article_details(article_id, meta.image_url, meta.description)
        return self.db.get_article(article_id)

    # ------------------------------------------------------ dashboard --
    def dashboard(self) -> Dict:
        demo = self.demo_mode
        return {
            "counts": self.db.get_counts(demo),
            "recent": self.db.query_articles(ArticleFilter(demo=demo), limit=6),
            "keywords": extract_keywords(self.db.recent_titles(demo), 12),
            "categories": self.db.count_by_category(demo),
            "last_fetch": self.db.last_fetch(),
        }

    # ------------------------------------------------------- analytics --
    def analytics_frames(self, days: int = 14) -> Dict[str, pd.DataFrame]:
        demo = self.demo_mode
        return {
            "source": analytics.to_frame(self.db.count_by_source(demo, 10), "source"),
            "category": analytics.to_frame(self.db.count_by_category(demo), "category"),
            "daily": analytics.daily_frame(self.db.count_by_collection_day(demo, days), days),
        }

    def chart(self, kind: str, theme: str = "dark", destination: Optional[Path] = None,
              days: int = 14) -> Path:
        frames = self.analytics_frames(days)
        builders = {"source": analytics.source_chart, "category": analytics.category_chart,
                    "daily": analytics.daily_chart}
        if kind not in builders:
            raise ServiceError(f"Unknown chart '{kind}'. Choose source, category or daily.")
        fig = builders[kind](frames[kind], theme)
        destination = destination or (self.config.paths.exports_dir /
                                      f"newspulse_chart_{kind}_{utc_now_iso().replace(':', '')}.png")
        return analytics.save_figure(fig, destination)

    # ---------------------------------------------------------- export --
    def export(self, fmt: str, flt: Optional[ArticleFilter] = None,
               filename: Optional[str] = None) -> Tuple[Path, int]:
        """Export every article matching ``flt``; returns ``(path, count)``."""
        flt = flt or ArticleFilter()
        articles = self.all_matching(flt)
        path = exporter.export_articles(articles, fmt, self.config.paths.exports_dir,
                                        flt.describe(), demo=self.demo_mode and not flt.saved_only,
                                        filename=filename)
        return path, len(articles)

    def recent_exports(self, limit: int = 15) -> List[Path]:
        """Files in the exports folder, newest first (charts and data files)."""
        folder = self.config.paths.exports_dir
        if not folder.exists():
            return []
        files = [p for p in folder.iterdir()
                 if p.is_file() and p.suffix.lower() in (".csv", ".xlsx", ".json", ".png")]
        return sorted(files, key=lambda p: p.stat().st_mtime, reverse=True)[:limit]

    def delete_export(self, path: Path) -> None:
        """Delete one exported file. Refuses anything outside the exports folder."""
        folder = self.config.paths.exports_dir.resolve()
        target = Path(path).resolve()
        if target.parent != folder:
            raise ServiceError("Only files inside the exports folder can be deleted here.")
        if not target.is_file():
            raise ServiceError("That file no longer exists.")
        try:
            target.unlink()
        except OSError as exc:
            raise ServiceError(f"Could not delete the file: {exc}") from exc

    # ----------------------------------------------------- maintenance --
    def backup_database(self) -> Path:
        stamp = utc_now_iso().replace(":", "").replace("-", "")
        return self.db.backup(self.config.paths.backups_dir / f"newspulse_backup_{stamp}.db")

    def purge_demo_data(self) -> int:
        return self.db.delete_demo_articles()

    def purge_older_than(self, days: int) -> int:
        if days < 1:
            raise ServiceError("Enter a number of days (1 or more).")
        return self.db.delete_older_than(days, demo=self.demo_mode)

    def clear_all_data(self) -> None:
        self.db.clear_all()
