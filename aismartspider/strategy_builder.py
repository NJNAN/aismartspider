"""Strategy building orchestration."""

from __future__ import annotations

import json
from typing import Any, Dict, List

from .ai_client import LLMClient
from .ai_prompts import STRATEGY_PROMPT_TEMPLATE
from .models import Intent, PageType, PageTypingResult, Strategy

_DEFAULT_FIELD_SELECTORS: Dict[str, str] = {
    "title": "article h1, h1, h2, .title",
    "content": "article, .article, #content",
    "date": "time, .date, .pub-date",
    "author": ".author, [itemprop='author']",
    "price": ".price, [itemprop='price']",
    "images": ".gallery img, img",
}

_FALLBACK_FIELD_SELECTORS: Dict[str, str] = {
    "title": "meta[property='og:title'], meta[name='title'], title",
    "content": "meta[property='og:description'], .article-content",
    "date": "meta[property='article:published_time'], meta[name='pubdate']",
}


class StrategyBuilder:
    """Use AI to synthesize a Strategy object."""

    def __init__(self, client: LLMClient) -> None:
        self.client = client

    def build(self, typing: PageTypingResult, intent: Intent, dom_summary: str) -> Strategy:
        prompt = STRATEGY_PROMPT_TEMPLATE.format(
            page_type=typing.page_type.value,
            intent_type=intent.intent_type.value,
            requested_fields=intent.requested_fields or [],
            dom_summary=dom_summary,
        )
        messages: List[Dict[str, str]] = [{"role": "user", "content": prompt}]
        model_data = self._call_model(messages)
        heuristic_data = self._heuristic_strategy(typing, intent, dom_summary)
        data = self._merge_strategy_dicts(heuristic_data, model_data)

        return Strategy(
            page_type=typing.page_type,
            intent=intent,
            field_selectors=data.get("field_selectors", {}),
            field_methods=data.get("field_methods", {}),
            is_list=data.get("is_list", False),
            item_link_selector=data.get("item_link_selector"),
            max_depth=data.get("max_depth", 1),
            pagination_selector=data.get("pagination_selector"),
            max_pages=data.get("max_pages", 1),
            image_selector=data.get("image_selector"),
            fallbacks=data.get("fallbacks"),
        )

    def _call_model(self, messages: List[Dict[str, str]]) -> Dict[str, Any]:
        try:
            response = self.client.chat(messages)
            content = response.get("content", "").strip()
            if content.startswith("```"):
                content = content.strip("`")
                if content.startswith("json"):
                    content = content[4:]
                content = content.strip()
            return json.loads(content)
        except Exception:
            return {}

    def _heuristic_strategy(self, typing: PageTypingResult, intent: Intent, dom_summary: str) -> Dict[str, Any]:
        selectors: Dict[str, str] = {}
        field_methods: Dict[str, str] = {}

        requested_fields = intent.requested_fields or typing.suggested_fields or ["title", "content"]
        for field in requested_fields:
            selector = _DEFAULT_FIELD_SELECTORS.get(field, "")
            if selector:
                selectors[field] = selector
                field_methods[field] = "css"

        tag_counts = self._extract_tag_counts(dom_summary)
        is_list = typing.page_type == PageType.LIST or tag_counts.get("li", 0) > 10
        is_gallery = typing.page_type == PageType.GALLERY or tag_counts.get("img", 0) > 5

        item_link_selector = ".list a, .post a, a" if is_list else None
        pagination_selector = ".pagination a.next, a.next, a[rel='next']" if is_list else None

        heuristics = {
            "field_selectors": selectors,
            "field_methods": field_methods,
            "is_list": is_list,
            "item_link_selector": item_link_selector,
            "pagination_selector": pagination_selector,
            "max_pages": 3,
            "max_depth": 2 if is_list else 1,
            "image_selector": ".gallery img, img" if is_gallery else None,
            "fallbacks": {"field_selectors": _FALLBACK_FIELD_SELECTORS},
        }
        return heuristics

    @staticmethod
    def _extract_tag_counts(dom_summary: str) -> Dict[str, int]:
        try:
            summary = json.loads(dom_summary)
            return summary.get("tag_counts", {}) or {}
        except Exception:
            return {}

    @staticmethod
    def _merge_strategy_dicts(base: Dict[str, Any], override: Dict[str, Any]) -> Dict[str, Any]:
        if not override:
            return base
        merged: Dict[str, Any] = dict(base)
        for key, value in override.items():
            if isinstance(value, dict):
                merged[key] = {**base.get(key, {}), **value}
            else:
                merged[key] = value
        return merged
