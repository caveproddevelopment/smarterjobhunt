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

Reliability additions (2026-08-24, after a driver crash ~94% through a
1923-company run):
  - Health check on every `get()`: if the cached browser's underlying
    driver connection has died (`browser.is_connected()` is False),
    it's discarded and a fresh one is launched instead of being handed
    back broken. Before this fix, a dead browser stayed cached for the
    rest of the thread's queue, and every remaining company on that
    thread silently scored 0 jobs for the rest of the run.
  - `invalidate()`: lets a caller that just caught a
    ScraperBrowserDeadError force the *next* `get()` to launch fresh,
    without waiting on the lazy health check above (belt-and-suspenders).
  - Proactive recycling: after `recycle_after` companies on one browser
    instance, it's closed and relaunched even if still "healthy" —
    headless Chrome under sustained multi-hour load accumulates memory
    that a single `is_connected()` check won't catch until it's fatal.
    Set `recycle_after=0` to disable.

Usage:
    pool = BrowserPool()
    ...inside a worker thread...
    browser = pool.get()          # launches once per thread, cached after —
                                   # auto-restarted if dead or past its recycle age
    scrape_careers_page(url, domain, browser=browser)
    ...
    if something_went_wrong:
        pool.invalidate()         # force a fresh browser on this thread's next get()
    ...
    pool.close_all()              # call once, after all threads finish
"""

import threading

DEFAULT_RECYCLE_AFTER = 150  # companies per browser instance before a preventive restart


class BrowserPool:
    def __init__(self, headless: bool = True, recycle_after: int = DEFAULT_RECYCLE_AFTER):
        self._local = threading.local()
        self._headless = headless
        self._recycle_after = recycle_after
        self._all_instances = []  # every (playwright_ctx, browser) ever created — for final cleanup
        self._lock = threading.Lock()

    def get(self):
        """Return this thread's browser, launching or relaunching as needed."""
        browser = getattr(self._local, "browser", None)
        uses = getattr(self._local, "uses", 0)

        if browser is not None:
            dead = False
            try:
                dead = not browser.is_connected()
            except Exception:
                dead = True  # if we can't even ask, treat it as dead

            if dead:
                print("[browser_pool] Browser connection is dead — relaunching.")
                self._retire_local()
                browser = None
            elif self._recycle_after and uses >= self._recycle_after:
                print(f"[browser_pool] Recycling browser after {uses} companies.")
                self._retire_local()
                browser = None

        if browser is not None:
            self._local.uses = uses + 1
            return browser

        from playwright.sync_api import sync_playwright

        pw = sync_playwright().start()
        browser = pw.chromium.launch(
            headless=self._headless,
            args=["--no-sandbox", "--disable-setuid-sandbox"],
        )
        self._local.pw = pw
        self._local.browser = browser
        self._local.uses = 1

        with self._lock:
            self._all_instances.append((pw, browser))

        return browser

    def invalidate(self):
        """Force this thread's next get() to launch a fresh browser.
        Call this right after catching a ScraperBrowserDeadError, so a
        retry doesn't reuse the same broken instance."""
        self._retire_local()

    def _retire_local(self):
        pw = getattr(self._local, "pw", None)
        browser = getattr(self._local, "browser", None)
        if browser is not None:
            try:
                browser.close()
            except Exception:
                pass
        if pw is not None:
            try:
                pw.stop()
            except Exception:
                pass
        self._local.browser = None
        self._local.pw = None
        self._local.uses = 0

    def close_all(self):
        """Call after all worker threads have finished. Closes every
        browser instance that was ever created by any thread (safe to
        call even on instances already retired mid-run — closing an
        already-closed browser/driver is a no-op wrapped in a
        try/except here)."""
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
