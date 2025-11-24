"""Helpers for parsing structured JSON returned by LLMs."""

from __future__ import annotations

import json
import re
from typing import Any, Dict, List

_CODE_FENCE_RE = re.compile(r"^```(?:json)?\s*(.*?)\s*```$", re.DOTALL | re.IGNORECASE)
_JSON_OBJECT_RE = re.compile(r"\{.*\}", re.DOTALL)
_JSON_ARRAY_RE = re.compile(r"\[.*\]", re.DOTALL)


def extract_json_payload(raw: str) -> Any:
    """Best-effort JSON extraction supporting code fences and noisy text."""
    content = raw.strip()
    if not content:
        return {}

    fenced = _CODE_FENCE_RE.match(content)
    if fenced:
        content = fenced.group(1).strip()

    for candidate in (content, _scan_candidate(content)):
        if not candidate:
            continue
        try:
            return json.loads(candidate)
        except json.JSONDecodeError:
            continue
    return {}


def _scan_candidate(content: str) -> str:
    """Scan for the first JSON object/array inside free-form text."""
    for regex in (_JSON_OBJECT_RE, _JSON_ARRAY_RE):
        match = regex.search(content)
        if match:
            return match.group(0)
    return ""


def ensure_string_list(value: Any) -> List[str]:
    """Return a sanitized string list."""
    if not isinstance(value, list):
        return []
    results: List[str] = []
    for item in value:
        if isinstance(item, str):
            stripped = item.strip()
            if stripped:
                results.append(stripped)
    return results


def ensure_mapping(value: Any) -> Dict[str, str]:
    """Return a mapping[str, str]."""
    if not isinstance(value, dict):
        return {}
    clean: Dict[str, str] = {}
    for key, val in value.items():
        if not isinstance(key, str):
            continue
        if isinstance(val, (str, int, float)):
            clean[key] = str(val).strip()
        elif isinstance(val, dict) or isinstance(val, list):
            clean[key] = json.dumps(val, ensure_ascii=False)
        else:
            continue
    return clean
