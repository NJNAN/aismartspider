"""Natural language intent parsing."""

from __future__ import annotations

import re
from typing import Dict, List, Optional

from .ai_client import LLMClient
from .ai_prompts import INTENT_PROMPT_TEMPLATE
from .models import Intent, IntentType
from .utils.json_utils import extract_json_payload, ensure_string_list


_FIELD_HINTS: Dict[str, List[str]] = {
    "title": ["title", "\u6807\u9898", "\u9898\u76ee"],
    "content": ["content", "\u6b63\u6587", "\u5185\u5bb9", "\u8be6\u60c5", "description"],
    "date": ["date", "time", "\u65f6\u95f4", "\u65e5\u671f"],
    "author": ["author", "\u4f5c\u8005", "\u53d1\u5e03\u8005"],
    "price": ["price", "\u4ef7\u683c", "\u4ef7\u94b1"],
    "images": ["image", "photo", "\u56fe\u7247", "\u914d\u56fe"],
    "links": ["link", "url", "\u94fe\u63a5", "\u8df3\u8f6c"],
    "name": ["name", "\u7528\u6237\u540d", "\u6635\u79f0"],
    "follows": ["followers", "fans", "\u7c89\u4e1d", "\u5173\u6ce8"],
    "answer": ["answer", "\u56de\u7b54", "\u56de\u590d"],
    "sub_comments": ["sub comment", "reply", "\u697c\u4e2d\u697c", "\u8bc4\u8bba"],
}

_INTENT_HINTS: Dict[IntentType, List[str]] = {
    IntentType.CRAWL_LIST: ["list", "\u5217\u8868", "\u591a\u6761", "\u5206\u9875", "top"],
    IntentType.DOWNLOAD_IMAGES: ["image", "\u56fe\u7247", "\u56fe\u96c6", "\u4e0b\u8f7d\u56fe"],
    IntentType.CRAWL_DETAIL: ["detail", "\u8be6\u60c5", "\u9012\u5f52", "\u6df1\u5ea6"],
}
class IntentParser:
    """Parse user text into structured Intent objects."""

    def __init__(self, client: LLMClient) -> None:
        self.client = client

    def parse(self, user_text: str) -> Intent:
        prompt = INTENT_PROMPT_TEMPLATE.format(user_text=user_text)
        messages: List[Dict[str, str]] = [{"role": "user", "content": prompt}]
        data = self._call_model(messages)
        heuristics = self._heuristic_parse(user_text)

        model_intent = self._safe_intent_type(data.get("intent_type")) if data else None
        if model_intent and model_intent != IntentType.OTHER:
            intent_type = model_intent
        else:
            intent_type = heuristics["intent_type"]

        requested_fields = self._merge_fields(
            data.get("requested_fields") if data else None,
            heuristics["requested_fields"],
        )
        max_items = self._parse_limit(user_text)

        return Intent(
            intent_type=intent_type,
            requested_fields=requested_fields,
            raw_text=user_text,
            max_items=max_items,
        )

    @staticmethod
    def _parse_limit(user_text: str) -> Optional[int]:
        # Match "前10", "Top 10" (most specific and common for limits)
        m = re.search(r'(?:前|top)\s*(\d+)', user_text, re.IGNORECASE)
        if m:
            return int(m.group(1))

        # Match "10个", "10条", "10章" etc.
        m = re.search(r'(\d+)\s*(?:个|条|篇|章|项|links?)', user_text, re.IGNORECASE)
        if m:
            return int(m.group(1))
            
        return None

    def _call_model(self, messages: List[Dict[str, str]]) -> Dict[str, List[str] | str]:
        try:
            response = self.client.chat(messages)
            payload = extract_json_payload(response.get("content", ""))
        except Exception:
            return {}
        if not isinstance(payload, dict):
            return {}
        requested = ensure_string_list(payload.get("requested_fields"))
        # Deduplicate while preserving order
        seen: set[str] = set()
        deduped: List[str] = []
        for field in requested:
            if field not in seen:
                deduped.append(field)
                seen.add(field)
        return {
            "intent_type": payload.get("intent_type"),
            "requested_fields": deduped,
        }

    def _heuristic_parse(self, user_text: str) -> Dict[str, Optional[List[str]] | IntentType]:
        lowered = user_text.lower()
        intent_type = IntentType.EXTRACT_INFO
        for candidate, markers in _INTENT_HINTS.items():
            if any(marker.lower() in lowered for marker in markers):
                intent_type = candidate
                break

        requested_fields: List[str] = []
        for field, hints in _FIELD_HINTS.items():
            if any(hint.lower() in lowered for hint in hints):
                requested_fields.append(field)

        return {
            "intent_type": intent_type,
            "requested_fields": requested_fields or None,
        }

    @staticmethod
    def _safe_intent_type(value: Optional[str]) -> IntentType:
        if not value:
            return IntentType.OTHER
        normalized = value.lower()
        return IntentType(normalized) if normalized in IntentType._value2member_map_ else IntentType.OTHER

    @staticmethod
    def _merge_fields(model_fields: Optional[List[str]], heuristic_fields: Optional[List[str]]) -> Optional[List[str]]:
        ordered: List[str] = []

        def append_unique(values: Optional[List[str]]) -> None:
            if not values:
                return
            for value in values:
                if value and value not in ordered:
                    ordered.append(value)

        append_unique(model_fields)
        append_unique(heuristic_fields)
        return ordered or None
