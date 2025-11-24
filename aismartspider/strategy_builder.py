"""Strategy building orchestration."""

from __future__ import annotations

import json
from typing import Any, Dict, List, Optional

from .ai_client import LLMClient
from .ai_prompts import STRATEGY_PROMPT_TEMPLATE, FIRST_IMAGE_PROMPT_TEMPLATE
from .models import Intent, PageType, PageTypingResult, Strategy
from .utils.json_utils import extract_json_payload, ensure_mapping

_DEFAULT_FIELD_SELECTORS: Dict[str, str] = {
    "title": "article h1, h1, h2, .title",
    "content": "article, .article, #content",
    "date": "time, .date, .pub-date",
    "author": ".author, [itemprop='author']",
    "price": ".price, [itemprop='price']",
    "images": ".gallery img, img",
    "links": "a",
    "name": ".name, .username, h1",
    "follows": ".follows, .follow-count, .fans",
    "sub_comments": ".sub-comment, .lzl_content, .subcomment",
    "answer": ".answer, .post-content, article",
}

_FALLBACK_FIELD_SELECTORS: Dict[str, str] = {
    "title": "meta[property='og:title'], meta[name='title'], title",
    "content": "meta[property='og:description'], .article-content",
    "date": "meta[property='article:published_time'], meta[name='pubdate']",
}

_PRIMARY_IMAGE_FIELD_MARKERS = {
    "image",
    "image_url",
    "imageurl",
    "cover",
    "first_image",
    "hero_image",
    "thumbnail",
}

_SELECTOR_INVALID = object()


