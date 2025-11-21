"""Shared dataclasses and enumerations."""

from __future__ import annotations

from dataclasses import dataclass
from enum import Enum
from typing import Optional, List, Dict, Any


class PageType(str, Enum):
    NEWS = "news"
    LIST = "list"
    PRODUCT = "product"
    GALLERY = "gallery"
    FORUM = "forum"
    PROFILE = "profile"
    SPA = "single_page_app"
    UNKNOWN = "unknown"


class IntentType(str, Enum):
    EXTRACT_INFO = "extract_info"
    CRAWL_LIST = "crawl_list"
    DOWNLOAD_IMAGES = "download_images"
    CRAWL_DETAIL = "crawl_detail"
    COMPARE_PRICE = "compare_price"
    OTHER = "other"


@dataclass
class PageTypingResult:
    page_type: PageType
    confidence: float
    suggested_fields: Optional[List[str]] = None


@dataclass
class Intent:
    intent_type: IntentType
    requested_fields: Optional[List[str]]
    raw_text: str


@dataclass
class Strategy:
    page_type: PageType
    intent: Intent

    field_selectors: Dict[str, str]
    field_methods: Dict[str, str]

    is_list: bool = False
    item_link_selector: Optional[str] = None
    max_depth: int = 1

    pagination_selector: Optional[str] = None
    max_pages: int = 1

    image_selector: Optional[str] = None

    fallbacks: Optional[Dict[str, Any]] = None
