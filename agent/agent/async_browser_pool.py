"""
Async Browser Pool — manages a single shared Playwright async Chromium
instance for concurrent scraping.

This replaces the sync threading model with native async/await, eliminating
the greenlet sync-to-async context-switching issues.

Usage:
    pool = AsyncBrowserPool()
    browser = await pool.get()      # launches once per pool, cached
    jobs = await scrape_careers_page(url, domain, browser=browser)
    await pool.close()              # call once at the end

Reliability additions (2026-08-24, after a driver crash on the sync
pipeline — see career_scraper.py's module docstring for the full
incident writeup): a health check on every `get()`, so a browser whose
underlying Node driver process died gets discarded and relaunched
instead of being handed back broken to every subsequent caller. Also
adds `invalidate()` so a caller that just caught a
ScraperBrowserDeadError can force the next `get()` to relaunch, without
waiting on the lazy health check.

Proactive recycling (closing the browser after N pages even if still
healthy — see the per-thread version in browser_pool.py) is
intentionally NOT done here: this pool hands out ONE browser shared by
every concurrent task, so closing it out from under tasks that are
mid-scrape would break them. If the same preventive-memory-growth
benefit is wanted here, the safer version is to recycle between
*batches* of tasks rather than while tasks are in flight — not
implemented yet.
"""

import asyncio


class AsyncBrowserPool:
    def __init__(self, headless: bool = True):
        self._browser = None
        self._pw = None
        self._headless = headless
        self._lock = asyncio.Lock()

    async def get(self):
        """Return the shared browser, launching or relaunching as needed."""
        async with self._lock:
            if self._browser is not None:
                dead = False
                try:
                    dead = not self._browser.is_connected()
                except Exception:
                    dead = True

                if dead:
                    print("[async_browser_pool] Browser connection is dead — relaunching.")
                    await self._retire_locked()

            if self._browser is not None:
                return self._browser

            from playwright.async_api import async_playwright

            self._pw = await async_playwright().start()
            self._browser = await self._pw.chromium.launch(
                headless=self._headless,
                args=["--no-sandbox", "--disable-setuid-sandbox"],
            )
        return self._browser

    async def invalidate(self):
        """Force the next get() to launch a fresh browser. Call this
        right after catching a ScraperBrowserDeadError, so a retry
        doesn't reuse the same broken instance."""
        async with self._lock:
            await self._retire_locked()

    async def _retire_locked(self):
        """Must only be called with self._lock already held."""
        if self._browser:
            try:
                await self._browser.close()
            except Exception:
                pass
        if self._pw:
            try:
                await self._pw.stop()
            except Exception:
                pass
        self._browser = None
        self._pw = None

    async def close(self):
        """Close the browser and stop Playwright."""
        async with self._lock:
            await self._retire_locked()
