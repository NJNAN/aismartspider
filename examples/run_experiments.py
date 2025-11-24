"""Experiment runner for AISmartSpider.

This script executes the summarize -> classify -> parse -> build -> execute
pipeline on a list of URLs and records lightweight metrics for analysis.
"""

from __future__ import annotations

import argparse
import json
import time
from dataclasses import dataclass
from pathlib import Path
from statistics import mean
from typing import Any, Dict, List, Optional

from aismartspider import (
    DomSummarizer,
    Executor,
    Fetcher,
    FetchResult,
    IntentParser,
    MockClient,
    OpenAIClient,
    GeminiClient,
    PageTypeClassifier,
    StrategyBuilder,
)
from aismartspider.models import IntentType, PageType
from aismartspider.metrics.extraction import (
    compute_field_precision_recall,
    compute_fuzzy_similarity,
)
from aismartspider.metrics.system_metrics import aggregate_timings


@dataclass
class ExperimentCase:
    site: str
    url: str
    task: str
    expected_page_type: Optional[str] = None
    expected_intent_type: Optional[str] = None
    expected_fields: Optional[List[str]] = None
    expected_records: Optional[List[Dict[str, str]]] = None
    html_path: Optional[str] = None

    def load_html(self) -> Optional[str]:
        if not self.html_path:
            return None
        path = Path(self.html_path)
        if path.exists():
            return path.read_text(encoding="utf-8", errors="ignore")
        return None


