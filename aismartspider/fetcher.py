"""HTTP fetching and automatic rendering utilities."""

from __future__ import annotations

import os
import shutil
import tempfile
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Dict, Optional, Sequence, Tuple

from curl_cffi import requests
from curl_cffi.requests import RequestsError

from .config import settings

try:
    import certifi
except ImportError:  # pragma: no cover - certifi is always installed in our env
    certifi = None


def _ensure_ascii_cert_path() -> Optional[str]:
    """Ensure CA bundle lives on an ASCII path (curl can't open non-ASCII)."""
    if certifi is None:
        return None

    try:
        original = Path(certifi.where())
    except Exception as exc:  # pragma: no cover - defensive
        print(f"[Fetcher] Failed to locate certifi bundle: {exc}")
        return None

    try:
        str(original).encode("ascii")
        return str(original)
    except UnicodeEncodeError:
        temp_dir = Path(tempfile.gettempdir())
        ascii_copy = temp_dir / "certifi_cacert.pem"
        try:
            if not ascii_copy.exists() or original.stat().st_mtime > ascii_copy.stat().st_mtime:
                shutil.copy2(original, ascii_copy)
            return str(ascii_copy)
        except Exception as exc:
            print(f"[Fetcher] Failed to copy certifi bundle to ASCII path: {exc}")
            return None


CERT_BUNDLE_PATH = _ensure_ascii_cert_path()


@dataclass
class FetchResult:
    """Represents a fetched (and possibly rendered) page."""

    url: str
    html: str
    renderer: str
    degraded: bool = False


