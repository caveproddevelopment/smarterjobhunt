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

Launch args now include `--disable-dev-shm-usage` — Docker containers
default /dev/shm to 64MB, too small for Chromium's shared memory needs
under real page rendering; this makes it use /tmp instead, which isn't
capped at a fixed tiny size.

Proactive recycling (closing the browser after N pages even if still
healthy — see the per-thread version in browser_pool.py) is
intentionally NOT done here: this pool hands out ONE browser shared by
every concurrent task, so closing it out from under tasks that are
mid-scrape would break them. If the same preventive-memory-growth
benefit is wanted here, the safer version is to recycle between
*batches* of tasks rather than while tasks are in flight — not
implemented yet.

2026-10-13: a second, lazily-launched browser with --disable-http2 is
available via get(http1=True). Several Akamai-fronted careers sites
(Honeywell, Yes Bank, Policybazaar, EA, Morgan Stanley, Lululemon in the
7 Oct logs) fail headless Chromium with net::ERR_HTTP2_PROTOCOL_ERROR but
load over HTTP/1.1. Only companies that hit that error ever touch it.
"""

import asyncio

_BASE_ARGS = ["--no-sandbox", "--disable-setuid-sandbox", "--disable-dev-shm-usage"]


class AsyncBrowserPool:
    def __init__(self, headless: bool = True):
        self._headless = headless
        self._lock = asyncio.Lock()
        # mode -> (playwright, browser); mode is "default" or "http1"
        self._slots: dict[str, tuple] = {}

    async def get(self, http1: bool = False):
        """Return the shared browser for this mode, launching or relaunching as needed."""
        mode = "http1" if http1 else "default"
        async with self._lock:
            slot = self._slots.get(mode)
            if slot is not None:
                dead = False
                try:
                    dead = not slot[1].is_connected()
                except Exception:
                    dead = True
                if dead:
                    print(f"[async_browser_pool] Browser ({mode}) connection is dead — relaunching.")
                    await self._retire_locked(mode)
                    slot = None
            if slot is not None:
                return slot[1]

            from playwright.async_api import async_playwright

            pw = await async_playwright().start()
            args = list(_BASE_ARGS) + (["--disable-http2"] if http1 else [])
            browser = await pw.chromium.launch(headless=self._headless, args=args)
            self._slots[mode] = (pw, browser)
            return browser

    async def invalidate(self):
        """Force the next get() to launch fresh browsers. Call this right
        after catching a ScraperBrowserDeadError, and between batches."""
        async with self._lock:
            for mode in list(self._slots):
                await self._retire_locked(mode)

    async def _retire_locked(self, mode: str):
        """Must only be called with self._lock already held."""
        slot = self._slots.pop(mode, None)
        if not slot:
            return
        pw, browser = slot
        try:
            await browser.close()
        except Exception:
            pass
        try:
            await pw.stop()
        except Exception:
            pass

    async def close(self):
        """Close all browsers and stop Playwright."""
        await self.invalidate()