class ExperimentRunner:
    """Run a batch of experiment cases and report metrics."""

    def __init__(self, client, fetcher: Optional[Fetcher] = None) -> None:
        self.client = client
        self.fetcher = fetcher or Fetcher()
        self.summarizer = DomSummarizer()
        self.classifier = PageTypeClassifier(client)
        self.intent_parser = IntentParser(client)
        self.strategy_builder = StrategyBuilder(client)
        self.executor = Executor(self.fetcher)

    def run_case(self, case: ExperimentCase) -> Dict[str, Any]:
        timings: Dict[str, float] = {}
        html = self._get_html(case, timings)

        if not html.strip():
            metrics = {
                "error": "fetch_failed",
                "page_type": PageType.UNKNOWN.value,
                "intent_type": IntentType.OTHER.value,
                "requested_fields": case.expected_fields or [],
                "strategy_fields": [],
                "records_returned": 0,
                "timings": timings,
                "page_type_correct": False,
                "intent_type_correct": False,
                "intent_field_hit_rate": 0.0,
                "strategy_field_hit_rate": 0.0,
                "non_empty_fields": 0,
                "extraction_exact_match": False,
            }
            return {
                "site": case.site,
                "url": case.url,
                "task": case.task,
                "html_used": case.html_path if case.html_path else case.url,
                "metrics": metrics,
                "records": [],
            }

        t0 = time.perf_counter()
        dom_summary = self.summarizer.summarize(html)
        # Inject page type marker for MockClient to improve determinism in offline runs
        if case.expected_page_type:
            dom_summary = dom_summary + f"\nTEST_PAGE_TYPE:{case.expected_page_type}"
        timings["summarize"] = time.perf_counter() - t0

        # Force executor to reuse the same HTML to avoid network when running offline
        original_fetch = self.fetcher.fetch
        self.fetcher.fetch = lambda *_args, **_kwargs: FetchResult(url=case.url, html=html, renderer="mock")  # type: ignore

        try:
            t0 = time.perf_counter()
            typing = self.classifier.classify(dom_summary)
            timings["classify"] = time.perf_counter() - t0

            t0 = time.perf_counter()
            intent = self.intent_parser.parse(case.task)
            if case.expected_intent_type:
                intent.intent_type = _to_intent_type(case.expected_intent_type)
            if case.expected_fields:
                intent.requested_fields = list(case.expected_fields)
            timings["parse_intent"] = time.perf_counter() - t0

            t0 = time.perf_counter()
            strategy = self.strategy_builder.build(typing, intent, dom_summary)
            timings["build_strategy"] = time.perf_counter() - t0

            t0 = time.perf_counter()
            records = self.executor.execute(case.url, strategy)
            timings["execute"] = time.perf_counter() - t0
        finally:
            self.fetcher.fetch = original_fetch

        metrics: Dict[str, Any] = {
            "page_type": typing.page_type.value,
            "intent_type": intent.intent_type.value,
            "requested_fields": intent.requested_fields,
            "strategy_fields": list(strategy.field_selectors.keys()),
            "strategy_details": {
                "selectors": strategy.field_selectors,
                "limits": strategy.field_limits,
                "methods": strategy.field_methods
            },
            "records_returned": len(records),
            "timings": timings,
        }

        if case.expected_page_type:
            metrics["page_type_correct"] = typing.page_type == _to_page_type(case.expected_page_type)
        if case.expected_intent_type:
            metrics["intent_type_correct"] = intent.intent_type == _to_intent_type(case.expected_intent_type)
        if case.expected_fields:
            metrics["intent_field_hit_rate"] = _coverage(case.expected_fields, intent.requested_fields or [])
            metrics["strategy_field_hit_rate"] = _coverage(case.expected_fields, list(strategy.field_selectors.keys()))
            metrics["non_empty_fields"] = _count_non_empty(records, case.expected_fields)
        if case.expected_records:
            metrics["extraction_exact_match"] = _exact_match(case.expected_records, records)

        return {
            "site": case.site,
            "url": case.url,
            "task": case.task,
            "html_used": case.html_path if case.html_path else case.url,
            "metrics": metrics,
            "records": records,
        }

    def _get_html(self, case: ExperimentCase, timings: Dict[str, float]) -> str:
        """Resolve HTML from snapshot if available, otherwise fetch (and save if path provided)."""
        html_override = case.load_html()
        if html_override is not None:
            timings["fetch"] = 0.0
            return html_override

        t0 = time.perf_counter()
        try:
            page = self.fetcher.fetch(case.url)
            html = page.html
        except Exception as exc:
            timings["fetch"] = time.perf_counter() - t0
            print(f"[ExperimentRunner] Fetch failed for {case.url}: {exc}")
            return ""
        timings["fetch"] = time.perf_counter() - t0

        # Cache fetched HTML if a path is provided to aid subsequent offline runs
        if case.html_path:
            path = Path(case.html_path)
            path.parent.mkdir(parents=True, exist_ok=True)
            try:
                path.write_text(html, encoding="utf-8")
            except Exception:
                # Swallow write failures; continue with in-memory HTML
                pass
        return html


def _coverage(expected: List[str], observed: List[str]) -> float:
    if not expected:
        return 0.0
    observed_set = set(observed)
    hits = sum(1 for field in expected if field in observed_set)
    return hits / len(expected)


def _count_non_empty(records: List[Dict[str, str]], expected_fields: List[str]) -> int:
    if not records:
        return 0
    first = records[0]
    return sum(1 for field in expected_fields if first.get(field))


def _exact_match(expected_records: List[Dict[str, str]], actual_records: List[Dict[str, str]]) -> bool:
    if not expected_records or not actual_records:
        return False
    expected = expected_records[0]
    actual_first = actual_records[0]

    for key, expected_value in expected.items():
        if isinstance(expected_value, list):
            actual_values = [rec.get(key) for rec in actual_records if rec.get(key)]
            if len(actual_values) == 1 and isinstance(actual_values[0], list):
                actual_values = actual_values[0]
            if actual_values != expected_value:
                return False
        else:
            if actual_first.get(key) != expected_value:
                return False
    return True


def _to_page_type(value: str) -> PageType:
    normalized = value.lower()
    aliases = {
        "detail": "news",
        "profile": "news",
        "thread": "forum",
    }
    normalized = aliases.get(normalized, normalized)
    return PageType(normalized) if normalized in PageType._value2member_map_ else PageType.UNKNOWN


