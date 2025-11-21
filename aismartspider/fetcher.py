"""HTTP fetching and optional rendering utilities."""

from __future__ import annotations

from typing import Optional, Dict
import time

from curl_cffi import requests

from .config import settings


class Fetcher:
    """Simple fetcher with optional Playwright rendering hook."""

    def __init__(self, use_playwright: bool = False, cookies: Optional[Dict[str, str]] = None, proxy: Optional[str] = None) -> None:
        self.use_playwright = use_playwright
        self.cookies = cookies or {}
        self.proxy = proxy

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
        # Let curl_cffi handle most headers to ensure consistency with the TLS fingerprint
        # We only set basic ones.
        headers = {
            "Referer": "https://tieba.baidu.com/",
            "Upgrade-Insecure-Requests": "1",
        }
        proxies = {"http": self.proxy, "https": self.proxy} if self.proxy else None
        
        # Debug: Print cookies to ensure they are passed correctly
        # print(f"DEBUG: Sending cookies: {list(self.cookies.keys())}")
        
        try:
            response = requests.get(
                url, 
                headers=headers, 
                cookies=self.cookies, 
                proxies=proxies, 
                timeout=settings.timeout,
                impersonate="chrome120", # Use a specific version for stability
                allow_redirects=False
            )
            
            if response.status_code in (301, 302, 303, 307, 308):
                location = response.headers.get('Location')
                print(f"DEBUG: Redirect detected for {url}")
                print(f"DEBUG: Location: {location}")
                if "passport.baidu.com" in location or "login" in location:
                    print("DEBUG: !!! LOGIN REQUIRED - YOUR BDUSS COOKIE IS EXPIRED OR INVALID !!!")
                return ""

            if response.status_code == 403:
                print(f"DEBUG: 403 Forbidden for {url}")
                # print(f"DEBUG: Response headers: {response.headers}")
                return ""

            time.sleep(0.5)  # Prevent rate limiting
            response.raise_for_status()
            
            # Degradation detection
            if "<html" not in response.text.lower():
                print(f"Warning: Possible degradation detected for {url} (no <html> tag)")
                
            return response.text
        except Exception:
            # Let the caller decide whether to suppress or not, but here we just raise
            # actually, to make the logic in fetch() cleaner, let's re-raise
            raise

    def _fetch_with_playwright(self, url: str) -> Optional[str]:
        try:
            from playwright.sync_api import sync_playwright
            import random
        except ImportError:
            print("Playwright not installed. Please run 'pip install playwright' and 'playwright install'.")
            return None

        try:
            with sync_playwright() as p:
                launch_args = {
                    "headless": True,
                    "args": ["--disable-blink-features=AutomationControlled"]
                }
                if self.proxy:
                    launch_args["proxy"] = {"server": self.proxy}
                
                browser = p.chromium.launch(**launch_args)
                
                # Create a new context with specific user agent if needed
                context = browser.new_context(
                    user_agent=settings.user_agent,
                    viewport={"width": 1920, "height": 1080},
                    locale="zh-CN",
                    timezone_id="Asia/Shanghai"
                )
                
                # Stealth: Hide webdriver property
                context.add_init_script("""
                    Object.defineProperty(navigator, 'webdriver', {
                        get: () => undefined
                    });
                """)
                
                if self.cookies:
                    from urllib.parse import urlparse
                    parsed = urlparse(url)
                    domain = parsed.hostname
                    # If it's a baidu subdomain, set cookies for .baidu.com to ensure they work across subdomains
                    if domain and "baidu.com" in domain:
                        domain = ".baidu.com"
                    
                    cookie_list = []
                    for k, v in self.cookies.items():
                        cookie_list.append({"name": k, "value": v, "domain": domain, "path": "/"})
                    context.add_cookies(cookie_list)

                page = context.new_page()

                # Wait for network idle to ensure dynamic content is loaded
                page.goto(url, wait_until="domcontentloaded", timeout=settings.timeout * 1000)
                
                # Simulate human behavior
                try:
                    page.mouse.move(random.randint(100, 500), random.randint(100, 500))
                    page.mouse.down()
                    time.sleep(random.uniform(0.1, 0.3))
                    page.mouse.move(random.randint(100, 500), random.randint(100, 500))
                    page.mouse.up()
                    page.evaluate("window.scrollBy(0, 300)")
                except Exception:
                    pass
                
                # Random delay to mimic human reading/loading
                time.sleep(random.uniform(1.5, 3.0))
                
                content = page.content()
                browser.close()
                return content
        except Exception as e:
            print(f"Playwright fetch error: {e}")
            return None
