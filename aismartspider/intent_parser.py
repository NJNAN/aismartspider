"""Natural language intent parsing."""

from __future__ import annotations

import json
import re
from typing import Dict, List, Optional

from .ai_client import LLMClient
from .ai_prompts import INTENT_PROMPT_TEMPLATE
from .models import Intent, IntentType


_FIELD_HINTS: Dict[str, List[str]] = {
    "title": ["标题", "题目", "title"],
    "content": ["正文", "内容", "详情", "description"],
    "date": ["时间", "日期", "time", "date"],
    "author": ["作者", "发布人", "回答者", "author"],
    "price": ["价格", "价钱", "price"],
    "images": ["图片", "配图", "image", "photo"],
    "links": ["链接", "url", "跳转"],
    "name": ["用户名", "昵称", "name"],
    "follows": ["粉丝", "关注", "followers"],
    "answer": ["回答", "回复"],
    "sub_comments": ["楼中楼", "回复", "评论"],
}

_INTENT_HINTS: Dict[IntentType, List[str]] = {
    IntentType.CRAWL_LIST: ["列表", "多条", "分页", "批量", "前10", "top"],
    IntentType.DOWNLOAD_IMAGES: ["下载图片", "保存图片", "图集"],
    IntentType.CRAWL_DETAIL: ["详情页", "递归", "深度"],
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

        intent_type = self._safe_intent_type(data.get("intent_type")) if data else heuristics["intent_type"]
        requested_fields = self._merge_fields(data.get("requested_fields") if data else None, heuristics["requested_fields"])
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
            content = response.get("content", "").strip()
            if content.startswith("```"):
                content = content.strip("`")
                if content.startswith("json"):
                    content = content[4:]
                content = content.strip()
            return json.loads(content)
        except Exception:
            return {}

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
