# -*- coding: utf-8 -*-
"""Agent 核心:消息历史管理 + function call 循环 + 流式输出。

通过 AgentCallbacks 回调向 UI 层通报事件,core 完全不依赖任何 UI 库。
"""
from __future__ import annotations

import json
from dataclasses import dataclass, field
from pathlib import Path
from typing import Callable, Optional

from .llm import LLMClient
from .mcp_client import McpManager, load_mcp_config
from .skills import discover_skills, build_skills_prompt
from .tools import TOOL_MAP, TOOL_SCHEMAS, skill_tools, register_mcp_tools
from . import context as ctx
from .tools import context_tools


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
    on_context_usage:  Optional[Callable[[dict], None]] = None               # 上下文占用状态(每次 LLM 响应后)


DEFAULT_SYSTEM = (
    "你是一个全能本地智能助手,可以调用以下工具:\n"
    "  - 系统工具: getDate(日期时间)、isLeapYear(闰年)、getCWD(当前目录)、getFileType(文件扩展名)\n"
    "  - 文件工具: listDir、readFile、createFile、editFile、createDir、deleteDir、deleteFile、rename\n"
    "  - 网络工具: searchWeb(百度搜索实时信息)、fetchWeb(抓取网页正文转 Markdown)\n"
    "  - 命令行: runCommand(执行本地 python/git 等命令)\n"
    "  - Skill 动态加载: loadSkill(加载 .agents/skills 下的 Skill 完整说明或附属文件)\n"
    "  - Skill 创建: createSkill(按 Agent Skills 规范生成 .agents/skills/<name>/SKILL.md)\n"
    "  - 历史上下文检索: recallContext(在 .agents/context 的压缩归档中按关键词查找原始记录)\n"
    "回答要简洁。调用工具时严格按 schema 提供参数。"
    "区分意图:用户要写通知、审代码等具体任务时,先用 loadSkill 加载最匹配的 Skill 并按其规则执行,"
    "不要为此新建 Skill;只有用户明确要求“新建/创建一个技能”时才调用 createSkill。"
    "创建 Skill 时必须调用 createSkill 工具完成创建,不要把 SKILL.md 的 YAML 内容当作正文打印给用户;"
    "skillContext 里 frontmatter 的 name 必须与参数 name 完全相同(都用小写英文字母、数字和连字符,不要用下划线);"
    "如还需 references/、scripts/ 等目录或辅助文件,创建完 SKILL.md 后继续用 createDir / createFile 完成。"
    "回答中可以引用搜索结果的来源 URL,抓取的网页内容用 Markdown 呈现。"
)


