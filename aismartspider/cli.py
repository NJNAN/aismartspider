"""Command line entry point for AISmartSpider."""

from __future__ import annotations

import argparse
import os

from .ai_client import OpenAIClient, MockClient, GeminiClient
from .dom_summary import DomSummarizer
from .executor import Executor
from .fetcher import Fetcher
from .intent_parser import IntentParser
from .output import (
    PrintWriter,
    TxtWriter,
    JsonWriter,
    CsvWriter,
    SQLiteWriter,
    MySQLWriter,
    PostgresWriter,
)
from .strategy_builder import StrategyBuilder
from .page_classifier import PageTypeClassifier


def _build_writer(mode: str, path: str | None, args: argparse.Namespace):
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
    if mode == "mysql":
        return MySQLWriter(
            host=args.db_host,
            port=args.db_port or 3306,
            user=args.db_user,
            password=args.db_password or "",
            database=args.db_name,
            table=args.db_table,
        )
    if mode == "postgres":
        return PostgresWriter(
            host=args.db_host,
            port=args.db_port or 5432,
            user=args.db_user,
            password=args.db_password or "",
            database=args.db_name,
            table=args.db_table,
        )
    return PrintWriter()


def main() -> None:
    parser = argparse.ArgumentParser("AISmartSpider CLI")
    parser.add_argument("url", help="Target URL")
    parser.add_argument("--task", required=True, help="Natural language task description.")
    parser.add_argument(
        "--output-mode",
        default="print",
        choices=["print", "txt", "json", "csv", "sqlite", "mysql", "postgres"],
        help="Output backend.",
    )
    parser.add_argument("--output-path", default=None, help="File path for txt/json/csv/sqlite outputs.")
    parser.add_argument("--db-host", default="localhost", help="Database host for SQL outputs.")
    parser.add_argument("--db-port", type=int, default=None, help="Database port for SQL outputs.")
    parser.add_argument("--db-user", default="root", help="Database username.")
    parser.add_argument("--db-password", default=None, help="Database password.")
    parser.add_argument("--db-name", default="aismartspider", help="Database/schema name.")
    parser.add_argument("--db-table", default="records", help="Target table name.")
    parser.add_argument("--use-mock", action="store_true", help="Use offline mock LLM responses.")
    parser.add_argument("--api-key", default=None, help="API Key for the provider")
    parser.add_argument("--base-url", default=None, help="Base URL for OpenAI-compatible APIs (e.g. DeepSeek)")
    parser.add_argument("--provider", default="openai", choices=["openai", "gemini", "mock"], help="LLM Provider")
    parser.add_argument("--model", default="gpt-4o-mini", help="LLM Model Name")
    parser.add_argument("--enable-playwright", action="store_true", help="(Legacy) ensure Playwright is in the render chain.")
    parser.add_argument(
        "--render-backends",
        default="playwright,selenium",
        help="Comma separated render pipeline, e.g. 'playwright,selenium'.",
    )
    parser.add_argument(
        "--disable-auto-render",
        action="store_true",
        help="Disable automatic detection of dynamic pages.",
    )
    args = parser.parse_args()

    api_key = args.api_key or os.getenv("OPENAI_API_KEY", "")

    if args.use_mock or args.provider == "mock":
        client = MockClient()
    elif args.provider == "gemini":
        client = GeminiClient(api_key=api_key, model=args.model)
    else:
        client = OpenAIClient(api_key=api_key, base_url=args.base_url, model=args.model)

    render_backends = [backend.strip() for backend in args.render_backends.split(",") if backend.strip()]
    if args.enable_playwright and "playwright" not in render_backends:
        render_backends.append("playwright")

    fetcher = Fetcher(
        use_playwright=True,
        auto_render=not args.disable_auto_render,
        render_backends=tuple(render_backends) if render_backends else None,
    )
    summarizer = DomSummarizer()
    classifier = PageTypeClassifier(client)
    intent_parser = IntentParser(client)
    strategy_builder = StrategyBuilder(client)
    executor = Executor(fetcher)
    writer = _build_writer(args.output_mode, args.output_path, args)

    page = fetcher.fetch(args.url)
    if not page.html:
        print("[ERROR] Failed to fetch content. Try a different renderer or check network connectivity.")
        return

    dom_summary = summarizer.summarize(page.html)
    typing = classifier.classify(dom_summary)
    intent = intent_parser.parse(args.task)
    strategy = strategy_builder.build(typing, intent, dom_summary)
    records = executor.execute(page.url or args.url, strategy)
    writer.write(records)


if __name__ == "__main__":
    main()
