"""LLM-powered page type classifier."""

from __future__ import annotations

import json
from typing import List, Dict

from .ai_client import LLMClient
from .ai_prompts import PAGE_TYPE_PROMPT_TEMPLATE
from .models import PageTypingResult, PageType


class PageTypeClassifier:
    """Classify DOM summaries into PageType values via LLM prompts."""

    def __init__(self, client: LLMClient) -> None:
        self.client = client

    def classify(self, dom_summary: str) -> PageTypingResult:
        prompt = PAGE_TYPE_PROMPT_TEMPLATE.format(dom_summary=dom_summary)
        messages: List[Dict[str, str]] = [{"role": "user", "content": prompt}]
        response = self.client.chat(messages)
        content = response.get("content", "").strip()
        
        # Remove markdown code blocks if present (e.g. ```json ... ```)
        if content.startswith("```"):
            content = content.strip("`")
            if content.startswith("json"):
                content = content[4:]
            content = content.strip()
            
        try:
            data = json.loads(content)
        except json.JSONDecodeError:
            # Fallback: try to find JSON object in text
            start = content.find("{")
            end = content.rfind("}")
            if start != -1 and end != -1:
                try:
                    data = json.loads(content[start : end + 1])
                except json.JSONDecodeError:
                    data = {}
            else:
                data = {}

        return PageTypingResult(
            page_type=self._safe_page_type(data.get("page_type")),
            confidence=float(data.get("confidence", 0.0)),
            suggested_fields=data.get("suggested_fields"),
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