@dataclass
class Agent:
    """对话 + 工具调用 Agent。同一个 Agent 实例保留完整对话历史。"""
    llm: LLMClient
    system_prompt: str = ""          # 留空则自动使用 DEFAULT_SYSTEM + Skill 列表
    project_root: str = ""           # 留空则自动使用当前工作目录
    callbacks: AgentCallbacks = field(default_factory=AgentCallbacks)
    max_tool_rounds: int = 16

    def __post_init__(self):
        # 1. 确定项目根目录
        root = Path(self.project_root) if self.project_root else Path.cwd()
        root = root.resolve()
        self.root = root
        skill_tools.set_project_root(root)
        context_tools.set_project_root(root)

        # 2. 发现 Skill,注入 System Prompt
        discovered = discover_skills(root)
        skill_prompt = build_skills_prompt(discovered)

        # 3. 加载 .mcp.json,连接 MCP Server 并注册其工具
        self.mcp_errors: list[str] = []
        mcp_cfg = load_mcp_config(root)
        if mcp_cfg:
            try:
                mgr = McpManager(mcp_cfg)
                self.mcp_errors = mgr.bootstrap()
                n = register_mcp_tools(mgr)
                if n:
                    mcp_names = ", ".join(
                        s["function"]["name"] for s in mgr.schemas[:10]
                    )
                    more = f" 等{len(mgr.schemas)}个" if len(mgr.schemas) > 10 else ""
                    skill_prompt = (
                        f"已连接 MCP Server,以下工具可直接调用(名称形如 服务器__工具):\n"
                        f"  {mcp_names}{more}\n\n" + skill_prompt
                    )
                for err in self.mcp_errors:
                    if self.callbacks.on_error:
                        self.callbacks.on_error(err)
            except Exception as e:
                self.mcp_errors.append(f"MCP 初始化失败: {e}")
                if self.callbacks.on_error:
                    self.callbacks.on_error(f"MCP 初始化失败: {e}")

        base = self.system_prompt or DEFAULT_SYSTEM
        final_prompt = (base + "\n\n" + skill_prompt) if skill_prompt else base
        self.messages: list[dict] = [
            {"role": "system", "content": final_prompt}
        ]

        # 4. 上下文监控状态
        self.context_window: int = getattr(self.llm.cfg, "context_window", ctx.DEFAULT_CONTEXT_WINDOW)
        self.context_window_is_default: bool = getattr(
            self.llm.cfg, "context_window_is_default", True
        )
        self._api_tokens: int = 0        # 模型 API 最近一次报告的 total_tokens
        self.compacting: bool = False    # 压缩进行中:禁止接收新任务/调用工具

    # ---------- 公开 API ----------
    def reset(self):
        """清空对话历史(保留 system)。"""
        self.messages = self.messages[:1]
        self._api_tokens = 0

    # ---------- 上下文监控 ----------
    def context_status(self) -> dict:
        """当前上下文占用情况。Token 数取「估算值」与「API 报告值」较大者。"""
        estimated = ctx.conversation_tokens(self.messages)
        used = max(estimated, self._api_tokens)
        window = self.context_window or ctx.DEFAULT_CONTEXT_WINDOW
        percent = used / window if window else 0.0
        return {
            "used": used,
            "window": window,
            "percent": percent,
            "is_default": self.context_window_is_default,
            "exceeded": percent >= ctx.COMPACT_RATIO,
        }

    def is_context_full(self) -> bool:
        """是否已达到压缩阈值(80%),此时应暂停接收普通提示词。"""
        return self.context_status()["exceeded"]

    # ---------- 上下文压缩 ----------
    def compact(self) -> dict:
        """手动压缩上下文:归档原始记录 -> LLM 生成摘要 -> 用摘要替换历史。

        返回 {"ok": True, "archive_id", "path", "summary"} 或 {"ok": False, "error"}。
        任何一步失败都保留原有上下文,允许重新执行。
        """
        cb = self.callbacks
        if self.compacting:
            return {"ok": False, "error": "上下文压缩已在进行中"}
        if len(self.messages) <= 1:
            return {"ok": False, "error": "当前没有可压缩的历史上下文"}

        self.compacting = True
        try:
            # 1) 先归档完整原始上下文,落盘成功才继续
            archive_id, path = ctx.archive_messages(self.root, self.messages)

            # 2) 只用 LLM 生成摘要(不挂 tools)
            transcript = ctx.render_transcript(self.messages[1:])
            resp = self.llm.chat([
                {"role": "system", "content": ctx.COMPACT_PROMPT},
                {"role": "user", "content": transcript + ctx.COMPACT_USER_SUFFIX},
            ])
            summary = (resp["message"].get("content") or "").strip()
            if not summary:
                raise RuntimeError("LLM 返回空摘要,已保留原有上下文")

            # 3) 用摘要替换历史:保留 System Prompt 与工具定义
            system_msg = self.messages[0]
            note = ctx.archive_note(archive_id)
            self.messages = [
                system_msg,
                {"role": "user", "content": f"【上下文压缩摘要】\n\n{summary}\n\n---\n\n{note}"},
            ]
            self._api_tokens = 0
            if cb.on_context_usage:
                cb.on_context_usage(self.context_status())
            return {"ok": True, "archive_id": archive_id, "path": str(path), "summary": summary}
        except Exception as e:
            if cb.on_error:
                cb.on_error(f"上下文压缩失败: {e}")
            return {"ok": False, "error": str(e)}
        finally:
            self.compacting = False

    def chat(self, user_input: str) -> str:
        """发送一条用户消息,返回最终文本回复。可能触发多轮工具调用。"""
        cb = self.callbacks
        # 压缩期间禁止继续处理原有任务
        if self.compacting:
            msg = "上下文压缩正在进行,暂时不能处理新任务,请稍候。"
            if cb.on_error:
                cb.on_error(msg)
            return msg
        # 达到 80% 后暂停接收普通提示词,直到压缩完成
        if self.is_context_full():
            msg = ("上下文已使用超过 80%(达到压缩阈值),已暂停接收新的提示词。"
                   "请先执行 /compact 命令压缩上下文,完成后再继续。")
            if cb.on_user_message:
                cb.on_user_message(user_input)
            if cb.on_error:
                cb.on_error(msg)
            return msg

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
        cb = self.callbacks
        for _ in range(self.max_tool_rounds):
            resp = self.llm.chat(self.messages, tools=TOOL_SCHEMAS)
            msg = resp["message"]
            finish = resp["finish_reason"]

            # 每次 LLM 响应后更新上下文占用:优先用 API 的 usage
            total = (resp.get("usage") or {}).get("total_tokens")
            if isinstance(total, int) and total > 0:
                self._api_tokens = total
            if cb.on_context_usage:
                cb.on_context_usage(self.context_status())

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
        if cb.on_context_usage:
            cb.on_context_usage(self.context_status())
        return text
