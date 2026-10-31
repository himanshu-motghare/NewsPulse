"""Polite web scraping with BeautifulSoup.

NewsAPI only returns a short description and often no image.  This module can
read a single article page and pull out its public Open Graph / meta tags
(image, description).  It is deliberately conservative:

* only http(s) URLs, one page per call, 10 s timeout, 2 MB size cap;
* ``robots.txt`` is honoured - pages that disallow crawling are never fetched;
* an honest User-Agent identifies the application.
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import Optional
from urllib.parse import urljoin, urlsplit
from urllib.robotparser import RobotFileParser

import requests
from bs4 import BeautifulSoup

from config import USER_AGENT
from errors import ScraperError
from logger import get_logger
from utils import clean_text, is_http_url

log = get_logger("scraper")

MAX_BYTES = 2_000_000
TIMEOUT = 10


@dataclass
class PageMetadata:
    title: str = ""
    description: str = ""
    image_url: str = ""
    site_name: str = ""


class ArticleScraper:
    def __init__(self, session: Optional[requests.Session] = None, timeout: float = TIMEOUT) -> None:
        self.session = session or requests.Session()
        self.session.headers.setdefault("User-Agent", USER_AGENT)
        self.timeout = timeout

    # ------------------------------------------------------ robots.txt --
    def is_allowed(self, url: str) -> bool:
        parts = urlsplit(url)
        robots_url = f"{parts.scheme}://{parts.netloc}/robots.txt"
        parser = RobotFileParser()
        try:
            resp = self.session.get(robots_url, timeout=self.timeout)
        except requests.exceptions.RequestException:
            return False                      # cannot verify -> be conservative
        if resp.status_code in (401, 403):
            return False
        if resp.status_code >= 400:
            return True                       # no robots.txt -> allowed
        parser.parse(resp.text.splitlines())
        return parser.can_fetch(USER_AGENT, url)

    # ------------------------------------------------------------ fetch --
    def fetch_metadata(self, url: str) -> PageMetadata:
        """Download one page and extract its metadata. Raises ScraperError."""
        if not is_http_url(url):
            raise ScraperError("Only http(s) links can be read.")
        if not self.is_allowed(url):
            raise ScraperError("This site's robots.txt does not allow automated access, so the page was not read.")
        try:
            resp = self.session.get(url, timeout=self.timeout, stream=True)
            resp.raise_for_status()
            if "html" not in resp.headers.get("Content-Type", "").lower():
                raise ScraperError("The link does not point to a web page.")
            body = b""
            for chunk in resp.iter_content(chunk_size=65536):
                body += chunk
                if len(body) > MAX_BYTES:
                    break
            html = body[:MAX_BYTES].decode(resp.encoding or "utf-8", errors="replace")
        except requests.exceptions.RequestException as exc:
            raise ScraperError(f"Could not load the page: {exc}") from exc
        return self.parse_metadata(html, url)

    @staticmethod
    def parse_metadata(html: str, base_url: str = "") -> PageMetadata:
        soup = BeautifulSoup(html, "html.parser")

        def meta(*names: str) -> str:
            for name in names:
                tag = soup.find("meta", attrs={"property": name}) or soup.find("meta", attrs={"name": name})
                if tag and tag.get("content"):
                    return clean_text(tag["content"])
            return ""

        image = meta("og:image", "og:image:url", "twitter:image")
        if image and base_url:
            image = urljoin(base_url, image)
        title = meta("og:title", "twitter:title") or (soup.title.get_text(strip=True) if soup.title else "")
        return PageMetadata(
            title=clean_text(title),
            description=meta("og:description", "description", "twitter:description"),
            image_url=image if is_http_url(image) else "",
            site_name=meta("og:site_name"),
        )
