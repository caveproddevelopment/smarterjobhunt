"""
Shared error types for the scraping layer.

`ScraperBrowserDeadError` is raised by career_scraper.py /
async_career_scraper.py when the shared Playwright browser's
underlying driver connection has died mid-scrape (e.g. the Node
driver process crashed or was OOM-killed). This is NOT an ordinary
per-company scrape failure — every other task sharing that same
browser instance would fail the exact same way — so the orchestrators
catch this specifically, discard the broken browser, and retry with a
fresh one, rather than just recording the company as failed and
moving on.

That "just move on" behavior is what silently happened during the
2026-08-24 incident: the shared browser's driver process crashed
~94% through a 1923-company run, and every remaining company on the
affected thread kept "succeeding" with 0 jobs found — indistinguishable
in the logs from a company that genuinely has no listed openings.
"""


class ScraperBrowserDeadError(RuntimeError):
    """The browser's driver connection is gone — not this company's
    fault, and not fixable by retrying against the same browser."""


_DEAD_BROWSER_MARKERS = (
    "connection closed",
    "target page, context or browser has been closed",
    "browser has been closed",
    "target closed",
    "websocket connection closed",
    "browser has disconnected",
)


def is_dead_browser_error(exc: Exception) -> bool:
    """True if this exception looks like the browser process itself
    died (as opposed to an ordinary page-level failure like a
    navigation timeout or a selector not matching anything)."""
    msg = str(exc).lower()
    return any(marker in msg for marker in _DEAD_BROWSER_MARKERS)
