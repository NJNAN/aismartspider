"""HTTP fetching and optional rendering utilities."""

from __future__ import annotations

from typing import Optional

import requests

from .config import settings


class Fetcher:
    """Simple fetcher with optional Playwright rendering hook."""

    def __init__(self, use_playwright: bool = False) -> None:
        self.use_playwright = use_playwright

    def fetch(self, url: str) -> str:
        """Fetch page source via static request with optional render fallback."""
        html = None
        try:
            html = self._fetch_static(url)
        except Exception as e:
            if not self.use_playwright:
                print(f"Static fetch failed: {e}")
                return ""
            # If static fails and we have playwright, suppress error and try playwright
            pass

        if not html and self.use_playwright:
            html = self._fetch_with_playwright(url)
        return html or ""

    def _fetch_static(self, url: str) -> Optional[str]:
        headers = {"User-Agent": settings.user_agent}
        try:
            response = requests.get(url, headers=headers, timeout=settings.timeout)
            response.raise_for_status()
            return response.text
        except Exception:
            # Let the caller decide whether to suppress or not, but here we just raise
            # actually, to make the logic in fetch() cleaner, let's re-raise
            raise

    def _fetch_with_playwright(self, url: str) -> Optional[str]:
        try:
            from playwright.sync_api import sync_playwright
        except ImportError:
            print("Playwright not installed. Please run 'pip install playwright' and 'playwright install'.")
            return None

        try:
            with sync_playwright() as p:
                browser = p.chromium.launch(headless=True)
                # Create a new context with specific user agent if needed
                context = browser.new_context(user_agent=settings.user_agent)
                page = context.new_page()
                # Wait for network idle to ensure dynamic content is loaded
                page.goto(url, wait_until="networkidle", timeout=settings.timeout * 1000)
                content = page.content()
                browser.close()
                return content
        except Exception as e:
            print(f"Playwright fetch error: {e}")
            return None
