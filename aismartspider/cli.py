"""Command line entry point for AISmartSpider."""

from __future__ import annotations

import argparse
import os

from .ai_client import OpenAIClient, MockClient, GeminiClient
from .dom_summary import DomSummarizer
from .executor import Executor
from .fetcher import Fetcher
from .intent_parser import IntentParser
from .output import PrintWriter, TxtWriter, JsonWriter, CsvWriter, SQLiteWriter
from .strategy_builder import StrategyBuilder
from .page_classifier import PageTypeClassifier


def _build_writer(mode: str, path: str | None = None):
    if mode == "print":
        return PrintWriter()
    if mode == "txt":
        return TxtWriter(path or "output.txt")
    if mode == "json":
        return JsonWriter(path or "output.json")
    if mode == "csv":
        return CsvWriter(path or "output.csv")
    if mode == "sqlite":
        return SQLiteWriter(path or "data.db")
    return PrintWriter()


def main() -> None:
    parser = argparse.ArgumentParser("AISmartSpider CLI")
    parser.add_argument("url", help="Target URL")
    parser.add_argument("--task", required=True, help="自然语言任务描述")
    parser.add_argument("--output-mode", default="print", choices=["print", "txt", "json", "csv", "sqlite"])
    parser.add_argument("--output-path", default=None)
    parser.add_argument("--use-mock", action="store_true")
    parser.add_argument("--api-key", default=None, help="API Key for the provider")
    parser.add_argument("--base-url", default=None, help="Base URL for OpenAI-compatible APIs (e.g. DeepSeek)")
    parser.add_argument("--provider", default="openai", choices=["openai", "gemini", "mock"], help="LLM Provider")
    parser.add_argument("--model", default="gpt-4o-mini", help="LLM Model Name")
    parser.add_argument("--enable-playwright", action="store_true", help="Enable Playwright for dynamic content")
    args = parser.parse_args()

    api_key = args.api_key or os.getenv("OPENAI_API_KEY", "")
    
    if args.use_mock or args.provider == "mock":
        client = MockClient()
    elif args.provider == "gemini":
        client = GeminiClient(api_key=api_key, model=args.model)
    else:
        # Default to OpenAI (supports DeepSeek via base_url)
        client = OpenAIClient(api_key=api_key, base_url=args.base_url, model=args.model)

    fetcher = Fetcher(use_playwright=args.enable_playwright)
    summarizer = DomSummarizer()
    classifier = PageTypeClassifier(client)
    intent_parser = IntentParser(client)
    strategy_builder = StrategyBuilder(client)
    executor = Executor(fetcher)
    writer = _build_writer(args.output_mode, args.output_path)

    html = fetcher.fetch(args.url)
    if not html:
        print("❌ Error: Failed to fetch content from URL. Please check the URL or try --enable-playwright.")
        return

    dom_summary = summarizer.summarize(html)
    typing = classifier.classify(dom_summary)
    intent = intent_parser.parse(args.task)
    strategy = strategy_builder.build(typing, intent, dom_summary)
    records = executor.execute(args.url, strategy)
    writer.write(records)


if __name__ == "__main__":
    main()
