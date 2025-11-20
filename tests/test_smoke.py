"""Basic smoke test for package imports and flow."""

from aismartspider import (
    Fetcher,
    DomSummarizer,
    MockClient,
    PageTypeClassifier,
    IntentParser,
    StrategyBuilder,
    Executor,
)


def test_smoke_flow():
    client = MockClient()
    fetcher = Fetcher()
    summarizer = DomSummarizer()
    classifier = PageTypeClassifier(client)
    intent_parser = IntentParser(client)
    strategy_builder = StrategyBuilder(client)
    executor = Executor(fetcher)

    sample_html = """<html><head><title>Test</title></head><body><h1>标题</h1><p>正文</p></body></html>"""
    dom_summary = summarizer.summarize(sample_html)
    typing = classifier.classify(dom_summary)
    intent = intent_parser.parse("抓标题")
    strategy = strategy_builder.build(typing, intent, dom_summary)

    fetcher.fetch = lambda _: sample_html  # type: ignore

    records = executor.execute("http://example.com", strategy)

    assert isinstance(records, list)
    assert records[0].get("title") == "标题"
