"""Tests for advanced executor flows."""

from __future__ import annotations

from typing import Dict

from aismartspider import Executor, FetchResult
from aismartspider.models import Intent, IntentType, PageType, Strategy
from aismartspider.utils.retry import RetryPolicy


class DummyFetcher:
    def __init__(self, mapping: Dict[str, str]) -> None:
        self.mapping = mapping

    def fetch(self, url: str) -> FetchResult:
        return FetchResult(url=url, html=self.mapping[url], renderer="mock")


class NoRetry(RetryPolicy):
    def run(self, func):
        return func()


def _strategy_for_list() -> Strategy:
    intent = Intent(intent_type=IntentType.CRAWL_LIST, requested_fields=["title", "content"], raw_text="")
    return Strategy(
        page_type=PageType.LIST,
        intent=intent,
        field_selectors={"title": "h1", "content": "p"},
        field_methods={"title": "css", "content": "css"},
        is_list=True,
        item_link_selector=".item-link",
        max_depth=3,
        pagination_selector=None,
        max_pages=1,
    )


def test_list_flow_followes_detail_pages():
    base_url = "http://example.com/list.html"
    mapping = {
        base_url: """
        <html><body>
            <ul>
                <li><a class="item-link" href="/d1.html">Item 1</a></li>
                <li><a class="item-link" href="/d2.html">Item 2</a></li>
            </ul>
        </body></html>
        """,
        "http://example.com/d1.html": "<html><body><h1>Title 1</h1><p>Content 1</p></body></html>",
        "http://example.com/d2.html": "<html><body><h1>Title 2</h1><p>Content 2</p></body></html>",
    }
    executor = Executor(DummyFetcher(mapping), retry_policy=NoRetry())
    records = executor.execute(base_url, _strategy_for_list())
    assert len(records) == 2
    assert {record["title"] for record in records} == {"Title 1", "Title 2"}


def test_gallery_flow_collects_images():
    intent = Intent(intent_type=IntentType.DOWNLOAD_IMAGES, requested_fields=["title"], raw_text="")
    strategy = Strategy(
        page_type=PageType.GALLERY,
        intent=intent,
        field_selectors={"title": "h1"},
        field_methods={"title": "css"},
        image_selector=".gallery img",
    )
    html = """
    <html>
      <body>
        <h1>Gallery</h1>
        <div class="gallery">
            <img src="a.jpg" />
            <img src="b.jpg" />
        </div>
      </body>
    </html>
    """
    base_url = "http://example.com/gallery.html"
    executor = Executor(DummyFetcher({base_url: html}), retry_policy=NoRetry())
    records = executor.execute(base_url, strategy)
    assert records[0]["title"] == "Gallery"
    assert records[0]["images"] == ["http://example.com/a.jpg", "http://example.com/b.jpg"]


def test_primary_image_selector_returns_single_image():
    intent = Intent(intent_type=IntentType.EXTRACT_INFO, requested_fields=["title", "image"], raw_text="")
    strategy = Strategy(
        page_type=PageType.NEWS,
        intent=intent,
        field_selectors={"title": "h1"},
        field_methods={"title": "css"},
        primary_image_field="image",
        primary_image_selector="article img.hero",
    )
    html = """
    <html>
        <body>
            <article>
                <h1>Hero</h1>
                <img class="hero" src="/hero.jpg" />
                <img src="/other.jpg" />
            </article>
        </body>
    </html>
    """
    base_url = "http://example.com/detail.html"
    executor = Executor(DummyFetcher({base_url: html}), retry_policy=NoRetry())
    record = executor.execute(base_url, strategy)[0]
    assert record["title"] == "Hero"
    assert record["image"] == "http://example.com/hero.jpg"
