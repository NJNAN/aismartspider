# AISmartSpider

AISmartSpider upgrades the original research prototype into a reproducible, engineering-grade crawling framework. It combines LLM-assisted reasoning with deterministic fallbacks so experiments can be repeated across sites and rendering modes.

## Key capabilities

- **Deterministic prompts** – Page typing, intent parsing and strategy generation prompts now enforce JSON-only outputs with explicit enumerations. The parser layer validates every field and auto-heals invalid replies.
- **Robust URL handling** – Every fetch returns the real, final URL. Executors propagate that context when resolving list/detail links, pagination and image sources, removing the brittle `base_url` dependence.
- **Automatic dynamic detection** – Static HTML is inspected for JS-heavy patterns. When needed the fetcher transparently escalates to Playwright and (optionally) Selenium, complete with graceful degradation.
- **Pluggable outputs** – Text, JSON, CSV, SQLite, MySQL and PostgreSQL writers share a common abstraction. Nested fields are normalized automatically so the same code path serves local files or external databases.
- **Packaged for PyPI** – A cleaned `pyproject.toml`, optional extras (Gemini, MySQL, Postgres, Selenium) and an expanded README ensure `pip install aismartspider` just works for reviewers.
- **Tests and smoke checks** – Additional coverage guards the fetcher heuristics, executor URL resolution, and writer normalization.

## Installation

```bash
python -m venv .venv
.venv\Scripts\activate  # or source .venv/bin/activate on Unix
pip install -U pip
pip install -e ".[mysql,postgres,google,selenium]"
# Install Playwright browsers once
playwright install
```

The optional extras are:

- `google` – `google-generativeai` for Gemini integration.
- `mysql` – `pymysql` for the MySQL writer.
- `postgres` – `psycopg2-binary` for PostgreSQL.
- `selenium` – Selenium-based renderer fallback.

## Quick start

```bash
aismartspider "https://example.com/news" --task "extract title and content" --output-mode json --output-path news.json
```

Important CLI flags:

| Flag | Description |
| --- | --- |
| `--render-backends` | Ordered render pipeline (default `playwright,selenium`). |
| `--disable-auto-render` | Force static mode only. |
| `--output-mode` | `print`, `txt`, `json`, `csv`, `sqlite`, `mysql`, `postgres`. |
| `--db-*` | Connection info for SQL outputs. |

## Programmatic usage

```python
from aismartspider import (
    Fetcher, Executor, DomSummarizer, PageTypeClassifier,
    IntentParser, StrategyBuilder, MockClient
)

client = MockClient()
fetcher = Fetcher()
summarizer = DomSummarizer()
classifier = PageTypeClassifier(client)
intent_parser = IntentParser(client)
strategy_builder = StrategyBuilder(client)
executor = Executor(fetcher)

page = fetcher.fetch("https://example.com")
summary = summarizer.summarize(page.html)
typing = classifier.classify(summary)
intent = intent_parser.parse("grab title and body text")
strategy = strategy_builder.build(typing, intent, summary)
records = executor.execute(page.url, strategy)
```

## Tests

```bash
pytest
```

The suite covers prompt heuristics, executor flows, fetcher fallbacks and writer serialization so regressions are detected early.

## Links

- GitHub: https://github.com/NJNAN/aismartspider
- Issues welcome via GitHub tracker.
