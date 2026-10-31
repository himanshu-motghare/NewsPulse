"""Custom exception hierarchy for NewsPulse.

Every error that can be shown to a user derives from :class:`NewsPulseError`,
so both the CLI and the GUI can catch one base class and display a friendly
message instead of a traceback.
"""


class NewsPulseError(Exception):
    """Base class for all application errors."""


class NewsAPIError(NewsPulseError):
    """Generic problem while talking to NewsAPI."""


class MissingAPIKeyError(NewsAPIError):
    """No NewsAPI key has been configured."""


class InvalidAPIKeyError(NewsAPIError):
    """NewsAPI rejected the configured key."""


class RateLimitError(NewsAPIError):
    """The NewsAPI request quota has been exhausted."""


class NetworkError(NewsAPIError):
    """A connection problem (offline, DNS failure, timeout...)."""


class DatabaseError(NewsPulseError):
    """A SQLite operation failed."""


class FilterError(NewsPulseError, ValueError):
    """User supplied an invalid search or filter value."""


class ExportError(NewsPulseError):
    """Exporting data to a file failed."""


class ScraperError(NewsPulseError):
    """A web page could not be read (blocked, offline, not HTML...)."""


class ServiceError(NewsPulseError):
    """A high-level operation was rejected (wrong mode, bad input...)."""