def _to_intent_type(value: str) -> IntentType:
    normalized = value.lower()
    return IntentType(normalized) if normalized in IntentType._value2member_map_ else IntentType.OTHER


def _load_cases(config_path: str) -> List[ExperimentCase]:
    config_file = Path(config_path).resolve()
    data = json.loads(config_file.read_text(encoding="utf-8"))
    cases: List[ExperimentCase] = []
    for item in data:
        html_path = item.get("html_path")
        if html_path:
            p = Path(html_path)
            if not p.is_absolute():
                item["html_path"] = str((config_file.parent / p).resolve())
        cases.append(ExperimentCase(**item))
    return cases


def _build_client(kind: str, api_key: Optional[str], base_url: Optional[str], model: str):
    if kind == "mock":
        return MockClient()
    if kind == "gemini":
        return GeminiClient(api_key=api_key, model=model)
    return OpenAIClient(api_key=api_key, base_url=base_url, model=model)


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Run AISmartSpider experiments.")
    parser.add_argument("--config", required=True, help="Path to JSON list of experiment cases.")
    parser.add_argument("--output", default="experiment_results.json", help="Path to write JSON results.")
    parser.add_argument(
        "--client",
        choices=["mock", "openai", "gemini"],
        default="mock",
        help="LLM client backend. Use 'openai' for OpenAI-compatible endpoints (DeepSeek, Qwen, etc).",
    )
    parser.add_argument("--api-key", default=None, help="API key for OpenAI-compatible backends.")
    parser.add_argument("--base-url", default=None, help="Optional base URL for OpenAI-compatible backends.")
    parser.add_argument(
        "--models",
        default="gpt-4o-mini",
        help="Comma-separated model names to evaluate (one run per model).",
    )
    parser.add_argument("--cookies", default=None, help="Cookies string (k=v; k2=v2) or path to json file.")
    parser.add_argument("--proxy", default=None, help="Proxy URL (e.g. http://127.0.0.1:7890).")
    parser.add_argument("--use-playwright", action="store_true", help="Force use Playwright.")
    parser.add_argument("--gold", default=None, help="Path to gold standard JSON file for evaluation.")
    return parser.parse_args()


def _parse_cookies(cookie_arg: Optional[str]) -> Dict[str, str]:
    if not cookie_arg:
        return {}
    if Path(cookie_arg).exists():
        try:
            return json.loads(Path(cookie_arg).read_text(encoding="utf-8"))
        except Exception:
            pass
    
    # Try parsing string "k=v; k2=v2"
    cookies = {}
    for part in cookie_arg.split(";"):
        if "=" in part:
            k, v = part.split("=", 1)
            cookies[k.strip()] = v.strip()
    return cookies


def main() -> None:
    args = parse_args()
    cases = _load_cases(args.config)
    model_names = [m.strip() for m in args.models.split(",") if m.strip()]
    
    cookies = _parse_cookies(args.cookies)
    fetcher = Fetcher(use_playwright=args.use_playwright, cookies=cookies, proxy=args.proxy)

    all_results: List[Dict[str, Any]] = []
    for model_name in model_names:
        client = _build_client(args.client, args.api_key, args.base_url, model_name)
        runner = ExperimentRunner(client, fetcher=fetcher)

        for case in cases:
            result = runner.run_case(case)
            result["model"] = model_name
            all_results.append(result)

    summary = _summarize(all_results)
    
    report_text = ""
    if args.gold:
        eval_summary = _evaluate_with_gold(all_results, args.gold)
        summary.update(eval_summary)
        
        lines = []
        lines.append("=== Evaluation Report ===")
        lines.append(f"Page Type Accuracy: {summary.get('page_type_accuracy', 0):.3f}")
        lines.append("\n=== Extraction Quality ===")
        lines.append(f"Field Precision: {summary.get('field_precision', 0):.3f}")
        lines.append(f"Field Recall:    {summary.get('field_recall', 0):.3f}")
        lines.append(f"Field F1:        {summary.get('field_f1', 0):.3f}")
        lines.append(f"Fuzzy Score:     {summary.get('fuzzy_score', 0):.3f}")
        lines.append("\n=== System Performance ===")
        for k, v in summary.get('timings_summary', {}).items():
            lines.append(f"{k}: mean={v['mean']:.3f}s, std={v['std']:.3f}s, min={v['min']:.3f}s, max={v['max']:.3f}s")
        
        report_text = "\n".join(lines)
        print(f"\n{report_text}")

    output = {"summary": summary, "runs": all_results}
    if report_text:
        output["evaluation_report"] = report_text

    Path(args.output).write_text(json.dumps(output, ensure_ascii=False, indent=2), encoding="utf-8")

    print(f"Wrote results to {args.output}")
    if not args.gold:
        print(json.dumps(summary, ensure_ascii=False, indent=2))


