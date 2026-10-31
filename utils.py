"""Small, dependency-free helpers used across the project."""
from __future__ import annotations

import html
import os
import re
import subprocess
import sys
import webbrowser
from collections import Counter
from datetime import date, datetime, timedelta, timezone
from pathlib import Path
from typing import Iterable, List, Tuple
from urllib.parse import parse_qsl, urlencode, urlsplit, urlunsplit

_TRACKING_PARAMS = {
    "fbclid", "gclid", "yclid", "mc_cid", "mc_eid", "igshid", "ref", "ref_src",
    "cmpid", "ocid", "_ga", "spm", "share",
}

_STOPWORDS = frozenset("""
a about after again all also an and any are as at be been before being but by can could
did do does for from get got had has have he her his how i if in into is it its just may
more most new news no not now of on one only or our out over said says say she so some than
that the their them then there these they this to up us was we were what when where which
while who why will with would you your amid per via vs top latest live update updates
first last year years day days week today after against between under during make makes
demo sample headline
""".split())


# ----------------------------------------------------------------- URLs ----
def normalize_url(url: str) -> str:
    """Return a canonical key for an article URL (used for de-duplication).

    Lower-cases scheme and host, drops ``www.``, fragments, default ports,
    trailing slashes and tracking parameters (``utm_*``, ``fbclid`` ...), and
    sorts the remaining query parameters.  Raises ``ValueError`` if the value is
    not a usable http(s) URL.
    """
    raw = (url or "").strip()
    parts = urlsplit(raw)
    if parts.scheme.lower() not in ("http", "https") or not parts.hostname:
        raise ValueError(f"Not a valid http(s) URL: {url!r}")
    host = parts.hostname.lower()
    if host.startswith("www."):
        host = host[4:]
    port = parts.port
    if port and not ((parts.scheme == "http" and port == 80) or (parts.scheme == "https" and port == 443)):
        host = f"{host}:{port}"
    path = parts.path.rstrip("/")
    query = sorted(
        (k, v) for k, v in parse_qsl(parts.query, keep_blank_values=True)
        if not k.lower().startswith("utm_") and k.lower() not in _TRACKING_PARAMS
    )
    return urlunsplit((parts.scheme.lower(), host, path, urlencode(query), ""))


def is_http_url(url: str) -> bool:
    try:
        normalize_url(url)
        return True
    except ValueError:
        return False


# ---------------------------------------------------------------- dates ----
def utc_now() -> datetime:
    return datetime.now(timezone.utc)


def utc_now_iso() -> str:
    return utc_now().strftime("%Y-%m-%dT%H:%M:%SZ")


def parse_date(text: str) -> date:
    """Parse ``YYYY-MM-DD`` (also ``today`` / ``yesterday``). Raises ValueError."""
    value = (text or "").strip().lower()
    if value == "today":
        return utc_now().date()
    if value == "yesterday":
        return utc_now().date() - timedelta(days=1)
    try:
        return datetime.strptime(value, "%Y-%m-%d").date()
    except ValueError:
        raise ValueError(f"Invalid date {text!r}. Use the format YYYY-MM-DD (e.g. 2026-10-31).") from None


def normalize_timestamp(value: str) -> str:
    """Convert API timestamps to ``YYYY-MM-DDTHH:MM:SSZ`` (UTC). Empty if unparsable."""
    if not value:
        return ""
    text = str(value).strip().replace("Z", "+00:00")
    try:
        dt = datetime.fromisoformat(text)
    except ValueError:
        return ""
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    return dt.astimezone(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def format_datetime(iso: str) -> str:
    """'2026-10-31T10:15:00Z' -> '31 Oct 2026, 10:15 UTC'."""
    if not iso:
        return "Date unknown"
    try:
        dt = datetime.strptime(iso, "%Y-%m-%dT%H:%M:%SZ")
    except ValueError:
        return iso
    return dt.strftime("%d %b %Y, %H:%M UTC")


def time_ago(iso: str) -> str:
    if not iso:
        return "date unknown"
    try:
        dt = datetime.strptime(iso, "%Y-%m-%dT%H:%M:%SZ").replace(tzinfo=timezone.utc)
    except ValueError:
        return iso
    seconds = int((utc_now() - dt).total_seconds())
    if seconds < 60:
        return "just now"
    if seconds < 3600:
        return f"{seconds // 60} min ago"
    if seconds < 86400:
        return f"{seconds // 3600} h ago"
    if seconds < 7 * 86400:
        return f"{seconds // 86400} d ago"
    return dt.strftime("%d %b %Y")


# ----------------------------------------------------------------- text ----
_TAG_RE = re.compile(r"<[^>]+>")
_SPACE_RE = re.compile(r"\s+")


def clean_text(text: str) -> str:
    """Strip HTML tags/entities and collapse whitespace."""
    if not text:
        return ""
    return _SPACE_RE.sub(" ", html.unescape(_TAG_RE.sub(" ", str(text)))).strip()


def truncate(text: str, limit: int) -> str:
    text = text or ""
    return text if len(text) <= limit else text[: max(0, limit - 1)].rstrip() + "…"


def extract_keywords(titles: Iterable[str], top_n: int = 12) -> List[Tuple[str, int]]:
    """Most frequent meaningful words across headlines (each title counts once)."""
    counter: Counter = Counter()
    for title in titles:
        words = {w.lower().strip("'-") for w in re.findall(r"[A-Za-z][A-Za-z'\-]{2,}", title or "")}
        counter.update(w for w in words if w and w not in _STOPWORDS)
    return counter.most_common(top_n)


# --------------------------------------------------------- OS integration --
def open_url(url: str) -> bool:
    """Open an http(s) URL in the default browser."""
    if not is_http_url(url):
        return False
    return webbrowser.open(url)


def open_path(path: os.PathLike) -> bool:
    """Open a file/folder with the operating system's default application."""
    target = str(Path(path))
    try:
        if sys.platform.startswith("win"):
            os.startfile(target)  # type: ignore[attr-defined]
        elif sys.platform == "darwin":
            subprocess.Popen(["open", target])
        else:
            subprocess.Popen(["xdg-open", target])
        return True
    except (OSError, ValueError):
        return False
