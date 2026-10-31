"""SQLite persistence layer (the only module that talks to SQL).

Tables
------
``sources``         one row per news outlet
``articles``        every stored article; ``url_key`` (normalised URL) is UNIQUE,
                    which is what prevents duplicates
``saved_articles``  bookmarks (+ optional note) referencing ``articles``
``fetch_log``       one row per fetch run (used for statistics)
``settings``        key/value user preferences

A new connection is opened per operation, so the database can safely be used
from the GUI's background worker threads.
"""
from __future__ import annotations

import sqlite3
from contextlib import contextmanager
from datetime import timedelta
from pathlib import Path
from typing import Any, Dict, Iterable, Iterator, List, Optional, Tuple

from errors import DatabaseError
from filters import ArticleFilter
from logger import get_logger
from models import Article, InsertResult
from utils import normalize_url, utc_now, utc_now_iso

log = get_logger("database")

SCHEMA_VERSION = 1

SCHEMA = """
CREATE TABLE IF NOT EXISTS sources (
    id          INTEGER PRIMARY KEY AUTOINCREMENT,
    name        TEXT NOT NULL UNIQUE COLLATE NOCASE,
    api_id      TEXT NOT NULL DEFAULT '',
    description TEXT NOT NULL DEFAULT '',
    url         TEXT NOT NULL DEFAULT '',
    category    TEXT NOT NULL DEFAULT '',
    country     TEXT NOT NULL DEFAULT '',
    language    TEXT NOT NULL DEFAULT '',
    updated_at  TEXT NOT NULL DEFAULT ''
);

CREATE TABLE IF NOT EXISTS articles (
    id           INTEGER PRIMARY KEY AUTOINCREMENT,
    url          TEXT NOT NULL,
    url_key      TEXT NOT NULL UNIQUE,
    title        TEXT NOT NULL,
    description  TEXT NOT NULL DEFAULT '',
    content      TEXT NOT NULL DEFAULT '',
    author       TEXT NOT NULL DEFAULT '',
    image_url    TEXT NOT NULL DEFAULT '',
    published_at TEXT NOT NULL DEFAULT '',
    category     TEXT NOT NULL DEFAULT 'general',
    source_id    INTEGER NOT NULL REFERENCES sources(id) ON DELETE RESTRICT,
    fetched_at   TEXT NOT NULL,
    is_demo      INTEGER NOT NULL DEFAULT 0 CHECK (is_demo IN (0, 1))
);
CREATE INDEX IF NOT EXISTS idx_articles_published ON articles(published_at);
CREATE INDEX IF NOT EXISTS idx_articles_category  ON articles(category);
CREATE INDEX IF NOT EXISTS idx_articles_source    ON articles(source_id);
CREATE INDEX IF NOT EXISTS idx_articles_fetched   ON articles(fetched_at);
CREATE INDEX IF NOT EXISTS idx_articles_demo      ON articles(is_demo);

CREATE TABLE IF NOT EXISTS saved_articles (
    article_id INTEGER PRIMARY KEY REFERENCES articles(id) ON DELETE CASCADE,
    saved_at   TEXT NOT NULL,
    note       TEXT NOT NULL DEFAULT ''
);

CREATE TABLE IF NOT EXISTS fetch_log (
    id         INTEGER PRIMARY KEY AUTOINCREMENT,
    started_at TEXT NOT NULL,
    kind       TEXT NOT NULL,
    fetched    INTEGER NOT NULL DEFAULT 0,
    inserted   INTEGER NOT NULL DEFAULT 0,
    duplicates INTEGER NOT NULL DEFAULT 0,
    status     TEXT NOT NULL,
    message    TEXT NOT NULL DEFAULT ''
);

CREATE TABLE IF NOT EXISTS settings (
    key   TEXT PRIMARY KEY,
    value TEXT NOT NULL
);
"""

_ARTICLE_FROM = """
FROM articles a
JOIN sources s ON s.id = a.source_id
LEFT JOIN saved_articles sa ON sa.article_id = a.id
"""

_ARTICLE_SELECT = """
SELECT a.id, a.url, a.title, a.description, a.content, a.author, a.image_url,
       a.published_at, a.category, a.fetched_at, a.is_demo,
       s.name AS source_name, s.api_id AS source_api_id,
       CASE WHEN sa.article_id IS NULL THEN 0 ELSE 1 END AS is_saved,
       COALESCE(sa.note, '') AS note
""" + _ARTICLE_FROM


