"""Classifier and strategy tests across page types."""

from pathlib import Path

import pytest

from aismartspider import (
    DomSummarizer,
    PageType,
    PageTypeClassifier,
    IntentParser,
    StrategyBuilder,
    MockClient,
)

FIXTURE_DIR = Path(__file__).parent / "fixtures"


@pytest.mark.parametrize(
    ("fixture_name", "marker", "expected_type"),
    [
        ("news.html", "TEST_PAGE_TYPE:news", PageType.NEWS),
        ("list.html", "TEST_PAGE_TYPE:list", PageType.LIST),
        ("gallery.html", "TEST_PAGE_TYPE:gallery", PageType.GALLERY),
        ("forum.html", "TEST_PAGE_TYPE:forum", PageType.FORUM),
    ],
)
def test_classifier_detects_common_page_types(fixture_name: str, marker: str, expected_type: PageType) -> None:
    html = (FIXTURE_DIR / fixture_name).read_text(encoding="utf-8")
    summarizer = DomSummarizer()
    classifier = PageTypeClassifier(MockClient())
    intent_parser = IntentParser(MockClient())
    strategy_builder = StrategyBuilder(MockClient())

    # 在 summary 里加一个专用于 MockClient 的测试标记，避免受自然语言变化影响
    summary = summarizer.summarize(html) + "\n" + marker
    typing = classifier.classify(summary)
    intent = intent_parser.parse("抓标题")
    strategy = strategy_builder.build(typing, intent, summary)

    assert typing.page_type == expected_type
    assert strategy.page_type == expected_type
    assert intent.requested_fields == ["title", "content"]
