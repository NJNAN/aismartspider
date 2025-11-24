"""Strategy executor implementations."""

from __future__ import annotations

from itertools import zip_longest
import re
from typing import Any, Dict, List
from urllib.parse import urljoin

from bs4 import BeautifulSoup

from .fetcher import Fetcher, FetchResult
from .models import PageType, Strategy
from .utils.retry import RetryPolicy


class Executor:
    """Execute strategies on target URLs using provided fetcher."""

    def __init__(self, fetcher: Fetcher, retry_policy: RetryPolicy | None = None) -> None:
        self.fetcher = fetcher
        self.retry_policy = retry_policy or RetryPolicy()

    def execute(self, url: str, strategy: Strategy) -> List[Dict[str, Any]]:
        if strategy.page_type == PageType.NEWS:
            return self._run_news_flow(url, strategy)
        if strategy.page_type == PageType.LIST:
            return self._run_list_flow(url, strategy)
        if strategy.page_type == PageType.GALLERY:
            return self._run_gallery_flow(url, strategy)
        return self._run_default_flow(url, strategy)

    def _run_news_flow(self, url: str, strategy: Strategy) -> List[Dict[str, Any]]:
        page = self.retry_policy.run(lambda: self.fetcher.fetch(url))
        if not page.html:
            return []
        soup = BeautifulSoup(page.html, "lxml")
        record = self._extract_fields(soup, strategy, page.url or url)
        return [record]

    def _run_list_flow(self, url: str, strategy: Strategy) -> List[Dict[str, Any]]:
        records: List[Dict[str, Any]] = []
        pages_processed = 0
        next_url: str | None = url
        visited: set[str] = set()

        # Hard limit on pages to prevent infinite loops
        MAX_PAGE_VISITS = 5
        max_pages = min(strategy.max_pages or 1, MAX_PAGE_VISITS)

        while next_url and pages_processed < max_pages:
            target_url = next_url
            page = self.retry_policy.run(lambda target=target_url: self.fetcher.fetch(target))
            current_url = page.url or target_url
            if current_url in visited:
                break
            visited.add(current_url)
            soup = BeautifulSoup(page.html, "lxml")

            new_records = self._extract_list_records(soup, current_url, strategy)
            records.extend(new_records)
            
            if strategy.max_items and len(records) >= strategy.max_items:
                records = records[:strategy.max_items]
                break

            pages_processed += 1
            next_url = self._next_page_url(soup, current_url, strategy.pagination_selector)

        return records or self._run_default_flow(url, strategy)

    def _run_gallery_flow(self, url: str, strategy: Strategy) -> List[Dict[str, Any]]:
        page = self.retry_policy.run(lambda: self.fetcher.fetch(url))
        if not page.html:
            return []
        soup = BeautifulSoup(page.html, "lxml")
        record = self._extract_fields(soup, strategy, page.url or url)
        record["images"] = self._collect_images(soup, strategy.image_selector or "img", page.url or url)
        return [record]

    def _run_default_flow(self, url: str, strategy: Strategy) -> List[Dict[str, Any]]:
        page = self.retry_policy.run(lambda: self.fetcher.fetch(url))
        if not page.html:
            return []
        soup = BeautifulSoup(page.html, "lxml")
        record = self._extract_fields(soup, strategy, page.url or url)
        return [record]

    def _extract_fields(self, soup: BeautifulSoup, strategy: Strategy, base_url: str) -> Dict[str, Any]:
        result: Dict[str, Any] = {}
        fallbacks = (strategy.fallbacks or {}).get("field_selectors", {})
        limits = strategy.field_limits or {}
        global_limit = strategy.max_items

        for field, selector in strategy.field_selectors.items():
            selector = self._sanitize_selector(selector)
            if not selector:
                continue
            method = strategy.field_methods.get(field, "css")
            limit = limits.get(field)
            # Treat 0 as None (no limit specified) so global_limit can apply
            if limit == 0:
                limit = None
            
            if global_limit:
                if limit is None or global_limit < limit:
                    limit = global_limit

            if field in {"sub_comments", "links"} and method.startswith("attr:href"):
                nodes = soup.select(selector)
                # Resolve URLs first, then limit
                value = []
                for node in nodes:
                    href = node.get("href", "").strip()
                    if href and not href.lower().startswith("javascript:"):
                        resolved = self._resolve_url(base_url, href)
                        if resolved:
                            value.append(resolved)
                if limit:
                    value = value[:limit]
            elif field in {"sub_comments", "links", "image", "img", "src", "video"} and method == "css":
                nodes = soup.select(selector)
                if limit:
                    nodes = nodes[:limit]
                value = []
                for node in nodes:
                    # Prefer href for links field
                    if field == "links" and node.name == "a" and node.has_attr("href"):
                        href = node.get("href", "").strip()
                        if href and not href.lower().startswith("javascript:"):
                            resolved = self._resolve_url(base_url, href)
                            value.append(resolved or href)
                            continue
                    # Prefer src for image fields
                    if field in ("image", "img", "src") and node.name == "img" and node.has_attr("src"):
                        src = node.get("src", "").strip()
                        resolved = self._resolve_url(base_url, src)
                        value.append(resolved or src)
                        continue
                    # Prefer src for video fields
                    if field in ("video",) and node.name == "video":
                         src = node.get("src", "").strip()
                         if not src:
                             # Try source children
                             source = node.select_one("source")
                             if source:
                                 src = source.get("src", "").strip()
                         if src:
                             resolved = self._resolve_url(base_url, src)
                             value.append(resolved or src)
                             continue

                    value.append(node.get_text(strip=True))
                
                if limit == 1:
                    value = value[0] if value else ""
            else:
                value = self._extract_with_method(soup, selector, method, base_url)
            
            if not value and field in fallbacks:
                fallback_selector = self._sanitize_selector(fallbacks[field])
                value = self._extract_with_method(soup, fallback_selector, "css", base_url)
            result[field] = value

        if strategy.primary_image_field:
            result[strategy.primary_image_field] = self._extract_primary_image(
                soup,
                strategy.primary_image_selector,
                base_url,
            )
        return result

    def _extract_with_method(self, soup: BeautifulSoup, selector: str, method: str, base_url: str) -> str:
        selector = self._sanitize_selector(selector)
        if not selector:
            return ""
        try:
            if method.startswith("attr:"):
                attr = method.split(":", 1)[1]
                node = soup.select_one(selector)
                if not node:
                    return ""
                value = node.get(attr, "").strip()
                if attr in {"href", "src"}:
                    return self._resolve_url(base_url, value) or value
                return value
            if method == "text":
                node = soup.select_one(selector)
                return node.get_text(strip=True) if node else ""
            # default css
            node = soup.select_one(selector)
            return node.get_text(strip=True) if node else ""
        except Exception:
            return ""

    def _extract_list_records(self, soup: BeautifulSoup, base_url: str, strategy: Strategy) -> List[Dict[str, Any]]:
        if self._sanitize_selector(strategy.item_link_selector):
            return self._follow_detail_links(soup, base_url, strategy)
        return self._extract_inline_list(soup, strategy, base_url)

    def _follow_detail_links(self, soup: BeautifulSoup, base_url: str, strategy: Strategy) -> List[Dict[str, Any]]:
        records: List[Dict[str, Any]] = []
        selector = self._sanitize_selector(strategy.item_link_selector)
        links = soup.select(selector) if selector else []
        max_items = max(1, strategy.max_depth or 1)
        for link in links[:max_items]:
            href = link.get("href")
            target = self._resolve_url(base_url, href)
            if not target:
                continue
            detail_page = self.retry_policy.run(lambda target_url=target: self.fetcher.fetch(target_url))
            detail_soup = BeautifulSoup(detail_page.html, "lxml")
            detail_url = detail_page.url or target
            records.append(self._extract_fields(detail_soup, strategy, detail_url))
        return records

    def _extract_inline_list(self, soup: BeautifulSoup, strategy: Strategy, base_url: str | None = None) -> List[Dict[str, Any]]:
        columns: Dict[str, List[Any]] = {}
        limits = strategy.field_limits or {}
        global_limit = strategy.max_items

        for field, selector in strategy.field_selectors.items():
            selector = self._sanitize_selector(selector)
            if not selector:
                continue
            nodes = soup.select(selector)
            limit = limits.get(field)
            # Treat 0 as None (no limit specified) so global_limit can apply
            if limit == 0:
                limit = None
            
            if global_limit:
                if limit is None or global_limit < limit:
                    limit = global_limit
            
            method = strategy.field_methods.get(field, "css")
            values: List[str] = []
            for node in nodes:
                if method.startswith("attr:"):
                    attr = method.split(":", 1)[1]
                    val = node.get(attr, "").strip()
                    if attr == "href":
                        if val.lower().startswith("javascript:"):
                            continue
                        if base_url:
                            val = self._resolve_url(base_url, val) or val
                    elif attr == "src" and base_url:
                        val = self._resolve_url(base_url, val) or val
                    values.append(val)
                elif method == "text":
                    values.append(node.get_text(strip=True))
                else:
                    # Default CSS behavior
                    # Auto-detect link intent
                    if field in ("links", "link", "url", "urls") and node.name == "a" and node.has_attr("href"):
                        val = node.get("href", "").strip()
                        if not val.lower().startswith("javascript:"):
                             if base_url:
                                 val = self._resolve_url(base_url, val) or val
                             values.append(val)
                             continue
                    # Auto-detect image intent
                    if field in ("image", "img", "src") and node.name == "img" and node.has_attr("src"):
                        val = node.get("src", "").strip()
                        if base_url:
                            val = self._resolve_url(base_url, val) or val
                        values.append(val)
                        continue
                    
                    values.append(node.get_text(strip=True))
            
            if limit:
                values = values[:limit]
            columns[field] = values
        
        if not columns:
            return []

        keys = list(columns.keys())
        # Special-case list aggregation fields to keep them as arrays
        if keys == ["links"]:
            return [{"links": columns["links"]}]
        if keys == ["sub_comments"]:
            return [{"sub_comments": columns["sub_comments"]}]

        values = [columns[k] for k in keys]
        
        records: List[Dict[str, Any]] = []
        for row in zip_longest(*values, fillvalue=""):
            record = dict(zip(keys, row))
            records.append(record)
        return records

    def _collect_images(self, soup: BeautifulSoup, selector: str, base_url: str) -> List[str]:
        results: List[str] = []
        selector = self._sanitize_selector(selector)
        for img in soup.select(selector):
            src = img.get("src", "").strip()
            if not src:
                continue
            resolved = self._resolve_url(base_url, src) or src
            results.append(resolved)
        return results

    def _extract_primary_image(
        self,
        soup: BeautifulSoup,
        selector: str | None,
        base_url: str,
    ) -> Any:
        selector = self._sanitize_selector(selector)
        if not selector:
            return None
        try:
            node = soup.select_one(selector)
        except Exception:
            node = None
        if not node:
            return None
        src = node.get("src", "").strip()
        if not src:
            return None
        return self._resolve_url(base_url, src) or src

    @staticmethod
    def _resolve_url(base_url: str, href: str | None) -> str | None:
        if not href:
            return None
        return urljoin(base_url, href)

    @staticmethod
    def _next_page_url(soup: BeautifulSoup, base_url: str, selector: str | None) -> str | None:
        selector = Executor._sanitize_selector(selector)
        if not selector:
            return None
        node = soup.select_one(selector)
        if not node:
            return None
        return Executor._resolve_url(base_url, node.get("href"))

    @staticmethod
    def _sanitize_selector(selector: str | None) -> str:
        if not selector:
            return ""
        return _CONTAINS_RE.sub(":-soup-contains", selector)


_CONTAINS_RE = re.compile(r":contains(?=\s*\()")