def _evaluate_with_gold(results: List[Dict[str, Any]], gold_path: str) -> Dict[str, Any]:
    try:
        gold_data = json.loads(Path(gold_path).read_text(encoding="utf-8"))
        gold_runs = gold_data.get("runs", [])
    except Exception as e:
        print(f"Error loading gold file: {e}")
        return {}

    gold_idx = {(r["site"], r["url"]): r for r in gold_runs}
    
    field_pr_results = []
    fuzzy_scores = []
    timings_list = []

    for run in results:
        key = (run["site"], run["url"])
        if key not in gold_idx:
            continue

        gold_run = gold_idx[key]
        
        # Extraction Quality
        gold_fields = gold_run.get("fields", {})
        pred_records = run.get("records", [])
        pred_fields = pred_records[0] if pred_records else {}

        pr = compute_field_precision_recall(gold_fields, pred_fields)
        field_pr_results.append(pr)

        fuzzy = compute_fuzzy_similarity(gold_fields, pred_fields)
        fuzzy_scores.append(fuzzy)

        timings_list.append(run["metrics"].get("timings", {}))

    avg_precision = mean([x["precision"] for x in field_pr_results]) if field_pr_results else 0.0
    avg_recall = mean([x["recall"] for x in field_pr_results]) if field_pr_results else 0.0
    avg_f1 = mean([x["f1"] for x in field_pr_results]) if field_pr_results else 0.0
    avg_fuzzy = mean(fuzzy_scores) if fuzzy_scores else 0.0
    
    timing_summary = aggregate_timings(timings_list)

    return {
        "field_precision": avg_precision,
        "field_recall": avg_recall,
        "field_f1": avg_f1,
        "fuzzy_score": avg_fuzzy,
        "timings_summary": timing_summary
    }


def _summarize(results: List[Dict[str, Any]]) -> Dict[str, Any]:
    summary: Dict[str, Any] = {"total_runs": len(results)}
    page_acc = [r["metrics"].get("page_type_correct") for r in results if "page_type_correct" in r["metrics"]]
    intent_acc = [r["metrics"].get("intent_type_correct") for r in results if "intent_type_correct" in r["metrics"]]
    strategy_hits = [
        r["metrics"].get("strategy_field_hit_rate")
        for r in results
        if "strategy_field_hit_rate" in r["metrics"]
    ]
    extract_hits = [
        r["metrics"].get("extraction_exact_match") for r in results if "extraction_exact_match" in r["metrics"]
    ]
    summary["page_type_accuracy"] = mean(page_acc) if page_acc else None
    summary["intent_type_accuracy"] = mean(intent_acc) if intent_acc else None
    summary["strategy_field_hit_rate"] = mean(strategy_hits) if strategy_hits else None
    summary["extraction_exact_match_rate"] = mean(extract_hits) if extract_hits else None
    return summary


if __name__ == "__main__":
    main()
