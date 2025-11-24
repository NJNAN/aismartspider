"""Prompt templates used for LLM calls with strict JSON constraints."""

PAGE_TYPE_PROMPT_TEMPLATE = """
You are a web page structure classifier. Decide the page type based on the DOM summary.

Hard requirements:
1. Allowed values for page_type (lowercase only): ["news","list","product","gallery","forum","profile","single_page_app","unknown"]
2. Output EXACTLY one JSON object. No natural language, comments, or Markdown code fences.
3. The JSON object must include page_type, confidence (0-1 float), and suggested_fields (array of strings).

Output format:
{{
  "page_type": "news",
  "confidence": 0.92,
  "suggested_fields": ["title", "date", "content"]
}}

DOM summary:
{dom_summary}
"""

INTENT_PROMPT_TEMPLATE = """
You are a natural language task interpreter. Select INTENT_TYPE strictly from:
["extract_info","crawl_list","download_images","crawl_detail","compare_price","other"]

Also list the fields explicitly requested by the user (return an empty array if none).
Return ONLY a JSON object with the following keys: intent_type, requested_fields.

Example:
{{
  "intent_type": "crawl_list",
  "requested_fields": ["title","date","links"]
}}

User instruction:
{user_text}
"""

STRATEGY_PROMPT_TEMPLATE = """
You are a strategy generator that must return a deterministic JSON object describing how to extract data.

Context:
- page_type: {page_type}
- intent_type: {intent_type}
- user requested fields: {requested_fields}
- DOM summary: {dom_summary}

Constraints:
1. Respond with a SINGLE JSON object. No prose or Markdown.
2. Allowed keys: field_selectors (dict[str,str]), field_methods (dict[str,str]), field_limits (dict[str,int]),
   is_list (bool), item_link_selector (str|null), pagination_selector (str|null), max_depth (int),
   max_pages (int), image_selector (str|null), fallbacks (dict).
3. Prefer selectors derived from structure_hints; avoid overly broad "body" or plain "div".
4. Link fields must use attr:href, image fields must use attr:src.
5. If recursive crawling is needed, set item_link_selector and sensible max_depth/max_pages.

Example output:
{{
  "field_selectors": {{"title": "article h1", "content": ".article-body"}},
  "field_methods": {{"title": "css", "content": "css"}},
  "field_limits": {{"links": 10}},
  "is_list": false,
  "item_link_selector": null,
  "pagination_selector": null,
  "max_depth": 1,
  "max_pages": 1,
  "image_selector": null,
  "fallbacks": {{"field_selectors": {{"title": "title"}}}}
}}
"""

FIRST_IMAGE_PROMPT_TEMPLATE = """
You are producing a single CSS selector that points to the semantic first/hero image inside the article body.

Contract:
1. Reply with ONLY one JSON object matching this schema: {{"selector": "<css-selector-or-null>"}}.
2. selector must be a single CSS selector string targeting exactly one <img>. If there is no valid hero image, set selector to null.
3. Never return image URLs, arrays, or explanations. No Markdown or prose.
4. Focus on main/article/section content areas and ignore navigation, headers, footers, or ad banners.
5. Prefer selectors that begin from meaningful containers (article, main, #content, .post-body, etc.) and avoid generic "img".

Inputs:
- page_type: {page_type}
- task: {task}
- requested_field: {field_name}
- DOM summary (includes structure_hints + image_hints with parent tags and order): {dom_summary}
"""
