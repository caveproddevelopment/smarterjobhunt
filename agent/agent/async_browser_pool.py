"""
Async Browser Pool — manages Playwright async contexts for concurrent scraping.

This replaces the sync threading model with native async/await, eliminating
the greenlet sync-to-async context-switching issues.

Usage:
    pool = AsyncBrowserPool()
    browser = await pool.get()      # launches once per pool, cached
    jobs = await scrape_careers_page(url, domain, browser=browser)
    await pool.close()              # call once at the end
"""

import asyncio


class AsyncBrowserPool:
    def __init__(self, headless: bool = True):
        self._browser = None
        self._pw = None
        self._headless = headless
        self._lock = asyncio.Lock()

    async def get(self):
        """Return the shared browser, launching it on first use."""
        async with self._lock:
            if self._browser is not None:
                return self._browser

            from playwright.async_api import async_playwright

            self._pw = await async_playwright().start()
            self._browser = await self._pw.chromium.launch(
                headless=self._headless,
                args=["--no-sandbox", "--disable-setuid-sandbox"],
            )
        return self._browser

    async def close(self):
        """Close the browser and stop Playwright."""
        async with self._lock:
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

