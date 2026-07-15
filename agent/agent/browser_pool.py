"""
Browser Pool — one persistent Playwright Chromium instance per worker
thread, reused across every company that thread handles.

This is the fix for the "new browser per company" problem in the
original career_scraper.py. Playwright's sync API is not thread-safe
across threads sharing one browser object, but it's perfectly fine for
each thread to own its own browser instance for the thread's lifetime.
So: thread A launches one browser and scrapes 40 companies with it;
thread B launches a separate one and scrapes another 40; etc. Instead
of 200 browser launches for 200 companies, you get (# worker threads)
launches total.

Usage:
    pool = BrowserPool()
    ...inside a worker thread...
    browser = pool.get()          # launches once per thread, cached after
    scrape_careers_page(url, domain, browser=browser)
    ...
    pool.close_all()              # call once, after all threads finish
"""

import threading


class BrowserPool:
    def __init__(self, headless: bool = True):
        self._local = threading.local()
        self._headless = headless
        self._all_instances = []  # (playwright_ctx, browser) — for cleanup
        self._lock = threading.Lock()

    def get(self):
        """Return this thread's browser, launching it on first use."""
        browser = getattr(self._local, "browser", None)
        if browser is not None:
            return browser

        from playwright.sync_api import sync_playwright

        pw = sync_playwright().start()
        browser = pw.chromium.launch(
            headless=self._headless,
            args=["--no-sandbox", "--disable-setuid-sandbox"],
        )
        self._local.pw = pw
        self._local.browser = browser

        with self._lock:
            self._all_instances.append((pw, browser))

        return browser

    def close_all(self):
        """Call after all worker threads have finished. Closes every
        browser instance that was ever created by any thread."""
        with self._lock:
            for pw, browser in self._all_instances:
                try:
                    browser.close()
                except Exception:
                    pass
                try:
                    pw.stop()
                except Exception:
                    pass
            self._all_instances.clear()