class StrategyBuilder:
    """Use AI to synthesize a Strategy object."""

    def __init__(self, client: LLMClient) -> None:
        self.client = client

    def build(self, typing: PageTypingResult, intent: Intent, dom_summary: str) -> Strategy:
        primary_image_field = self._detect_primary_image_field(intent.requested_fields)
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
        primary_image_selector: Optional[str] = None

        if intent.requested_fields:
            allowed = set(intent.requested_fields)
            data["field_selectors"] = {k: v for k, v in data.get("field_selectors", {}).items() if k in allowed}
            data["field_methods"] = {k: v for k, v in data.get("field_methods", {}).items() if k in allowed}

        if primary_image_field:
            # Remove direct extraction of the image field from AI/heuristics results
            data.get("field_selectors", {}).pop(primary_image_field, None)
            data.get("field_methods", {}).pop(primary_image_field, None)
            if "field_limits" in data and isinstance(data["field_limits"], dict):
                data["field_limits"].pop(primary_image_field, None)
            primary_image_selector = self._build_primary_image_selector(
                typing,
                intent,
                dom_summary,
                primary_image_field,
            )
            if primary_image_selector is _SELECTOR_INVALID:
                primary_image_selector = self._fallback_primary_image_selector()

        strategy = Strategy(
            page_type=typing.page_type,
            intent=intent,
            field_selectors=data.get("field_selectors", {}),
            field_methods=data.get("field_methods", {}),
            is_list=data.get("is_list", False),
            item_link_selector=data.get("item_link_selector"),
            max_depth=data.get("max_depth", 1),
            pagination_selector=data.get("pagination_selector"),
            max_pages=data.get("max_pages", 1),
            max_items=intent.max_items,
            image_selector=data.get("image_selector"),
            primary_image_field=primary_image_field,
            primary_image_selector=primary_image_selector if primary_image_selector is not _SELECTOR_INVALID else None,
            field_limits=data.get("field_limits"),
            fallbacks=data.get("fallbacks"),
        )

        # Heuristic: if max_items is set and small, limit max_pages to avoid over-crawling
        if strategy.max_items and strategy.max_items <= 20:
            strategy.max_pages = 1
            
        return strategy

    def _call_model(self, messages: List[Dict[str, str]]) -> Dict[str, Any]:
        try:
            response = self.client.chat(messages)
            payload = extract_json_payload(response.get("content", ""))
        except Exception:
            return {}
        if not isinstance(payload, dict):
            return {}

        cleaned: Dict[str, Any] = {}
        selectors = ensure_mapping(payload.get("field_selectors"))
        methods = ensure_mapping(payload.get("field_methods"))
        limits = self._ensure_int_mapping(payload.get("field_limits"))

        if selectors:
            cleaned["field_selectors"] = selectors
        if methods:
            cleaned["field_methods"] = methods
        if limits:
            cleaned["field_limits"] = limits

        for key in ("item_link_selector", "pagination_selector", "image_selector"):
            if key in payload and isinstance(payload.get(key), str):
                cleaned[key] = payload[key].strip() or None

        if "is_list" in payload:
            cleaned["is_list"] = self._as_bool(payload.get("is_list"))
        if "max_depth" in payload:
            cleaned["max_depth"] = self._as_positive_int(payload.get("max_depth"))
        if "max_pages" in payload:
            cleaned["max_pages"] = self._as_positive_int(payload.get("max_pages"))

        if "fallbacks" in payload and isinstance(payload.get("fallbacks"), dict):
            cleaned["fallbacks"] = payload["fallbacks"]

        return cleaned

    def _heuristic_strategy(self, typing: PageTypingResult, intent: Intent, dom_summary: str) -> Dict[str, Any]:
        selectors: Dict[str, str] = {}
        field_methods: Dict[str, str] = {}

        requested_fields = intent.requested_fields or typing.suggested_fields or ["title", "content"]
        for field in requested_fields:
            selector = _DEFAULT_FIELD_SELECTORS.get(field, "")
            if selector:
                selectors[field] = selector
                field_methods[field] = "attr:href" if field == "links" else "css"

        tag_counts = self._extract_tag_counts(dom_summary)
        is_list = typing.page_type == PageType.LIST or tag_counts.get("li", 0) > 10
        is_gallery = typing.page_type == PageType.GALLERY or tag_counts.get("img", 0) > 5

        wants_links = "links" in requested_fields
        item_link_selector = None if wants_links else (".list a, .post a, a" if is_list else None)
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

    @staticmethod
    def _ensure_int_mapping(value: Any) -> Dict[str, int]:
        if not isinstance(value, dict):
            return {}
        cleaned: Dict[str, int] = {}
        for key, val in value.items():
            if not isinstance(key, str):
                continue
            try:
                intval = int(val)
            except (TypeError, ValueError):
                continue
            if intval < 0:
                continue
            cleaned[key] = intval
        return cleaned

    @staticmethod
    def _as_bool(value: Any) -> bool:
        if isinstance(value, bool):
            return value
        if isinstance(value, str):
            return value.strip().lower() in {"1", "true", "yes"}
        if isinstance(value, (int, float)):
            return bool(value)
        return False

    @staticmethod
    def _as_positive_int(value: Any) -> int:
        try:
            intval = int(value)
        except (TypeError, ValueError):
            return 0
        return max(0, intval)

    @staticmethod
    def _detect_primary_image_field(fields: Optional[List[str]]) -> Optional[str]:
        if not fields:
            return None
        for field in fields:
            normalized = field.replace("-", "_").lower()
            if normalized in _PRIMARY_IMAGE_FIELD_MARKERS:
                return field
        return None

    def _build_primary_image_selector(
        self,
        typing: PageTypingResult,
        intent: Intent,
        dom_summary: str,
        field_name: str,
        retries: int = 3,
    ) -> Any:
        prompt = FIRST_IMAGE_PROMPT_TEMPLATE.format(
            page_type=typing.page_type.value,
            task=intent.raw_text,
            field_name=field_name,
            dom_summary=dom_summary,
        )
        messages = [{"role": "user", "content": prompt}]
        for _ in range(retries):
            try:
                response = self.client.chat(
                    messages,
                    temperature=0,
                    top_p=1,
                    response_format={"type": "json_object"},
                )
            except Exception:
                continue
            payload = extract_json_payload(response.get("content", ""))
            parsed = self._parse_primary_image_payload(payload)
            if parsed is not _SELECTOR_INVALID:
                return parsed
        return _SELECTOR_INVALID

    @staticmethod
    def _parse_primary_image_payload(payload: Any) -> Any:
        if not isinstance(payload, dict) or "selector" not in payload:
            return _SELECTOR_INVALID
        selector = payload.get("selector")
        if selector is None:
            return None
        if isinstance(selector, str):
            stripped = selector.strip()
            return stripped or None
        return _SELECTOR_INVALID

    @staticmethod
    def _fallback_primary_image_selector() -> str:
        return "article img, main img, section img, #content img, .article img, img"
