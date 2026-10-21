# -*- coding: utf-8 -*-
"""命令行界面(CLI):最简 UI 实现,把 Agent 事件直接 print 出来。"""
from __future__ import annotations

import sys

from ..core import Agent, AgentCallbacks, LLMClient, load_config


def build_agent() -> Agent:
    cfg = load_config("config.ini")
    llm = LLMClient(cfg)

    cb = AgentCallbacks(
        on_tool_call=lambda name, args: print(f"  [调用工具] {name}({args})"),
        on_tool_result=lambda name, result: print(f"  [工具返回] {result}"),
        on_token=lambda piece: (print(piece, end="", flush=True)),
        on_error=lambda msg: print(f"[错误] {msg}", file=sys.stderr),
    )
    return Agent(llm=llm, callbacks=cb)


def main():
    agent = build_agent()
    print("xAgent CLI (输入 exit 退出)")
    print("=" * 40)
    while True:
        try:
            user = input("\n你: ").strip()
        except (EOFError, KeyboardInterrupt):
            print("\n再见!")
            break
        if not user:
            continue
        if user.lower() in ("exit", "quit"):
            print("再见!")
            break
        print("AI: ", end="", flush=True)
        agent.chat(user)
        print()   # 流式输出结束后换行


if __name__ == "__main__":
    main()
