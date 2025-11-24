"""LLM-powered page type classifier."""

from __future__ import annotations

from typing import List, Dict

from .ai_client import LLMClient
from .ai_prompts import PAGE_TYPE_PROMPT_TEMPLATE
from .models import PageTypingResult, PageType
from .utils.json_utils import extract_json_payload, ensure_string_list


class PageTypeClassifier:
    """Classify DOM summaries into PageType values via LLM prompts."""

    def __init__(self, client: LLMClient) -> None:
        self.client = client

    def classify(self, dom_summary: str) -> PageTypingResult:
        prompt = PAGE_TYPE_PROMPT_TEMPLATE.format(dom_summary=dom_summary)
        messages: List[Dict[str, str]] = [{"role": "user", "content": prompt}]
        response = self.client.chat(messages)
        content = response.get("content", "").strip()

        data = extract_json_payload(content)
        if not isinstance(data, dict):
            data = {}

        return PageTypingResult(
            page_type=self._safe_page_type(data.get("page_type")),
            confidence=self._safe_confidence(data.get("confidence")),
            suggested_fields=ensure_string_list(data.get("suggested_fields")),
        )

    @staticmethod
    def _safe_page_type(value: str | None) -> PageType:
        if not value:
            return PageType.UNKNOWN
        normalized = value.lower()
        aliases = {
            "detail": "news",
            "profile": "news",
            "thread": "forum",
        }
        normalized = aliases.get(normalized, normalized)
        return PageType(normalized) if normalized in PageType._value2member_map_ else PageType.UNKNOWN

    @staticmethod
    def _safe_confidence(value: object) -> float:
        try:
            confidence = float(value)
        except (TypeError, ValueError):
            return 0.0
        if confidence < 0.0:
            return 0.0
        if confidence > 1.0:
            return 1.0
        return confidence
