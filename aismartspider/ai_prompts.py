"""Prompt templates used for LLM calls."""

PAGE_TYPE_PROMPT_TEMPLATE = """
你是一个网页结构分析助手。根据下面的 DOM 摘要判断页面类型。
类型只能从以下集合中选一个：
["news", "list", "product", "gallery", "forum", "single_page_app", "unknown"]

请只输出 JSON：
{{
  "page_type": "...",
  "confidence": 0.0,
  "suggested_fields": ["title", "date", ...]
}}

DOM 摘要：
{dom_summary}
"""

INTENT_PROMPT_TEMPLATE = """
你是一个自然语言任务解析器。根据用户指令，从以下类型中选一个任务类型：
["extract_info", "crawl_list", "download_images", "crawl_detail", "compare_price", "other"]

同时解析用户明确希望抽取的字段（如果有），例如 ["title","date","content"]。

请只输出 JSON：
{{
  "intent_type": "...",
  "requested_fields": ["..."]
}}

用户指令：
{user_text}
"""

STRATEGY_PROMPT_TEMPLATE = """
你是一个网页抽取策略生成器。根据页面类型、用户任务和 DOM 摘要，生成一个 JSON 策略，用于驱动爬虫。

页面类型: {page_type}
任务类型: {intent_type}
用户请求字段: {requested_fields}

DOM 摘要:
{dom_summary}

请注意：
1. 优先使用 DOM 摘要中 `structure_hints` 提供的 class 或 id 来定位正文容器（如 .article-body, #content 等），避免使用过于宽泛的 `body` 或 `div`。
2. 对于日期（date），尝试寻找包含时间信息的 meta 标签或具有 time/date 类名的元素。
3. 对于正文（content），尽量排除广告、侧边栏和评论区。

输出 JSON:
{{
  "field_selectors": {{"title": "h1", "date": ".time", "content": ".article-body"}},
  "field_methods": {{"title": "css", "date": "css", "content": "css"}},
  "is_list": false,
  "item_link_selector": null,
  "pagination_selector": null,
  "max_depth": 1,
  "max_pages": 1,
  "image_selector": null,
  "fallbacks": {{}}
}}
"""