class Fetcher:
    """Fetch pages and transparently render dynamic content when needed."""

    def __init__(
        self,
        use_playwright: bool | None = None,
        cookies: Optional[Dict[str, str]] = None,
        proxy: Optional[str] = None,
        auto_render: bool = True,
        render_backends: Optional[Sequence[str]] = None,
        selenium_options: Optional[Dict[str, str]] = None,
    ) -> None:
        # use_playwright is kept for backward-compatibility; default to auto-render.
        if use_playwright is None:
            use_playwright = True

        self.auto_render = auto_render
        self.cookies = cookies or {}
        self.proxy = proxy
        self.selenium_options = selenium_options or {}

        default_backends: Tuple[str, ...] = ("playwright", "selenium") if use_playwright else ()
        self.render_backends: Tuple[str, ...] = tuple(render_backends or default_backends)
        self._cert_bundle = CERT_BUNDLE_PATH
        self._playwright_disabled = False
        self._selenium_disabled = False

    def fetch(self, url: str) -> FetchResult:
        """Fetch page source via static request with automatic render fallback."""
        static_html = ""
        final_url = url
        last_error: Exception | None = None

        try:
            static_html, final_url = self._fetch_static(url)
        except Exception as exc:
            last_error = exc

        needs_render = self.auto_render and self._needs_render(static_html)
        if static_html and not needs_render:
            return FetchResult(url=final_url, html=static_html, renderer="static")

        rendered = None
        if self.auto_render:
            rendered = self._render_with_backends(url)
        if rendered:
            html, rendered_url, backend = rendered
            return FetchResult(url=rendered_url or url, html=html, renderer=backend)

        if static_html:
            return FetchResult(url=final_url, html=static_html, renderer="static", degraded=True)

        if last_error:
            raise last_error

        return FetchResult(url=url, html="", renderer="static", degraded=True)

    # ------------------------------------------------------------------ #
    # Internal helpers
    # ------------------------------------------------------------------ #
    def _fetch_static(self, url: str) -> Tuple[str, str]:
        # Encode URL to handle non-ASCII characters (e.g. Chinese in query params)
        from urllib.parse import quote, urlsplit, urlunsplit
        
        parts = urlsplit(url)
        # Encode path and query, keeping safe characters
        # safe characters for path usually include /
        # safe characters for query usually include = & %
        encoded_path = quote(parts.path, safe="/%")
        encoded_query = quote(parts.query, safe="=&%")
        encoded_url = urlunsplit((parts.scheme, parts.netloc, encoded_path, encoded_query, parts.fragment))

        headers = {
            "Referer": encoded_url,
            "Upgrade-Insecure-Requests": "1",
            "User-Agent": settings.user_agent,
        }
        proxies = {"http": self.proxy, "https": self.proxy} if self.proxy else None

        verify_arg: bool | str = self._cert_bundle or True

        try:
            response = requests.get(
                encoded_url,
                headers=headers,
                cookies=self.cookies,
                proxies=proxies,
                timeout=settings.timeout,
                impersonate="chrome120",
                allow_redirects=True,
                verify=verify_arg,
            )
        except RequestsError as exc:
            message = str(exc).lower()
            if "certificate" in message and "verify" in message and verify_arg is not False:
                print("[Fetcher] TLS verification failed (likely non-ASCII CA path). Retrying insecurely.")
                response = requests.get(
                    encoded_url,
                    headers=headers,
                    cookies=self.cookies,
                    proxies=proxies,
                    timeout=settings.timeout,
                    impersonate="chrome120",
                    allow_redirects=True,
                    verify=False,
                )
            else:
                raise

        if response.status_code == 403:
            print(f"[Fetcher] 403 Forbidden for {url}")
            return "", response.url or url

        response.raise_for_status()
        time.sleep(0.5)  # gentle rate limit

        if "<html" not in response.text.lower():
            print(f"[Fetcher] Warning: unusual response, missing <html> tag for {url}")

        return response.text, response.url or url

    def _render_with_backends(self, url: str) -> Optional[Tuple[str, str, str]]:
        for backend in self.render_backends:
            if backend == "playwright" and self._playwright_disabled:
                continue
            if backend == "selenium" and self._selenium_disabled:
                continue
            if backend == "playwright":
                rendered = self._fetch_with_playwright(url)
            elif backend == "selenium":
                rendered = self._fetch_with_selenium(url)
            else:
                continue

            if rendered and rendered[0]:
                html, final_url = rendered
                return html, final_url or url, backend
        return None

    def _fetch_with_playwright(self, url: str) -> Optional[Tuple[str, str]]:
        if self._playwright_disabled:
            return None
        try:
            from playwright.sync_api import sync_playwright
            import random
        except ImportError:
            print("[Fetcher] Playwright not installed. Run 'pip install playwright' and 'playwright install'.")
            self._playwright_disabled = True
            return None

        try:
            with sync_playwright() as p:
                launch_args = {
                    "headless": True,
                    "args": ["--disable-blink-features=AutomationControlled"],
                }
                if self.proxy:
                    launch_args["proxy"] = {"server": self.proxy}

                browser = p.chromium.launch(**launch_args)
                context = browser.new_context(
                    user_agent=settings.user_agent,
                    viewport={"width": 1920, "height": 1080},
                    locale="zh-CN",
                    timezone_id="Asia/Shanghai",
                )
                context.add_init_script(
                    """
                    Object.defineProperty(navigator, 'webdriver', {
                        get: () => undefined
                    });
                    """
                )

                if self.cookies:
                    from urllib.parse import urlparse

                    parsed = urlparse(url)
                    domain = parsed.hostname or ""
                    if domain and "baidu.com" in domain:
                        domain = ".baidu.com"

                    cookie_list = []
                    for key, value in self.cookies.items():
                        cookie_list.append({"name": key, "value": value, "domain": domain, "path": "/"})
                    context.add_cookies(cookie_list)

                page = context.new_page()
                page.goto(url, wait_until="networkidle", timeout=settings.timeout * 1000)

                try:
                    page.mouse.move(random.randint(100, 400), random.randint(200, 700))
                    page.mouse.wheel(0, random.randint(200, 800))
                except Exception:
                    pass

                time.sleep(1.5)
                content = page.content()
                final_url = page.url
                browser.close()
                return content, final_url
        except Exception as exc:
            print(f"[Fetcher] Playwright fetch error: {exc}")
            message = str(exc).lower()
            if "playwright install" in message or "executable doesn't exist" in message:
                print("[Fetcher] Disabling Playwright backend for this run. Falling back to static fetch.")
                self._playwright_disabled = True
        return None

    def _fetch_with_selenium(self, url: str) -> Optional[Tuple[str, str]]:
        if self._selenium_disabled:
            return None
        try:
            from selenium import webdriver
            from selenium.webdriver.chrome.options import Options
        except ImportError:
            print("[Fetcher] Selenium not installed. Run 'pip install selenium'.")
            self._selenium_disabled = True
            return None

        options = Options()
        options.add_argument("--headless=new")
        options.add_argument("--disable-blink-features=AutomationControlled")
        if self.proxy:
            options.add_argument(f"--proxy-server={self.proxy}")
        for arg in self.selenium_options.get("extra_args", []):
            options.add_argument(arg)

        driver = None
        try:
            driver = webdriver.Chrome(options=options)
            driver.set_page_load_timeout(settings.timeout)
            driver.get(url)
            time.sleep(2.0)
            html = driver.page_source
            final_url = driver.current_url
            return html, final_url
        except Exception as exc:
            print(f"[Fetcher] Selenium fetch error: {exc}")
            self._selenium_disabled = True
            return None
        finally:
            if driver:
                driver.quit()

    @staticmethod
    def _needs_render(html: str) -> bool:
        if not html:
            return True
        sample = html.strip().lower()
        if len(sample) < 800:
            return True
        script_count = sample.count("<script")
        text_block_count = sample.count("<p") + sample.count("<article") + sample.count("<section") + sample.count("<li")
        if "enable javascript" in sample or "requires javascript" in sample:
            return True
        if text_block_count == 0 and script_count > 0:
            return True
        if script_count >= 15 and script_count > text_block_count * 2:
            return True
        if sample.count("var ") > 50 and text_block_count < 3:
            return True
        return False