class Database:
    """Thin wrapper around a SQLite file."""

    def __init__(self, db_path: Path) -> None:
        self.db_path = Path(db_path)
        self.db_path.parent.mkdir(parents=True, exist_ok=True)
        self.initialize()

    # ------------------------------------------------------ connection --
    @contextmanager
    def connect(self) -> Iterator[sqlite3.Connection]:
        """Yield a connection; commit on success, roll back on error."""
        try:
            conn = sqlite3.connect(self.db_path, timeout=30)
        except sqlite3.Error as exc:
            raise DatabaseError(f"Cannot open database {self.db_path}: {exc}") from exc
        conn.row_factory = sqlite3.Row
        try:
            conn.execute("PRAGMA foreign_keys = ON")
            yield conn
            conn.commit()
        except sqlite3.Error as exc:
            conn.rollback()
            log.error("Database error: %s", exc)
            raise DatabaseError(f"Database error: {exc}") from exc
        except Exception:
            conn.rollback()
            raise
        finally:
            conn.close()

    def initialize(self) -> None:
        with self.connect() as conn:
            conn.executescript(SCHEMA)
            conn.execute("PRAGMA journal_mode = WAL")
            conn.execute(f"PRAGMA user_version = {SCHEMA_VERSION}")

    # --------------------------------------------------------- sources --
    @staticmethod
    def _source_id(conn: sqlite3.Connection, name: str, api_id: str, cache: Dict[str, int]) -> int:
        name = (name or "").strip()[:200] or "Unknown source"
        key = name.lower()
        if key in cache:
            return cache[key]
        conn.execute(
            "INSERT INTO sources (name, api_id, updated_at) VALUES (?, ?, ?) "
            "ON CONFLICT(name) DO UPDATE SET api_id = CASE WHEN sources.api_id = '' "
            "THEN excluded.api_id ELSE sources.api_id END",
            (name, (api_id or "").strip(), utc_now_iso()),
        )
        row = conn.execute("SELECT id FROM sources WHERE name = ?", (name,)).fetchone()
        cache[key] = row["id"]
        return row["id"]

    def upsert_sources(self, sources: Iterable[Dict[str, str]]) -> int:
        """Store source metadata (from NewsAPI's /sources endpoint)."""
        count = 0
        with self.connect() as conn:
            for src in sources:
                name = (src.get("name") or "").strip()
                if not name:
                    continue
                conn.execute(
                    "INSERT INTO sources (name, api_id, description, url, category, country, language, updated_at) "
                    "VALUES (?, ?, ?, ?, ?, ?, ?, ?) ON CONFLICT(name) DO UPDATE SET "
                    "api_id=excluded.api_id, description=excluded.description, url=excluded.url, "
                    "category=excluded.category, country=excluded.country, language=excluded.language, "
                    "updated_at=excluded.updated_at",
                    (name[:200], src.get("id", "") or "", src.get("description", "") or "",
                     src.get("url", "") or "", src.get("category", "") or "",
                     src.get("country", "") or "", src.get("language", "") or "", utc_now_iso()),
                )
                count += 1
        return count

    def list_sources(self, demo: bool, only_with_articles: bool = False) -> List[Dict[str, Any]]:
        """Sources of the current mode with their article counts."""
        having = "HAVING article_count > 0" if only_with_articles else ""
        sql = f"""
            SELECT s.id, s.name, s.api_id, s.description, s.url, s.category, s.country,
                   s.language, COUNT(a.id) AS article_count
            FROM sources s LEFT JOIN articles a ON a.source_id = s.id
            WHERE (s.api_id LIKE 'demo-%') = ?
            GROUP BY s.id {having}
            ORDER BY article_count DESC, s.name COLLATE NOCASE
        """
        with self.connect() as conn:
            return [dict(r) for r in conn.execute(sql, (1 if demo else 0,))]

    # -------------------------------------------------------- articles --
    def insert_articles(self, articles: Iterable[Article]) -> InsertResult:
        """Insert articles, ignoring duplicates (same normalised URL)."""
        result = InsertResult()
        now = utc_now_iso()
        cache: Dict[str, int] = {}
        with self.connect() as conn:
            for art in articles:
                title = (art.title or "").strip()
                try:
                    url_key = normalize_url(art.url)
                except ValueError:
                    url_key = ""
                if not title or not url_key:
                    result.skipped += 1
                    continue
                source_id = self._source_id(conn, art.source_name, art.source_api_id, cache)
                category = art.category or "general"
                cur = conn.execute(
                    "INSERT OR IGNORE INTO articles (url, url_key, title, description, content, author, "
                    "image_url, published_at, category, source_id, fetched_at, is_demo) "
                    "VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
                    (art.url.strip(), url_key, title[:500], (art.description or "")[:2000],
                     (art.content or "")[:5000], (art.author or "")[:300], (art.image_url or "").strip(),
                     art.published_at or "", category, source_id, now, 1 if art.is_demo else 0),
                )
                if cur.rowcount == 1:
                    result.inserted += 1
                else:
                    result.duplicates += 1
                    # Enrich the existing row: better category, missing image/description.
                    conn.execute(
                        "UPDATE articles SET "
                        "category = CASE WHEN category = 'general' AND ? <> 'general' THEN ? ELSE category END, "
                        "image_url = CASE WHEN image_url = '' THEN ? ELSE image_url END, "
                        "description = CASE WHEN description = '' THEN ? ELSE description END "
                        "WHERE url_key = ?",
                        (category, category, (art.image_url or "").strip(),
                         (art.description or "")[:2000], url_key),
                    )
        log.info("Inserted %d articles (%d duplicates, %d skipped)",
                 result.inserted, result.duplicates, result.skipped)
        return result

    def get_article(self, article_id: int) -> Optional[Article]:
        with self.connect() as conn:
            row = conn.execute(_ARTICLE_SELECT + " WHERE a.id = ?", (article_id,)).fetchone()
        return Article.from_row(row) if row else None

    def query_articles(self, flt: ArticleFilter, limit: Optional[int] = None, offset: int = 0) -> List[Article]:
        where, params = flt.to_sql()
        sql = _ARTICLE_SELECT + (f" WHERE {where}" if where else "") + f" ORDER BY {flt.order_sql()}"
        if limit is not None:
            sql += " LIMIT ? OFFSET ?"
            params = params + [int(limit), int(offset)]
        with self.connect() as conn:
            return [Article.from_row(r) for r in conn.execute(sql, params)]

    def count_articles(self, flt: ArticleFilter) -> int:
        where, params = flt.to_sql()
        sql = "SELECT COUNT(*) " + _ARTICLE_FROM + (f" WHERE {where}" if where else "")
        with self.connect() as conn:
            return conn.execute(sql, params).fetchone()[0]

    def update_article_details(self, article_id: int, image_url: str = "", description: str = "") -> bool:
        """Fill in a missing image/description (used by the web-page enrichment)."""
        with self.connect() as conn:
            cur = conn.execute(
                "UPDATE articles SET "
                "image_url = CASE WHEN image_url = '' THEN ? ELSE image_url END, "
                "description = CASE WHEN description = '' THEN ? ELSE description END WHERE id = ?",
                (image_url or "", (description or "")[:2000], article_id),
            )
            return cur.rowcount == 1

    def delete_article(self, article_id: int) -> bool:
        with self.connect() as conn:
            return conn.execute("DELETE FROM articles WHERE id = ?", (article_id,)).rowcount == 1

    def delete_demo_articles(self) -> int:
        with self.connect() as conn:
            n = conn.execute("DELETE FROM articles WHERE is_demo = 1").rowcount
            conn.execute("DELETE FROM sources WHERE api_id LIKE 'demo-%' AND id NOT IN "
                         "(SELECT DISTINCT source_id FROM articles)")
        return n

    def delete_older_than(self, days: int, demo: Optional[bool] = None) -> int:
        """Delete articles published (or, if undated, fetched) before the cutoff. Saved ones are kept."""
        cutoff = (utc_now() - timedelta(days=days)).strftime("%Y-%m-%dT%H:%M:%SZ")
        sql = ("DELETE FROM articles WHERE COALESCE(NULLIF(published_at, ''), fetched_at) < ? "
               "AND id NOT IN (SELECT article_id FROM saved_articles)")
        params: List[Any] = [cutoff]
        if demo is not None:
            sql += " AND is_demo = ?"
            params.append(1 if demo else 0)
        with self.connect() as conn:
            return conn.execute(sql, params).rowcount

    def clear_all(self) -> None:
        """Remove all articles, saved items, sources and the fetch log (settings are kept)."""
        with self.connect() as conn:
            for table in ("saved_articles", "articles", "sources", "fetch_log"):
                conn.execute(f"DELETE FROM {table}")

    # ----------------------------------------------------------- saved --
    def save_article(self, article_id: int, note: str = "") -> bool:
        """Bookmark an article. Returns False if it does not exist."""
        with self.connect() as conn:
            if not conn.execute("SELECT 1 FROM articles WHERE id = ?", (article_id,)).fetchone():
                return False
            conn.execute(
                "INSERT INTO saved_articles (article_id, saved_at, note) VALUES (?, ?, ?) "
                "ON CONFLICT(article_id) DO UPDATE SET note = CASE WHEN excluded.note <> '' "
                "THEN excluded.note ELSE saved_articles.note END",
                (article_id, utc_now_iso(), (note or "")[:1000]),
            )
        return True

    def unsave_article(self, article_id: int) -> bool:
        with self.connect() as conn:
            return conn.execute("DELETE FROM saved_articles WHERE article_id = ?", (article_id,)).rowcount == 1

    def update_note(self, article_id: int, note: str) -> bool:
        with self.connect() as conn:
            return conn.execute("UPDATE saved_articles SET note = ? WHERE article_id = ?",
                                ((note or "")[:1000], article_id)).rowcount == 1

    def count_saved(self) -> int:
        with self.connect() as conn:
            return conn.execute("SELECT COUNT(*) FROM saved_articles").fetchone()[0]

    # ------------------------------------------------------ statistics --
    def get_counts(self, demo: bool) -> Dict[str, int]:
        today = utc_now().strftime("%Y-%m-%d")
        flag = 1 if demo else 0
        with self.connect() as conn:
            q = lambda sql, *p: conn.execute(sql, p).fetchone()[0]  # noqa: E731
            return {
                "total": q("SELECT COUNT(*) FROM articles WHERE is_demo = ?", flag),
                "today": q("SELECT COUNT(*) FROM articles WHERE is_demo = ? AND substr(published_at,1,10) = ?", flag, today),
                "sources": q("SELECT COUNT(DISTINCT source_id) FROM articles WHERE is_demo = ?", flag),
                "saved": q("SELECT COUNT(*) FROM saved_articles"),
            }

    def count_by_source(self, demo: bool, limit: int = 10) -> List[Tuple[str, int]]:
        sql = ("SELECT s.name, COUNT(*) AS n FROM articles a JOIN sources s ON s.id = a.source_id "
               "WHERE a.is_demo = ? GROUP BY s.id ORDER BY n DESC, s.name LIMIT ?")
        with self.connect() as conn:
            return [(r[0], r[1]) for r in conn.execute(sql, (1 if demo else 0, limit))]

    def count_by_category(self, demo: bool) -> List[Tuple[str, int]]:
        sql = ("SELECT category, COUNT(*) AS n FROM articles WHERE is_demo = ? "
               "GROUP BY category ORDER BY n DESC, category")
        with self.connect() as conn:
            return [(r[0], r[1]) for r in conn.execute(sql, (1 if demo else 0,))]

    def count_by_collection_day(self, demo: bool, days: int = 30) -> List[Tuple[str, int]]:
        """Articles collected (stored) per day, for the last ``days`` days."""
        since = (utc_now() - timedelta(days=days - 1)).strftime("%Y-%m-%d")
        sql = ("SELECT substr(fetched_at,1,10) AS d, COUNT(*) FROM articles "
               "WHERE is_demo = ? AND substr(fetched_at,1,10) >= ? GROUP BY d ORDER BY d")
        with self.connect() as conn:
            return [(r[0], r[1]) for r in conn.execute(sql, (1 if demo else 0, since))]

    def recent_titles(self, demo: bool, limit: int = 500) -> List[str]:
        sql = ("SELECT title FROM articles WHERE is_demo = ? "
               "ORDER BY CASE WHEN published_at = '' THEN 1 ELSE 0 END, published_at DESC, id DESC LIMIT ?")
        with self.connect() as conn:
            return [r[0] for r in conn.execute(sql, (1 if demo else 0, limit))]

    # ------------------------------------------------------- fetch log --
    def log_fetch(self, kind: str, fetched: int, inserted: int, duplicates: int,
                  status: str, message: str = "") -> None:
        with self.connect() as conn:
            conn.execute(
                "INSERT INTO fetch_log (started_at, kind, fetched, inserted, duplicates, status, message) "
                "VALUES (?, ?, ?, ?, ?, ?, ?)",
                (utc_now_iso(), kind, fetched, inserted, duplicates, status, message[:500]),
            )

    def last_fetch(self, successful_only: bool = True) -> Optional[Dict[str, Any]]:
        sql = "SELECT * FROM fetch_log " + ("WHERE status = 'ok' " if successful_only else "") + "ORDER BY id DESC LIMIT 1"
        with self.connect() as conn:
            row = conn.execute(sql).fetchone()
        return dict(row) if row else None

    # --------------------------------------------------------- settings --
    def get_setting(self, key: str) -> Optional[str]:
        with self.connect() as conn:
            row = conn.execute("SELECT value FROM settings WHERE key = ?", (key,)).fetchone()
        return row[0] if row else None

    def set_setting(self, key: str, value: str) -> None:
        with self.connect() as conn:
            conn.execute("INSERT INTO settings (key, value) VALUES (?, ?) "
                         "ON CONFLICT(key) DO UPDATE SET value = excluded.value", (key, str(value)))

    # ----------------------------------------------------------- backup --
    def backup(self, destination: Path) -> Path:
        """Write a consistent copy of the database using SQLite's backup API."""
        destination = Path(destination)
        destination.parent.mkdir(parents=True, exist_ok=True)
        try:
            src = sqlite3.connect(self.db_path)
            dst = sqlite3.connect(destination)
            try:
                src.backup(dst)
            finally:
                dst.close()
                src.close()
        except sqlite3.Error as exc:
            raise DatabaseError(f"Backup failed: {exc}") from exc
        log.info("Database backed up to %s", destination)
        return destination
