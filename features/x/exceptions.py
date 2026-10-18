class ScraperException(Exception):
    """Base exception for scraping operations."""
    pass

class PageNeverLoaded(ScraperException):
    """Raised when timeline posts fail to hydrate after retries on a non-empty page."""
    pass

class AccountUnavailable(ScraperException):
    """Raised when an account is suspended, does not exist, or is protected."""
    pass

class SessionExpired(ScraperException):
    """Raised when X redirects to login/flow, indicating expired or invalid cookies."""
    pass
