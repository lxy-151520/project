# -*- coding: utf-8 -*-
"""Agent 核心:消息历史管理 + function call 循环 + 流式输出。

通过 AgentCallbacks 回调向 UI 层通报事件,core 完全不依赖任何 UI 库。
"""
from __future__ import annotations

import json
from dataclasses import dataclass, field
from typing import Callable, Optional

from .llm import LLMClient
from .tools import TOOL_MAP, TOOL_SCHEMAS


# ---------- UI 事件回调(所有钩子都是可选的) ----------
@dataclass
class AgentCallbacks:
    """UI 层订阅这些回调来渲染过程。所有回调都在工作线程触发,UI 需自行 marshal 到主线程。"""
    on_user_message:   Optional[Callable[[str], None]] = None                # 用户消息
    on_tool_call:      Optional[Callable[[str, dict], None]] = None          # (name, args)
    on_tool_result:    Optional[Callable[[str, str], None]] = None           # (name, result)
    on_token:          Optional[Callable[[str], None]] = None                # 流式 token
    on_response_done:  Optional[Callable[[str], None]] = None                # 完整回复
    on_error:          Optional[Callable[[str], None]] = None                # 错误消息


DEFAULT_SYSTEM = (
    "你是一个全能本地智能助手,可以调用以下工具:\n"
    "  - 系统工具: getDate(日期时间)、isLeapYear(闰年)、getCWD(当前目录)、getFileType(文件扩展名)\n"
    "  - 文件工具: listDir、readFile、createFile、editFile、createDir、deleteDir、deleteFile、rename\n"
    "  - 网络工具: searchWeb(百度搜索实时信息)、fetchWeb(抓取网页正文转 Markdown)\n"
    "  - 命令行: runCommand(执行本地 python/git 等命令)\n"
    "回答要简洁。调用工具时严格按 schema 提供参数。"
    "回答中可以引用搜索结果的来源 URL,抓取的网页内容用 Markdown 呈现。"
)


@dataclass
class Agent:
    """对话 + 工具调用 Agent。同一个 Agent 实例保留完整对话历史。"""
    llm: LLMClient
    system_prompt: str = DEFAULT_SYSTEM
    callbacks: AgentCallbacks = field(default_factory=AgentCallbacks)
    max_tool_rounds: int = 8

    def __post_init__(self):
        self.messages: list[dict] = [
            {"role": "system", "content": self.system_prompt}
        ]

    # ---------- 公开 API ----------
    def reset(self):
        """清空对话历史(保留 system)。"""
        self.messages = self.messages[:1]

    def chat(self, user_input: str) -> str:
        """发送一条用户消息,返回最终文本回复。可能触发多轮工具调用。"""
        cb = self.callbacks
        if cb.on_user_message:
            cb.on_user_message(user_input)
        self.messages.append({"role": "user", "content": user_input})

        try:
            final_text = self._loop()
        except Exception as e:
            final_text = f"[错误] {e}"
            if cb.on_error:
                cb.on_error(str(e))

        if cb.on_response_done:
            cb.on_response_done(final_text)
        return final_text

    # ---------- 内部主循环 ----------
    def _loop(self) -> str:
        for _ in range(self.max_tool_rounds):
            resp = self.llm.chat(self.messages, tools=TOOL_SCHEMAS)
            msg = resp["message"]
            finish = resp["finish_reason"]

            if finish == "tool_calls" and msg.get("tool_calls"):
                # 把 assistant 的 tool_calls 加入历史
                self.messages.append({
                    "role": "assistant",
                    "content": msg.get("content") or "",
                    "tool_calls": msg["tool_calls"],
                })
                self._run_tools(msg["tool_calls"])
                continue   # 工具结果回传后再次请求 LLM

            # 没有工具调用 -> 流式输出最终回复
            return self._stream_final()
        return "(已达到最大工具调用轮次)"

    def _run_tools(self, tool_calls: list[dict]):
        cb = self.callbacks
        for tc in tool_calls:
            name = tc["function"]["name"]
            args_raw = tc["function"].get("arguments") or "{}"
            try:
                args = json.loads(args_raw)
            except json.JSONDecodeError:
                args = {}
            if cb.on_tool_call:
                cb.on_tool_call(name, args)

            fn = TOOL_MAP.get(name)
            if fn is None:
                result = f"未知工具: {name}"
            else:
                try:
                    result = str(fn(**args))
                except Exception as e:
                    result = f"工具执行异常: {e}"

            if cb.on_tool_result:
                cb.on_tool_result(name, result)
            self.messages.append({
                "role": "tool",
                "tool_call_id": tc["id"],
                "name": name,
                "content": result,
            })

    def _stream_final(self) -> str:
        cb = self.callbacks
        parts: list[str] = []
        for piece in self.llm.chat_stream(self.messages):
            parts.append(piece)
            if cb.on_token:
                cb.on_token(piece)
        text = "".join(parts)
        self.messages.append({"role": "assistant", "content": text})
        return text
