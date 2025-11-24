"""LLM abstraction layer."""

from __future__ import annotations

import json
import time
from abc import ABC, abstractmethod
from typing import List, Dict, Any, Optional


class LLMClient(ABC):
    """Base interface for chat-capable language models."""

    @abstractmethod
    def chat(self, messages: List[Dict[str, str]], **kwargs) -> Dict[str, Any]:
        """Return dict with at least a 'content' field containing model output."""


class OpenAIClient(LLMClient):
    """OpenAI-compatible client (works with GPT, DeepSeek, Moonshot, etc)."""

    def __init__(self, api_key: Optional[str] = None, base_url: Optional[str] = None, model: str = "gpt-4o-mini") -> None:
        self.api_key = api_key or ""
        self.base_url = base_url
        self.model = model
        self._client = None
        self._legacy = None

        try:
            # Try modern OpenAI v1.x client
            from openai import OpenAI
            self._client = OpenAI(api_key=self.api_key, base_url=self.base_url)
        except ImportError:
            # Fallback to legacy openai v0.x
            import openai
            self._legacy = openai
            self._legacy.api_key = self.api_key
            if self.base_url:
                self._legacy.api_base = self.base_url

    def chat(self, messages: List[Dict[str, str]], **kwargs) -> Dict[str, Any]:
        if self._client:
            response = self._client.chat.completions.create(
                model=self.model,
                messages=messages,
                **kwargs,
            )
            content = response.choices[0].message.content
        else:
            response = self._legacy.ChatCompletion.create(
                model=self.model,
                messages=messages,
                **kwargs,
            )
            content = response["choices"][0]["message"]["content"]
        return {"content": content}


class GeminiClient(LLMClient):
    """Client for Google Gemini models via google-generativeai SDK."""

    def __init__(self, api_key: Optional[str] = None, model: str = "models/gemini-2.5-pro") -> None:
        try:
            import google.generativeai as genai
            self._genai = genai
            self._genai.configure(api_key=api_key)
            self.model_name = model if model.startswith("models/") else f"models/{model}"
        except ImportError:
            raise ImportError("Google Generative AI SDK not found. Please run: pip install google-generativeai")

    def chat(self, messages: List[Dict[str, str]], **kwargs) -> Dict[str, Any]:
        call_kwargs = dict(kwargs)
        temperature = call_kwargs.pop("temperature", None)
        top_p = call_kwargs.pop("top_p", None)
        response_format = call_kwargs.pop("response_format", None)
        generation_config: Dict[str, Any] = {}

        if temperature is not None:
            generation_config["temperature"] = temperature
        if top_p is not None:
            generation_config["top_p"] = top_p
        if isinstance(response_format, dict) and response_format.get("type") == "json_object":
            generation_config["response_mime_type"] = "application/json"

        model = self._genai.GenerativeModel(
            self.model_name,
            generation_config=generation_config or None,
        )
        
        # Simple conversion of chat history to prompt for Gemini
        # (For more complex history, use model.start_chat)
        full_prompt = ""
        for msg in messages:
            role = msg.get("role", "user")
            content = msg.get("content", "")
            full_prompt += f"{role}: {content}\n"
            
        max_retries = 10
        base_delay = 5
        
        for attempt in range(max_retries):
            try:
                response = model.generate_content(full_prompt, **call_kwargs)
                return {"content": response.text}
            except Exception as e:
                # Check for ResourceExhausted (429)
                if "429" in str(e) or "ResourceExhausted" in str(e):
                    if attempt < max_retries - 1:
                        sleep_time = base_delay * (1.5 ** attempt)
                        print(f"Rate limit hit. Retrying in {sleep_time:.1f}s...")
                        time.sleep(sleep_time)
                        continue
                raise e
        return {"content": ""}



class MockClient(LLMClient):
    """Offline/test client that returns deterministic JSON snippets."""

    def chat(self, messages: List[Dict[str, str]], **kwargs) -> Dict[str, Any]:
        content = messages[-1]["content"] if messages else ""
        prompt_type = self._detect_prompt_type(content)

        if prompt_type == "typing":
            payload = self._mock_page_type_response(content)
        elif prompt_type == "intent":
            payload = {
                "intent_type": "extract_info",
                "requested_fields": ["title", "content"],
            }
        elif prompt_type == "strategy":
            payload = {
                "field_selectors": {
                    "title": "h1",
                    "date": "time",
                    "content": "p",
                },
                "field_methods": {
                    "title": "css",
                    "date": "css",
                    "content": "css",
                },
                "is_list": False,
                "item_link_selector": None,
                "pagination_selector": None,
                "max_depth": 1,
                "max_pages": 1,
                "image_selector": None,
                "fallbacks": {},
            }
        else:
            payload = {"message": "mock response"}

        return {"content": json.dumps(payload, ensure_ascii=False)}

    @staticmethod
    def _detect_prompt_type(content: str) -> str:
        lowered = content.lower()
        if "field_selectors" in lowered or "抽取策略" in content:
            return "strategy"
        if "intent_type" in lowered or "任务类型" in content:
            return "intent"
        if "page_type" in lowered or "页面类型" in content:
            return "typing"
        return "unknown"

    @staticmethod
    def _mock_page_type_response(content: str) -> Dict[str, Any]:
        # 简化版：仅用于测试，优先根据测试中注入的 "TEST_PAGE_TYPE:xxx" 标记决定页面类型
        # 找不到标记时，统一返回 news，避免因中文关键词微调导致测试不稳定
        lowered = content.lower()
        marker = "test_page_type:"
        idx = lowered.find(marker)
        if idx != -1:
            value = lowered[idx + len(marker) :].split()[0].strip().strip("\n\r,{}]")
            page_type = value or "news"
        else:
            page_type = "news"

        return {
            "page_type": page_type,
            "confidence": 0.99,
            "suggested_fields": ["title", "date", "content"],
        }
