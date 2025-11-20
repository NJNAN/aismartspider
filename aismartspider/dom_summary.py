"""DOM summary generation helpers."""

from __future__ import annotations

import json
from collections import Counter
from typing import Any, Dict, List

from bs4 import BeautifulSoup, Tag


class DomSummarizer:
    """Generate compact JSON summaries from HTML."""

    def __init__(self, max_text_nodes: int = 60, max_links: int = 20, max_lists: int = 6) -> None:
        self.max_text_nodes = max_text_nodes
        self.max_links = max_links
        self.max_lists = max_lists

    def summarize(self, html: str) -> str:
        """Convert DOM to a lightweight JSON string for LLM consumption."""
        soup = BeautifulSoup(html, "lxml")
        
        # Remove script and style elements to reduce noise
        for script in soup(["script", "style", "noscript", "iframe", "svg"]):
            script.decompose()

        title = soup.title.get_text(strip=True) if soup.title else ""
        meta = self._extract_meta(soup)
        
        # Extract potential content containers (with class/id hints)
        structure_hints = self._extract_structure_hints(soup)
        
        headings = self._collect_texts(soup, ["h1", "h2", "h3"], limit=self.max_text_nodes // 3 or 1)
        paragraphs = self._collect_texts(soup, ["p"], limit=self.max_text_nodes)
        links = self._collect_links(soup)
        lists = self._collect_lists(soup)
        tag_counts = self._collect_tag_counts(soup)

        summary: Dict[str, Any] = {
            "title": title,
            "meta": meta,
            "structure_hints": structure_hints, # New field to help AI find selectors
            "headings": headings,
            "paragraphs": paragraphs,
            "links": links,
            "lists": lists,
            "tag_counts": tag_counts,
        }
        return json.dumps(summary, ensure_ascii=False)

    def _extract_structure_hints(self, soup: BeautifulSoup) -> List[Dict[str, str]]:
        """Find potential main content containers and return their attributes."""
        hints = []
        # Look for common content wrappers
        candidates = soup.find_all(["article", "div", "section", "main"])
        for tag in candidates:
            classes = tag.get("class", [])
            if isinstance(classes, list):
                classes = " ".join(classes)
            ids = tag.get("id", "")
            
            score = 0
            # Simple heuristic to find "interesting" containers
            keywords = ["content", "article", "post", "body", "detail", "news", "main"]
            combined = (str(classes) + " " + str(ids)).lower()
            
            if any(k in combined for k in keywords):
                # Get a snippet of text to help AI verify
                text_snippet = tag.get_text(strip=True)[:100]
                if len(text_snippet) > 20:
                    hints.append({
                        "tag": tag.name,
                        "class": classes,
                        "id": ids,
                        "text_snippet": text_snippet
                    })
            
            if len(hints) >= 10:
                break
        return hints


    @staticmethod
    def _extract_meta(soup: BeautifulSoup) -> Dict[str, str]:
        description = soup.find("meta", attrs={"name": "description"})
        keywords = soup.find("meta", attrs={"name": "keywords"})
        return {
            "description": description["content"].strip() if description and description.has_attr("content") else "",
            "keywords": keywords["content"].strip() if keywords and keywords.has_attr("content") else "",
        }

    @staticmethod
    def _collect_texts(soup: BeautifulSoup, tags: List[str], limit: int) -> List[str]:
        results: List[str] = []
        for node in soup.find_all(tags):
            text = node.get_text(strip=True)
            if text:
                results.append(text)
            if len(results) >= limit:
                break
        return results

    def _collect_links(self, soup: BeautifulSoup) -> List[Dict[str, str]]:
        results: List[Dict[str, str]] = []
        for node in soup.find_all("a"):
            href = node.get("href") or ""
            text = node.get_text(strip=True)
            if href or text:
                results.append({"href": href, "text": text})
            if len(results) >= self.max_links:
                break
        return results

    def _collect_lists(self, soup: BeautifulSoup) -> List[Dict[str, Any]]:
        lists: List[Dict[str, Any]] = []
        for list_tag in soup.find_all(["ul", "ol"]):
            items = []
            for li in list_tag.find_all("li"):
                text = li.get_text(strip=True)
                if text:
                    items.append(text)
                if len(items) >= 10:
                    break
            if items:
                lists.append({"type": list_tag.name, "items": items})
            if len(lists) >= self.max_lists:
                break
        return lists

    @staticmethod
    def _collect_tag_counts(soup: BeautifulSoup) -> Dict[str, int]:
        interesting = ["div", "article", "section", "li", "img", "a", "table"]
        counter: Counter[str] = Counter()
        for tag in soup.find_all(interesting):  # type: ignore[arg-type]
            if isinstance(tag, Tag):
                counter[tag.name] += 1
        return dict(counter)
