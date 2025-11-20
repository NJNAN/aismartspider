"""Tests for heuristic fallbacks on parser and builder."""

from __future__ import annotations

import json

from aismartspider import IntentParser, StrategyBuilder, PageType
from aismartspider.ai_client import LLMClient
from aismartspider.models import Intent, IntentType, PageTypingResult


class BrokenClient(LLMClient):
    """Client that always returns invalid payload to trigger heuristics."""

    def chat(self, messages, **kwargs):
        return {"content": "invalid"}


def test_intent_parser_heuristic_fields():
    parser = IntentParser(BrokenClient())
    intent = parser.parse("帮我抓取列表标题和图片")
    assert intent.intent_type == IntentType.CRAWL_LIST
    assert set(intent.requested_fields or []) >= {"title", "images"}


def test_strategy_builder_heuristic_defaults():
    builder = StrategyBuilder(BrokenClient())
    typing = PageTypingResult(page_type=PageType.LIST, confidence=0.8)
    intent = Intent(intent_type=IntentType.CRAWL_LIST, requested_fields=["title"], raw_text="")
    dom_summary = json.dumps({"tag_counts": {"li": 20}})
    strategy = builder.build(typing, intent, dom_summary)
    assert strategy.is_list
    assert strategy.item_link_selector
    assert "title" in strategy.field_selectors
    assert strategy.field_methods["title"] == "css"
