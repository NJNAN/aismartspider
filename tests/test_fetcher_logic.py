"""Tests for dynamic rendering heuristics and fetch fallbacks."""

from __future__ import annotations

from aismartspider.fetcher import Fetcher


class StubFetcher(Fetcher):
    def __init__(self, static_html: str, render_payload):
        super().__init__(use_playwright=True, auto_render=True, render_backends=("playwright",))
        self._static_html = static_html
        self._render_payload = render_payload
        self.render_attempts = 0

    def _fetch_static(self, url: str):
        return self._static_html, url

    def _render_with_backends(self, url: str):
        self.render_attempts += 1
        return self._render_payload


def test_fetcher_auto_switches_to_renderer_on_dynamic_page():
    render_payload = ("<html><body>rendered</body></html>", "http://example.com/detail", "playwright")
    fetcher = StubFetcher("<html></html>", render_payload)
    result = fetcher.fetch("http://example.com")

    assert result.renderer == "playwright"
    assert result.html == render_payload[0]
    assert result.url == render_payload[1]
    assert fetcher.render_attempts == 1


def test_fetcher_keeps_static_result_on_content_rich_page():
    static_html = "<html>" + "<p>data</p>" * 500 + "</html>"
    render_payload = ("<html></html>", "http://example.com/rendered", "playwright")
    fetcher = StubFetcher(static_html, render_payload)
    result = fetcher.fetch("http://example.com")

    assert result.renderer == "static"
    assert result.html == static_html
    assert fetcher.render_attempts == 0
