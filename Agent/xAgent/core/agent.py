# -*- coding: utf-8 -*-
"""Agent 核心:消息历史管理 + function call 循环 + 流式输出。

通过 AgentCallbacks 回调向 UI 层通报事件,core 完全不依赖任何 UI 库。
"""
from __future__ import annotations

import json
import threading
from dataclasses import dataclass, field
from pathlib import Path
from typing import Callable, Optional

from .config import AppConfig
from .llm import LLMClient
from .mcp_client import McpManager, load_mcp_config
from .skills import discover_skills, build_skills_prompt
from . import session as sess
from . import context as ctx
from .tools import TOOL_MAP, TOOL_SCHEMAS, skill_tools, register_mcp_tools
from .tools import context_tools, cli_tools, run_tool, web_tools


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
    on_mcp_ready:      Optional[Callable[[dict], None]] = None               # MCP 加载完成


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

# 标记:AGENTS.md 注入消息的首行,用于判断本次会话是否已注入
AGENTS_MD_MARKER = "【项目规范 AGENTS.md】"


@dataclass
class Agent:
    """对话 + 工具调用 Agent。同一个 Agent 实例保留完整对话历史。"""
    llm: LLMClient
    system_prompt: str = ""          # 留空则自动使用 DEFAULT_SYSTEM + Skill 列表
    project_root: str = ""           # 留空则自动使用当前工作目录
    callbacks: AgentCallbacks = field(default_factory=AgentCallbacks)
    config: Optional[AppConfig] = None
    auto_load_mcp: bool = True       # False 时由 UI 异步调用 load_mcp()
    max_tool_rounds: Optional[int] = None

    def __post_init__(self):
        # 0. 配置(未显式传入时用 LLM 配置缺省值构造一份)
        self.cfg = self.config or AppConfig(llm=self.llm.cfg)
        cfg = self.cfg

        # 1. 确定项目根目录
        root = Path(self.project_root) if self.project_root else Path.cwd()
        root = root.resolve()
        self.root = root
        skill_tools.set_project_root(root)
        context_tools.set_project_root(root)

        # 2. 把 [tools] 参数注入各工具模块
        cli_tools.configure(cfg.tools.command_timeout, cfg.tools.command_timeout_max,
                            cfg.tools.output_max_chars)
        run_tool.configure(cfg.tools.run_timeout, cfg.tools.run_timeout_max,
                           cfg.tools.output_max_chars)
        web_tools.configure(cfg.tools.search_top_k, cfg.tools.search_top_k_max,
                            cfg.tools.fetch_max_chars)
        context_tools.configure(cfg.tools.recall_max_results, cfg.tools.recall_snippet_chars,
                                cfg.tools.recall_max_output)

        # 3. 发现 Skill,注入 System Prompt
        discovered = discover_skills(root)
        skill_prompt = build_skills_prompt(discovered)
        base = self.system_prompt or DEFAULT_SYSTEM
        self._base_prompt = (base + "\n\n" + skill_prompt) if skill_prompt else base

        # 4. 上下文监控状态
        self.context_window: int = cfg.llm.context_window or ctx.DEFAULT_CONTEXT_WINDOW
        self.context_window_is_default: bool = cfg.llm.context_window_is_default
        self.compact_ratio: float = cfg.agent.compact_ratio
        self.summary_target_tokens: int = cfg.agent.summary_target_tokens
        self._api_tokens: int = 0        # 模型 API 最近一次报告的 total_tokens
        self.compacting: bool = False    # 压缩进行中:禁止接收新任务/调用工具

        # 5. MCP 状态(实际连接可放到 UI 线程之外异步执行)
        self.mcp_servers: list[dict] = []
        self.mcp_errors: list[str] = []
        self._mcp_loaded: bool = False
        self._mcp_loading: bool = False
        self._mcp_lock = threading.Lock()

        # 6. 新建会话 + 注入 AGENTS.md
        self.messages: list[dict] = [{"role": "system", "content": self._base_prompt}]
        self.agents_md_injected = False
        self.start_session()

        if self.auto_load_mcp:
            self.load_mcp()

    # ---------- MCP ----------
    def load_mcp(self) -> dict:
        """连接 .mcp.json 中的 MCP Server 并注册工具。

        可在后台线程调用(耗时主要花在网络上);重复/并发调用直接返回当前状态。
        """
        with self._mcp_lock:
            # 已加载完成,或另一个线程正在加载:直接返回当前状态
            if self._mcp_loaded or self._mcp_loading:
                return self.mcp_info()
            self._mcp_loading = True

        try:
            self._bootstrap_mcp()
        finally:
            with self._mcp_lock:
                self._mcp_loading = False
                self._mcp_loaded = True

        for err in self.mcp_errors:
            if self.callbacks.on_error:
                self.callbacks.on_error(err)

        info = self.mcp_info()
        if self.callbacks.on_mcp_ready:
            self.callbacks.on_mcp_ready(info)
        return info

    def _bootstrap_mcp(self) -> None:
        """真正执行连接与工具注册;异常全部收敛到 mcp_errors,不向上抛出。"""
        mcp_cfg = load_mcp_config(self.root)
        if not mcp_cfg:
            return

        try:
            mgr = McpManager(mcp_cfg)
            errors = mgr.bootstrap()
            self.mcp_errors = list(errors)
            register_mcp_tools(mgr)

            # 整理每个服务器的工具,供 TUI 侧边栏展示
            server_tools = mgr.list_server_tools()
            self.mcp_servers = [
                {
                    "name": name,
                    "tools": server_tools.get(name, []),
                    "error": next((e for e in errors if f"'{name}'" in e), ""),
                }
                for name in mgr.servers
            ]

            # 把 MCP 工具清单补进 System Prompt(只补一次)
            names = [s["function"]["name"] for s in mgr.schemas]
            if names and "已连接 MCP Server" not in self.messages[0]["content"]:
                more = f" 等{len(names)}个" if len(names) > 10 else ""
                block = (
                    "已连接 MCP Server,以下工具可直接调用(名称形如 服务器__工具):\n"
                    f"  {', '.join(names[:10])}{more}"
                )
                self.messages[0]["content"] = self.messages[0]["content"] + "\n\n" + block
        except Exception as e:  # noqa: BLE001
            self.mcp_errors.append(f"MCP 初始化失败: {e}")

    def mcp_info(self) -> dict:
        """供侧边栏渲染的 MCP 状态。"""
        return {
            "loaded": self._mcp_loaded,
            "loading": self._mcp_loading,
            "servers": self.mcp_servers,
            "errors": self.mcp_errors,
        }

    # ---------- 会话管理 ----------
    def start_session(self, sid: str | None = None) -> str:
        """开启新会话:保留 System Prompt,清空历史,注入 AGENTS.md 并落盘。"""
        system_msg = self.messages[0]
        self.messages = [system_msg]
        self._api_tokens = 0
        self.session_id = sid or sess.new_session_id()
        sess.create_session(self.root, self.session_id, {
            "model": self.llm.cfg.model,
            "agents_md": bool(self.cfg.agent.agents_md),
        })
        self.agents_md_injected = False
        self._inject_agents_md()
        return self.session_id

    def _inject_agents_md(self) -> None:
        """会话首次加载时注入项目根目录的 AGENTS.md(一次注入,后续轮次复用)。"""
        if not self.cfg.agent.agents_md or self.agents_md_injected:
            return
        path = self.root / "AGENTS.md"
        if not path.is_file():
            return
        try:
            content = path.read_text(encoding="utf-8").strip()
        except OSError as e:
            if self.callbacks.on_error:
                self.callbacks.on_error(f"读取 AGENTS.md 失败: {e}")
            return
        if not content:
            return
        msg = {
            "role": "user",
            "content": (
                f"{AGENTS_MD_MARKER} 以下内容来自项目根目录的 AGENTS.md,"
                "是本项目必须遵守的规范,请在后续所有工作中遵守:\n\n" + content
            ),
        }
        self.messages.append(msg)
        sess.append_record(self.root, self.session_id, msg)
        self.agents_md_injected = True

    def save_session(self) -> str:
        """保存当前会话(重写事件日志,保证与内存一致)。"""
        path = sess.save_session(
            self.root, self.session_id, self.messages,
            meta={"agents_md_injected": self.agents_md_injected, "model": self.llm.cfg.model},
        )
        return str(path)

    def resume_session(self, sid: str) -> int:
        """恢复历史会话,返回恢复后的消息条数。"""
        meta, messages = sess.load_session(self.root, sid)
        system_msg = self.messages[0]
        restored = [m for m in messages if m.get("role") != "system"]
        self.messages = [system_msg] + restored
        self.session_id = sid
        self._api_tokens = 0
        self.agents_md_injected = any(
            AGENTS_MD_MARKER in str(m.get("content") or "") for m in self.messages
        )
        # 老会话日志里可能没有注入记录:恢复时补一次(幂等,已有则跳过)
        self._inject_agents_md()
        return len(self.messages)

    def list_sessions(self) -> list[dict]:
        return sess.list_sessions(self.root)

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
            "exceeded": percent >= self.compact_ratio,
        }

    def is_context_full(self) -> bool:
        """是否已达到压缩阈值(默认 80%),此时应暂停接收普通提示词。"""
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
                {"role": "system", "content": ctx.compact_prompt(self.summary_target_tokens)},
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
            # 事件日志与内存同步(压缩后历史被替换)
            self.save_session()
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
        # 达到阈值后暂停接收普通提示词,直到压缩完成
        if self.is_context_full():
            threshold = int(self.compact_ratio * 100)
            msg = (f"上下文已使用超过 {threshold}%(达到压缩阈值),已暂停接收新的提示词。"
                   "请先执行 /compact 命令压缩上下文,完成后再继续。")
            if cb.on_user_message:
                cb.on_user_message(user_input)
            if cb.on_error:
                cb.on_error(msg)
            return msg

        if not self._mcp_loaded:
            self.load_mcp()

        if cb.on_user_message:
            cb.on_user_message(user_input)
        self.messages.append({"role": "user", "content": user_input})
        sess.append_record(self.root, self.session_id, {"role": "user", "content": user_input})

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
        rounds = self.max_tool_rounds or self.cfg.agent.max_tool_rounds
        for _ in range(rounds):
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
                record = {
                    "role": "assistant",
                    "content": msg.get("content") or "",
                    "tool_calls": msg["tool_calls"],
                }
                self.messages.append(record)
                sess.append_record(self.root, self.session_id, record)
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
            record = {
                "role": "tool",
                "tool_call_id": tc["id"],
                "name": name,
                "content": result,
            }
            self.messages.append(record)
            sess.append_record(self.root, self.session_id, record)

    def _stream_final(self) -> str:
        cb = self.callbacks
        parts: list[str] = []
        for piece in self.llm.chat_stream(self.messages):
            parts.append(piece)
            if cb.on_token:
                cb.on_token(piece)
        text = "".join(parts)
        self.messages.append({"role": "assistant", "content": text})
        sess.append_record(self.root, self.session_id, {"role": "assistant", "content": text})
        if cb.on_context_usage:
            cb.on_context_usage(self.context_status())
        return text
