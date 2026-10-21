# -*- coding: utf-8 -*-
"""LLM 客户端封装(智谱 BigModel OpenAI 兼容接口)。"""
import json
from typing import Iterator

import requests

from .config import LLMConfig


class LLMClient:
    """对 OpenAI 兼容接口的最小封装:非流式请求 + 流式请求。"""

    def __init__(self, cfg: LLMConfig, timeout: int = 60):
        self.cfg = cfg
        self.timeout = timeout
        self._url = f"{cfg.base_url.rstrip('/')}/chat/completions"
        self._headers = {
            "Authorization": f"Bearer {cfg.api_key}",
            "Content-Type": "application/json",
        }

    # ---------- 非流式:用于工具调用决策 ----------
    def chat(self, messages: list[dict], tools: list[dict] | None = None) -> dict:
        """返回完整 message dict (含 content / tool_calls / finish_reason)。"""
        payload = {
            "model": self.cfg.model,
            "messages": messages,
            "stream": False,
        }
        if tools:
            payload["tools"] = tools
            payload["tool_choice"] = "auto"
        r = requests.post(self._url, headers=self._headers, json=payload, timeout=self.timeout)
        r.raise_for_status()
        data = r.json()
        choice = data["choices"][0]
        return {
            "message": choice["message"],
            "finish_reason": choice.get("finish_reason", "stop"),
        }

    # ---------- 流式:输出最终回复 ----------
    def chat_stream(self, messages: list[dict]) -> Iterator[str]:
        """流式返回 assistant 内容片段。"""
        payload = {
            "model": self.cfg.model,
            "messages": messages,
            "stream": True,
        }
        with requests.post(self._url, headers=self._headers, json=payload,
                           stream=True, timeout=self.timeout) as r:
            r.raise_for_status()
            for line in r.iter_lines(decode_unicode=True):
                if not line or not line.startswith("data:"):
                    continue
                data = line[len("data:"):].strip()
                if data == "[DONE]":
                    break
                try:
                    chunk = json.loads(data)
                except json.JSONDecodeError:
                    continue
                delta = chunk["choices"][0].get("delta", {})
                piece = delta.get("content")
                if piece:
                    yield piece
