"""Minimal demo using MockClient and inline HTML."""

from aismartspider import (
    Fetcher,
    DomSummarizer,
    MockClient,
    PageTypeClassifier,
    IntentParser,
    StrategyBuilder,
    Executor,
)


def main() -> None:
    url = "http://example.com"
    task = "帮我抓标题和正文"

    client = MockClient()
    fetcher = Fetcher()
    summarizer = DomSummarizer()
    classifier = PageTypeClassifier(client)
    intent_parser = IntentParser(client)
    strategy_builder = StrategyBuilder(client)
    executor = Executor(fetcher)

    html = """<html><head><title>Demo</title></head><body><h1>示例标题</h1><p>示例正文</p></body></html>"""
    dom_summary = summarizer.summarize(html)
    typing = classifier.classify(dom_summary)
    intent = intent_parser.parse(task)
    strategy = strategy_builder.build(typing, intent, dom_summary)

    # Monkey patch fetcher to avoid network dependency in the demo.
    fetcher.fetch = lambda _: html  # type: ignore

    records = executor.execute(url, strategy)

    from pprint import pprint

    pprint(records)


if __name__ == "__main__":
    main()
