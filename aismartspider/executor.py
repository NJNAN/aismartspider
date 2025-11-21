"""Strategy executor implementations."""

from __future__ import annotations

from itertools import zip_longest
from typing import Dict, List
from urllib.parse import urljoin

from bs4 import BeautifulSoup

from .fetcher import Fetcher
from .models import PageType, Strategy
from .utils.retry import RetryPolicy


class Executor:
    """Execute strategies on target URLs using provided fetcher."""

    def __init__(self, fetcher: Fetcher, retry_policy: RetryPolicy | None = None) -> None:
        self.fetcher = fetcher
        self.retry_policy = retry_policy or RetryPolicy()

    def execute(self, url: str, strategy: Strategy) -> List[Dict[str, str]]:
        if strategy.page_type == PageType.NEWS:
            return self._run_news_flow(url, strategy)
        if strategy.page_type == PageType.LIST:
            return self._run_list_flow(url, strategy)
        if strategy.page_type == PageType.GALLERY:
            return self._run_gallery_flow(url, strategy)
        return self._run_default_flow(url, strategy)

    def _run_news_flow(self, url: str, strategy: Strategy) -> List[Dict[str, str]]:
        html = self.retry_policy.run(lambda: self.fetcher.fetch(url))
        soup = BeautifulSoup(html, "lxml")
        record = self._extract_fields(soup, strategy)
        return [record]

    def _run_list_flow(self, url: str, strategy: Strategy) -> List[Dict[str, str]]:
        records: List[Dict[str, str]] = []
        pages_processed = 0
        next_url: str | None = url
        visited: set[str] = set()

        while next_url and pages_processed < max(1, strategy.max_pages or 1):
            if next_url in visited:
                break
            visited.add(next_url)
            html = self.retry_policy.run(lambda target=next_url: self.fetcher.fetch(target))
            soup = BeautifulSoup(html, "lxml")
            records.extend(self._extract_list_records(soup, next_url, strategy))
            pages_processed += 1
            next_url = self._next_page_url(soup, next_url, strategy.pagination_selector)

        return records or self._run_default_flow(url, strategy)

    def _run_gallery_flow(self, url: str, strategy: Strategy) -> List[Dict[str, str]]:
        html = self.retry_policy.run(lambda: self.fetcher.fetch(url))
        soup = BeautifulSoup(html, "lxml")
        record = self._extract_fields(soup, strategy)
        record["images"] = self._collect_images(soup, strategy.image_selector or "img")
        return [record]

    def _run_default_flow(self, url: str, strategy: Strategy) -> List[Dict[str, str]]:
        html = self.retry_policy.run(lambda: self.fetcher.fetch(url))
        soup = BeautifulSoup(html, "lxml")
        record = self._extract_fields(soup, strategy)
        return [record]

    def _extract_fields(self, soup: BeautifulSoup, strategy: Strategy) -> Dict[str, str]:
        result: Dict[str, str] = {}
        fallbacks = (strategy.fallbacks or {}).get("field_selectors", {})
        for field, selector in strategy.field_selectors.items():
            method = strategy.field_methods.get(field, "css")
            if field in {"sub_comments", "links"} and method.startswith("attr:href"):
                nodes = soup.select(selector)
                value = [node.get("href", "").strip() for node in nodes if node.get("href")]
            elif field in {"sub_comments", "links"} and method == "css":
                nodes = soup.select(selector)
                value = [node.get_text(strip=True) for node in nodes]
            else:
                value = self._extract_with_method(soup, selector, method)
            if not value and field in fallbacks:
                value = self._extract_with_method(soup, fallbacks[field], "css")
            result[field] = value
        return result

    def _extract_with_method(self, soup: BeautifulSoup, selector: str, method: str) -> str:
        if not selector:
            return ""
        try:
            if method.startswith("attr:"):
                attr = method.split(":", 1)[1]
                node = soup.select_one(selector)
                return node.get(attr, "").strip() if node else ""
            if method == "text":
                node = soup.select_one(selector)
                return node.get_text(strip=True) if node else ""
            # default css
            node = soup.select_one(selector)
            return node.get_text(strip=True) if node else ""
        except Exception:
            return ""

    def _extract_list_records(self, soup: BeautifulSoup, base_url: str, strategy: Strategy) -> List[Dict[str, str]]:
        if strategy.item_link_selector:
            return self._follow_detail_links(soup, base_url, strategy)
        return self._extract_inline_list(soup, strategy)

    def _follow_detail_links(self, soup: BeautifulSoup, base_url: str, strategy: Strategy) -> List[Dict[str, str]]:
        records: List[Dict[str, str]] = []
        links = soup.select(strategy.item_link_selector)
        max_items = max(1, strategy.max_depth or 1)
        for link in links[:max_items]:
            href = link.get("href")
            target = self._resolve_url(base_url, href)
            if not target:
                continue
            detail_html = self.retry_policy.run(lambda target_url=target: self.fetcher.fetch(target_url))
            detail_soup = BeautifulSoup(detail_html, "lxml")
            records.append(self._extract_fields(detail_soup, strategy))
        return records

    def _extract_inline_list(self, soup: BeautifulSoup, strategy: Strategy) -> List[Dict[str, str]]:
        columns: Dict[str, List[str]] = {}
        for field, selector in strategy.field_selectors.items():
            nodes = soup.select(selector)
            method = strategy.field_methods.get(field, "css")
            values: List[str] = []
            for node in nodes:
                if method.startswith("attr:"):
                    attr = method.split(":", 1)[1]
                    values.append(node.get(attr, "").strip())
                elif method == "text":
                    values.append(node.get_text(strip=True))
                else:
                    values.append(node.get_text(strip=True))
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
        
        records: List[Dict[str, str]] = []
        for row in zip_longest(*values, fillvalue=""):
            record = dict(zip(keys, row))
            records.append(record)
        return records

    def _collect_images(self, soup: BeautifulSoup, selector: str) -> List[str]:
        return [img.get("src", "") for img in soup.select(selector) if img.get("src")]

    @staticmethod
    def _resolve_url(base_url: str, href: str | None) -> str | None:
        if not href:
            return None
        return urljoin(base_url, href)

    @staticmethod
    def _next_page_url(soup: BeautifulSoup, base_url: str, selector: str | None) -> str | None:
        if not selector:
            return None
        node = soup.select_one(selector)
        if not node:
            return None
        return Executor._resolve_url(base_url, node.get("href"))
