"""Configuration, paths and secure API-key handling for NewsPulse.

* Secrets (the NewsAPI key) live in a ``.env`` file - never in source code.
* Folders (database, exports, logs, cache) are created on demand.
* Set the ``NEWSPULSE_HOME`` environment variable to keep all data somewhere
  other than the project folder (the automated tests use this).
"""
from __future__ import annotations

import os
import re
from dataclasses import dataclass
from pathlib import Path
from typing import Optional

from dotenv import dotenv_values, set_key

from errors import ServiceError

APP_NAME = "NewsPulse"
APP_TAGLINE = "Smart News Aggregator"
APP_VERSION = "1.0.0"
USER_AGENT = f"{APP_NAME}/{APP_VERSION} (+https://github.com/your-username/NewsPulse)"

CODE_DIR = Path(__file__).resolve().parent

NEWSAPI_BASE_URL = "https://newsapi.org/v2"
API_KEY_ENV_VAR = "NEWSAPI_KEY"
_PLACEHOLDER_KEYS = {"", "your_api_key_here", "your-api-key-here"}

# Categories supported by NewsAPI's /top-headlines endpoint.
CATEGORIES = ("business", "entertainment", "general", "health", "science", "sports", "technology")

# Countries supported by NewsAPI's /top-headlines endpoint.
COUNTRIES = {
    "ae": "United Arab Emirates", "ar": "Argentina", "at": "Austria", "au": "Australia",
    "be": "Belgium", "bg": "Bulgaria", "br": "Brazil", "ca": "Canada", "ch": "Switzerland",
    "cn": "China", "co": "Colombia", "cu": "Cuba", "cz": "Czechia", "de": "Germany",
    "eg": "Egypt", "fr": "France", "gb": "United Kingdom", "gr": "Greece", "hk": "Hong Kong",
    "hu": "Hungary", "id": "Indonesia", "ie": "Ireland", "il": "Israel", "in": "India",
    "it": "Italy", "jp": "Japan", "kr": "South Korea", "lt": "Lithuania", "lv": "Latvia",
    "ma": "Morocco", "mx": "Mexico", "my": "Malaysia", "ng": "Nigeria", "nl": "Netherlands",
    "no": "Norway", "nz": "New Zealand", "ph": "Philippines", "pl": "Poland", "pt": "Portugal",
    "ro": "Romania", "rs": "Serbia", "ru": "Russia", "sa": "Saudi Arabia", "se": "Sweden",
    "sg": "Singapore", "si": "Slovenia", "sk": "Slovakia", "th": "Thailand", "tr": "Turkey",
    "tw": "Taiwan", "ua": "Ukraine", "us": "United States", "ve": "Venezuela", "za": "South Africa",
}

APPEARANCE_MODES = ("Dark", "Light", "System")
PAGE_SIZES = (10, 20, 30, 50)
FETCH_SIZES = (10, 20, 50, 100)
SORT_OPTIONS = {"newest": "Newest first", "oldest": "Oldest first", "source": "Source (A-Z)"}

# User preferences stored in the SQLite ``settings`` table (all values are text).
DEFAULT_PREFERENCES = {
    "country": "us",
    "categories": ",".join(CATEGORIES),
    "fetch_size": "30",
    "page_size": "20",
    "demo_mode": "0",
    "appearance": "Dark",
}


@dataclass(frozen=True)
class Paths:
    """Every file-system location used by the application."""

    base_dir: Path
    database_dir: Path
    db_path: Path
    backups_dir: Path
    exports_dir: Path
    logs_dir: Path
    cache_dir: Path
    env_file: Path
    assets_dir: Path

    @classmethod
    def build(cls, base_dir: Optional[os.PathLike] = None) -> "Paths":
        base = Path(base_dir).expanduser().resolve() if base_dir else CODE_DIR
        database_dir = base / "database"
        return cls(
            base_dir=base,
            database_dir=database_dir,
            db_path=database_dir / "newspulse.db",
            backups_dir=database_dir / "backups",
            exports_dir=base / "exports",
            logs_dir=base / "logs",
            cache_dir=base / "cache",
            env_file=base / ".env",
            assets_dir=CODE_DIR / "assets",
        )

    def ensure(self) -> None:
        for folder in (self.database_dir, self.backups_dir, self.exports_dir,
                       self.logs_dir, self.cache_dir):
            folder.mkdir(parents=True, exist_ok=True)


class Config:
    """Runtime configuration: paths plus the NewsAPI key from ``.env``."""

    def __init__(self, base_dir: Optional[os.PathLike] = None) -> None:
        self.paths = Paths.build(base_dir or os.environ.get("NEWSPULSE_HOME"))
        self.paths.ensure()

    @property
    def api_key(self) -> str:
        """The configured key (``.env`` first, then the real environment)."""
        value = ""
        if self.paths.env_file.exists():
            value = (dotenv_values(self.paths.env_file).get(API_KEY_ENV_VAR) or "").strip()
        if not value:
            value = os.environ.get(API_KEY_ENV_VAR, "").strip()
        return "" if value.lower() in _PLACEHOLDER_KEYS else value

    @property
    def has_api_key(self) -> bool:
        return bool(self.api_key)

    @property
    def log_level(self) -> str:
        return os.environ.get("NEWSPULSE_LOG_LEVEL", "INFO").upper()

    @staticmethod
    def validate_api_key_format(key: str) -> str:
        key = (key or "").strip()
        if not re.fullmatch(r"[A-Za-z0-9_\-]{16,64}", key):
            raise ServiceError(
                "That does not look like a NewsAPI key. Keys are 32 letters/digits - "
                "copy it from https://newsapi.org/account."
            )
        return key

    def save_api_key(self, key: str) -> None:
        """Validate and store the key in ``.env`` (file is created if missing)."""
        key = self.validate_api_key_format(key)
        env = self.paths.env_file
        env.touch(exist_ok=True)
        set_key(str(env), API_KEY_ENV_VAR, key, quote_mode="never")
        try:
            env.chmod(0o600)  # owner-only; ignored on platforms without POSIX modes
        except OSError:
            pass

    def clear_api_key(self) -> None:
        env = self.paths.env_file
        if env.exists():
            set_key(str(env), API_KEY_ENV_VAR, "", quote_mode="never")
