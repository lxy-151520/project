# -*- coding: utf-8 -*-
"""Textual TUI 界面:左侧 MCP 面板 + 消息区 + 斜杠命令补全。"""
from __future__ import annotations

import sys
import traceback
from pathlib import Path

from textual.app import App, ComposeResult
from textual.binding import Binding
from textual.containers import Horizontal, Vertical, VerticalScroll
from textual.screen import ModalScreen
from textual.widgets import Button, Footer, Header, Input, ListItem, ListView, Static

from ..core import Agent, AgentCallbacks, LLMClient, ensure_config, load_config
from ..core.config import DEFAULTS
from ..core.tools import TOOL_MAP


def _esc(value) -> str:
    """把动态内容变成安全的 markup 字面量。

    注意不能用 rich.markup.escape:它只转义"像标签"的 [ (后跟字母/#/@),
    而 dict/list 的 repr(如 ['create', 'demo.pptx']) 里 [ 后面是引号,会漏掉,
    导致 MarkupError。这里无条件转义反斜杠和所有 [。
    """
    return str(value).replace("\\", "\\\\").replace("[", "\\[")


# ---------- 斜杠命令表 ----------
COMMANDS: list[tuple[str, str]] = [
    ("/new",     "新建会话,并自动保存当前会话历史"),
    ("/resume",  "恢复历史会话(↑↓ 选择,Enter 确认,ESC 取消)"),
    ("/save",    "保存当前会话到 .agents/sessions"),
    ("/compact", "压缩上下文,并把原始记录归档到 .agents/context"),
    ("/context", "查看当前上下文占用详情"),
    ("/tools",   "列出当前可用的 Function Calling 工具"),
    ("/mcp",     "列出已连接的 MCP 服务器与其工具"),
    ("/clear",   "清空屏幕显示(不清空会话记忆)"),
    ("/help",    "显示所有斜杠命令"),
    ("/quit",    "退出 xAgent"),
]


def _find_config_ini() -> Path:
    """定位 config.ini:打包目录 → xAgent 源码目录 → 当前工作目录。"""
    candidates: list[Path] = []
    if getattr(sys, "frozen", False):
        candidates.append(Path(sys.executable).resolve().parent / "config.ini")
    candidates.append(Path(__file__).resolve().parent.parent / "config.ini")
    candidates.append(Path.cwd() / "config.ini")
    for p in candidates:
        if p.exists():
            return p
    return candidates[-1]


# ---------- 会话列表面板(/resume) ----------
class SessionListScreen(ModalScreen[str | None]):
    """历史会话列表:↑↓ 选择,Enter 恢复,ESC 取消。"""

    BINDINGS = [Binding("escape", "cancel", "取消")]

    CSS = """
    SessionListScreen { align: center middle; }
    #session_box {
        width: 80%; height: 70%;
        border: thick $accent; background: $panel;
        padding: 1 2;
    }
    #session_hint { color: $text-muted; margin-bottom: 1; }
    """

    def __init__(self, sessions: list[dict]):
        super().__init__()
        self._sessions = sessions

    def compose(self) -> ComposeResult:
        items = []
        for s in self._sessions:
            label = f"[bold]{s['id']}[/]  [dim]{s['updated_at']}  {s['count']} 条[/]"
            if s.get("preview"):
                label += f"\n  [dim]{_esc(s['preview'])}[/]"
            items.append(ListItem(Static(label, markup=True), id=f"sid-{s['id']}"))
        with Vertical(id="session_box"):
            yield Static("[bold]历史会话[/]  (↑↓ 选择 · Enter 恢复 · ESC 取消)", id="session_hint")
            yield ListView(*items, id="session_list")

    def on_mount(self):
        self.query_one("#session_list", ListView).focus()

    def on_list_view_selected(self, event: ListView.Selected) -> None:
        item_id = event.item.id or ""
        self.dismiss(item_id.removeprefix("sid-"))

    def action_cancel(self) -> None:
        self.dismiss(None)


# ---------- 配置缺失提示面板 ----------
class ConfigRequiredScreen(ModalScreen[None]):
    """config.ini 已生成但没有可用配置时弹出,提示修改后重启。"""

    BINDINGS = [Binding("escape", "close", "退出")]

    CSS = """
    ConfigRequiredScreen { align: center middle; }
    #cfg_box {
        width: 80%; height: auto;
        border: thick $warning; background: $panel;
        padding: 1 2;
    }
    """

    def __init__(self, path: Path):
        super().__init__()
        self._path = path

    def compose(self) -> ComposeResult:
        with Vertical(id="cfg_box"):
            yield Static("[bold yellow]⚠ 已生成配置文件,请先完成配置[/]")
            yield Static(f"\n已创建: {_esc(self._path)}\n", markup=False)
            yield Static(
                "配置文件里目前是 mock 信息,直接启动无法正常工作。\n"
                "请打开该文件,把 [llm] 段的 api_key 换成你自己的 Key"
                "(其余项可按需修改),保存后重新启动 xAgent。\n\n"
                "• api_key:必填,否则无法调用模型\n"
                "• context_window:留空表示按 128k(默认)处理\n"
                "• [search] baidu_qianfan_api_key:可选,搜索功能需要\n",
                markup=False,
            )
            yield Button("退出", id="cfg_exit", variant="error")

    def on_button_pressed(self, event: Button.Pressed) -> None:
        self.app.exit()

    def action_close(self) -> None:
        self.app.exit()


class XAgentApp(App):
    """xAgent Textual 界面。"""

    CSS = """
    #body { height: 1fr; }
    #sidebar {
        width: 34;
        border-right: solid $primary;
        padding: 0 1;
    }
    #sidebar_scroll { height: 1fr; }
    #main { width: 1fr; }
    #log {
        height: 1fr;
        border: solid $primary;
        padding: 0 1;
    }
    #palette {
        height: 0;
        display: none;
        border: solid $accent;
        padding: 0 1;
    }
    #ctxbar {
        height: 1;
        background: $panel;
        padding: 0 1;
    }
    #input {
        height: 3;
        margin: 0 1 0 1;
    }
    """

    BINDINGS = [
        Binding("ctrl+c", "quit", "退出"),
        Binding("ctrl+l", "clear", "清屏"),
    ]

    def __init__(self):
        super().__init__()
        self._init_error: str | None = None
        self._config_created = False
        self._config_path: Path | None = None
        self.agent: Agent | None = None
        # 配置加载前的兜底值(与 core.config.DEFAULTS 保持一致)
        self.palette_max = DEFAULTS["tui"]["palette_height"]
        self.sidebar_width = DEFAULTS["tui"]["sidebar_width"]
        self.tool_preview_chars = DEFAULTS["agent"]["tool_preview_chars"]
        try:
            ini_path = _find_config_ini()
            self._config_path = ini_path
            # 配置文件不存在 -> 生成模板并弹窗提示
            if ensure_config(ini_path):
                self._config_created = True
            else:
                cfg = load_config(ini_path)
                self.palette_max = max(2, cfg.tui.palette_height)
                self.sidebar_width = max(20, cfg.tui.sidebar_width)
                self.tool_preview_chars = cfg.agent.tool_preview_chars
                llm = LLMClient(cfg.llm)
                cb = AgentCallbacks(
                    on_tool_call=self._ev_tool_call,
                    on_tool_result=self._ev_tool_result,
                    on_token=self._ev_token,
                    on_response_done=self._ev_response_done,
                    on_error=self._ev_error,
                    on_context_usage=self._ev_context_usage,
                    on_mcp_ready=self._ev_mcp_ready,
                )
                # MCP 由 UI 在后台异步加载,先让界面出来
                self.agent = Agent(llm=llm, config=cfg, callbacks=cb, auto_load_mcp=False)
        except Exception as e:
            tb = traceback.format_exc()
            self._init_error = f"{e}\n\n{tb}"
            print("=" * 50, file=sys.stderr)
            print(f"[xAgent 启动失败] {e}", file=sys.stderr)
            traceback.print_exc()
            print("=" * 50, file=sys.stderr)
            try:
                log_path = Path.cwd() / "_xagent_init_error.log"
                log_path.write_text(f"[{ini_path}]\n{self._init_error}", encoding="utf-8")
            except Exception:
                pass

        self._streaming_tokens: list[str] = []
        self._streaming_line_open = False
        self._stream_text: str = ""
        self._stream_static: Static | None = None
        # 上下文压缩状态
        self._compacting = False
        self._warned_full = False
        # 斜杠命令补全
        self._palette_items: list[tuple[str, str]] = []
        self._palette_index = 0
        self._palette_visible = False
        self._suppress_palette = False

    # ---------- UI 布局 ----------
    def compose(self) -> ComposeResult:
        yield Header(show_clock=True, name="xAgent")
        with Horizontal(id="body"):
            with Vertical(id="sidebar"):
                yield Static("[bold]MCP Servers[/]", id="sidebar_title")
                with VerticalScroll(id="sidebar_scroll"):
                    yield Static("[dim]等待加载…[/]", id="sidebar_body")
            with Vertical(id="main"):
                yield VerticalScroll(id="log")
                yield VerticalScroll(id="palette")
                yield Static("上下文: 未就绪", id="ctxbar")
                yield Input(placeholder="输入消息,Enter 发送…  输入 / 查看命令", id="input")
        yield Footer()

    def on_mount(self):
        self.title = "xAgent TUI"
        self.sub_title = "core/UI 分离架构演示"
        sidebar = self.query_one("#sidebar")
        sidebar.styles.width = self.sidebar_width
        self.query_one("#input", Input).focus()

        if self._config_created:
            self._log("[bold yellow]⚠ 未找到 config.ini,已生成配置模板[/]")
            self._log(f"[dim]路径: {_esc(self._config_path)}[/]")
            if self._config_path:
                self.push_screen(ConfigRequiredScreen(self._config_path))
            return

        if self.agent is None:
            self._log("[bold red]⚠ Agent 初始化失败[/] 详细错误如下 (也已写入 _xagent_init_error.log):")
            if self._init_error:
                self._log(f"[dim]{_esc(self._init_error)}[/]")
            return

        self._log("[bold cyan]xAgent 已启动[/]  本地工具: getDate / isLeapYear / 文件操作 / searchWeb / fetchWeb / Run / loadSkill / createSkill / recallContext")
        self._log("[dim]输入 [bold]/help[/] 查看全部斜杠命令;输入 [bold]/compact[/] 手动压缩上下文[/]")
        if self.agent.agents_md_injected:
            self._log("[dim]已加载项目根目录的 AGENTS.md 作为本次会话的规范[/]")
        self._log(f"[dim]会话编号: {_esc(self.agent.session_id)}[/]")
        self._update_ctxbar()
        # 异步加载 MCP:先出界面,连上后再刷新左侧面板
        self.run_worker(self._mcp_job, thread=True, group="mcp")

    # ---------- MCP 异步加载 ----------
    def _mcp_job(self):
        if self.agent is None:
            return
        info = self.agent.load_mcp()
        self.call_from_thread(self._render_sidebar, info)

    def _ev_mcp_ready(self, info: dict):
        self.call_from_thread(self._render_sidebar, info)

    def _render_sidebar(self, info: dict | None = None):
        body = self.query_one("#sidebar_body", Static)
        info = info or (self.agent.mcp_info() if self.agent else {"loaded": False, "servers": [], "errors": []})
        if not info.get("loaded"):
            body.update("[dim]⟳ 正在连接 MCP 服务器…[/]")
            return
        lines: list[str] = []
        servers = info.get("servers") or []
        if not servers:
            lines.append("[dim]未配置 MCP 服务器(.mcp.json)[/]")
        for srv in servers:
            if srv.get("error"):
                lines.append(f"[red]✗[/] [bold]{_esc(srv['name'])}[/]")
                lines.append(f"  [dim red]{_esc(str(srv['error'])[:120])}[/]")
                continue
            tools = srv.get("tools") or []
            lines.append(f"[green]✓[/] [bold]{_esc(srv['name'])}[/] [dim]({len(tools)} 个工具)[/]")
            for t in tools[:8]:
                lines.append(f"   [dim]• {_esc(t)}[/]")
            if len(tools) > 8:
                lines.append(f"   [dim]… 其余 {len(tools) - 8} 个[/]")
        lines.append("")
        lines.append(f"[dim]本地工具 {len(TOOL_MAP)} 个[/]")
        body.update("\n".join(lines))

    # ---------- 斜杠命令补全面板 ----------
    def on_input_changed(self, event: Input.Changed) -> None:
        # Tab 补全时是用代码直接改 value,会再次触发 Changed 消息;
        # 用这个开关跳过那一次,避免面板刚隐藏又被重新显示。
        if self._suppress_palette:
            self._suppress_palette = False
            return
        value = event.value
        if not value.startswith("/") or " " in value:
            self._palette_hide()
            return
        query = value[1:].lower()
        items = [(c, d) for c, d in COMMANDS if c[1:].lower().startswith(query)]
        if not items:
            self._palette_hide()
            return
        self._palette_items = items
        if self._palette_index >= len(items):
            self._palette_index = 0
        self._palette_render()

    def _palette_render(self):
        palette = self.query_one("#palette", VerticalScroll)
        palette.remove_children()
        for i, (cmd, desc) in enumerate(self._palette_items):
            marker = "[bold cyan]▶[/]" if i == self._palette_index else " "
            palette.mount(Static(f"{marker} [bold]{_esc(cmd)}[/]  [dim]{_esc(desc)}[/]", markup=True))
        palette.styles.height = min(len(self._palette_items), self.palette_max)
        palette.styles.display = "block"
        self._palette_visible = True

    def _palette_hide(self):
        if self._palette_visible:
            self.query_one("#palette", VerticalScroll).styles.display = "none"
            self._palette_visible = False
            self._palette_index = 0

    def _palette_complete(self):
        if not self._palette_items:
            return
        cmd = self._palette_items[self._palette_index][0]
        inp = self.query_one("#input", Input)
        self._suppress_palette = True
        inp.value = cmd
        inp.cursor_position = len(cmd)
        self._palette_hide()

    def on_key(self, event):
        if not self._palette_visible:
            return
        if event.key in ("up", "down"):
            delta = -1 if event.key == "up" else 1
            self._palette_index = (self._palette_index + delta) % len(self._palette_items)
            self._palette_render()
            event.stop()
        elif event.key == "tab":
            self._palette_complete()
            event.stop()
        elif event.key == "escape":
            self._palette_hide()
            event.stop()

    # ---------- 输入提交 ----------
    def on_input_submitted(self, event: Input.Submitted):
        text = event.value.strip()
        if not text:
            return
        event.input.value = ""
        self._palette_hide()

        if text.startswith("/"):
            self._handle_command(text)
            return

        if self._compacting:
            self._log("[yellow]上下文压缩进行中,请稍候再输入…[/]")
            return
        if self.agent is None:
            self._log("[bold red]Agent 未就绪[/] 无法处理请求,请检查配置后重启")
            return
        if self.agent.is_context_full():
            threshold = int(self.agent.compact_ratio * 100)
            self._log(
                f"[bold red]⚠ 上下文已占用 {threshold}% 以上,已暂停接收新任务。[/]"
                " 请先执行 [bold]/compact[/] 压缩上下文"
            )
            return

        self._log(f"[bold green]你:[/] {_esc(text)}")
        self._close_stream_line()
        self.run_worker(lambda: self.agent.chat(text), thread=True, exclusive=True, group="chat")

    # ---------- 命令分发 ----------
    def _require_agent(self) -> bool:
        if self.agent is None:
            self._log("[bold red]Agent 未就绪[/] 无法执行该命令")
            return False
        return True

    def _handle_command(self, text: str):
        parts = text.split(maxsplit=1)
        cmd = parts[0].lower()
        known = [c for c, _ in COMMANDS]
        # 允许用唯一前缀触发,例如 /con -> /context
        if cmd not in known:
            matches = [c for c in known if c.startswith(cmd)]
            if len(matches) == 1:
                cmd = matches[0]
            else:
                self._log(f"[yellow]未知命令:[/] {_esc(text)}")
                self._log("[dim]可用命令: " + " ".join(known) + "[/]")
                return

        if cmd == "/help":
            self._log("[bold]可用斜杠命令:[/]")
            for c, d in COMMANDS:
                self._log(f"  [bold]{c}[/]  [dim]{d}[/]")
            return
        if cmd == "/quit":
            self.exit()
            return
        if cmd == "/clear":
            self.query_one("#log", VerticalScroll).remove_children()
            return
        if cmd == "/compact":
            self._start_compact()
            return
        if cmd == "/context":
            self._show_context_detail()
            return
        if cmd == "/tools":
            self._log(f"[bold]可用工具({len(TOOL_MAP)}):[/]")
            for name in sorted(TOOL_MAP):
                self._log(f"  [dim]• {_esc(name)}[/]")
            return
        if cmd == "/mcp":
            self._show_mcp_detail()
            return
        if cmd == "/save":
            if not self._require_agent():
                return
            path = self.agent.save_session()
            self._log("[bold green]✓ 会话已保存[/]")
            self._log(f"[dim]{_esc(path)}[/]")
            return
        if cmd == "/new":
            if not self._require_agent():
                return
            old = self.agent.save_session()
            self._close_stream_line()
            sid = self.agent.start_session()
            self._warned_full = False
            self._log("[bold green]✓ 已新建会话[/]")
            self._log(f"[dim]上一会话已保存: {_esc(old)}[/]")
            self._log(f"[dim]新会话编号: {_esc(sid)}[/]")
            if self.agent.agents_md_injected:
                self._log("[dim]已注入 AGENTS.md[/]")
            self._update_ctxbar()
            return
        if cmd == "/resume":
            if not self._require_agent():
                return
            sessions = self.agent.list_sessions()
            if not sessions:
                self._log("[yellow]没有历史会话可恢复[/]")
                return
            self.push_screen(SessionListScreen(sessions), self._after_resume)
            return

    def _after_resume(self, sid: str | None):
        if not sid or self.agent is None:
            return
        count = self.agent.resume_session(sid)
        self._warned_full = False
        self._close_stream_line()
        self._log("[bold green]✓ 已恢复会话[/]")
        self._log(f"[dim]编号 {_esc(sid)},共 {count} 条消息[/]")
        self._update_ctxbar()

    def _show_context_detail(self):
        if self.agent is None:
            return
        st = self.agent.context_status()
        window = f"{st['window'] / 1000:.1f}k"
        if st.get("is_default"):
            window += "(默认)"
        self._log(f"[bold]上下文占用[/] {st['used']} tokens / {window}  ({st['percent'] * 100:.1f}%)")
        self._log(f"[dim]压缩阈值 {int(self.agent.compact_ratio * 100)}% · 摘要目标 {self.agent.summary_target_tokens} tokens[/]")

    def _show_mcp_detail(self):
        if self.agent is None:
            return
        info = self.agent.mcp_info()
        if not info.get("loaded"):
            self._log("[yellow]MCP 尚未加载完成,请稍候[/]")
            return
        servers = info.get("servers") or []
        if not servers:
            self._log("[dim]未配置 MCP 服务器[/]")
            return
        for srv in servers:
            if srv.get("error"):
                self._log(f"[red]✗ {_esc(srv['name'])}[/] [dim]{_esc(str(srv['error'])[:200])}[/]")
            else:
                self._log(f"[green]✓ {_esc(srv['name'])}[/] [dim]{len(srv.get('tools') or [])} 个工具[/]")
                for t in srv.get("tools") or []:
                    self._log(f"   [dim]• {_esc(t)}[/]")

    # ---------- 上下文压缩 ----------
    def _start_compact(self):
        if self.agent is None or self._compacting:
            return
        self._compacting = True
        self._close_stream_line()
        self._log("[bold cyan]⟳ 开始压缩上下文[/] 正在归档原始记录并请求 LLM 生成摘要…")

        def job():
            self.call_from_thread(self._after_compact, self.agent.compact())

        self.run_worker(job, thread=True, exclusive=True, group="compact")

    def _after_compact(self, result: dict):
        self._compacting = False
        if result.get("ok"):
            self._warned_full = False
            self._log(
                f"[bold green]✓ 上下文压缩完成[/]  归档编号 [bold]{_esc(result['archive_id'])}[/]"
                f"  → {_esc(result['path'])}"
            )
            self._log("[dim]摘要已替换历史上下文;缺失的历史细节可用 recallContext 检索归档。[/]")
            self._update_ctxbar()
        else:
            self._log(f"[bold red]✗ 上下文压缩失败:[/] {_esc(result.get('error', '未知错误'))}")
            self._log("[dim]原有上下文已保留,可重新执行 /compact 再试。[/]")

    # ---------- 上下文占用显示 ----------
    def _update_ctxbar(self, status: dict | None = None):
        bar = self.query_one("#ctxbar", Static)
        if self.agent is None:
            bar.update("[dim]上下文: 未就绪[/]")
            return

        st = status or self.agent.context_status()
        pct = st["percent"] * 100
        threshold = self.agent.compact_ratio * 100
        color = "red" if st["exceeded"] else ("yellow" if pct >= threshold * 0.75 else "green")
        used = f"{st['used'] / 1000:.1f}k"
        window = f"{st['window'] / 1000:.1f}k"
        text = f"[bold {color}]上下文 {used} / {window} ({pct:.1f}%)[/]"
        if st.get("is_default"):
            text += " [dim]· 窗口大小默认 128k[/]"
        if st["exceeded"]:
            text += f" [bold red]⚠ 已达 {threshold:.0f}%,请执行 /compact[/]"
        bar.update(text)
        plain = f"上下文 {used}/{window} ({pct:.1f}%)"
        self.sub_title = plain if not st["exceeded"] else plain + " ⚠ 请 /compact"

        if st["exceeded"] and not self._warned_full:
            self._warned_full = True
            self._log(
                f"[bold red]⚠ 上下文占用已达 {threshold:.0f}%,已暂停接收新任务。[/]"
                " 请输入 /compact 压缩上下文。"
            )
        elif not st["exceeded"]:
            self._warned_full = False

    def _ev_context_usage(self, status: dict):
        self.call_from_thread(self._update_ctxbar, status)

    # ---------- Agent 回调(在 worker 线程中触发) ----------
    def _ev_tool_call(self, name: str, args: dict):
        self.call_from_thread(
            self._log,
            f"  [yellow]⚙ 调用工具[/] [bold]{_esc(name)}[/]({_esc(args)})",
        )

    def _ev_tool_result(self, name: str, result: str):
        limit = self.tool_preview_chars
        short = result if len(result) <= limit else result[:limit] + "..."
        self.call_from_thread(self._log, f"  [blue]↩ 返回[/] {_esc(short)}")

    def _ev_token(self, piece: str):
        self._streaming_tokens.append(piece)
        if not self._streaming_line_open:
            self._streaming_line_open = True
            self.call_from_thread(self._open_stream_line)
        if len(self._streaming_tokens) >= 3:
            chunk = "".join(self._streaming_tokens)
            self._streaming_tokens.clear()
            self.call_from_thread(self._append_stream, chunk)

    def _ev_error(self, msg: str):
        self.call_from_thread(self._flush_stream)
        self.call_from_thread(self._finish_stream_line)
        self.call_from_thread(self._log, f"[bold red]错误:[/] {_esc(msg)}")

    def _ev_response_done(self, full_text: str):
        self.call_from_thread(self._stream_finish)

    # ---------- 线程安全的 UI 更新 ----------
    def _log(self, markup: str):
        container = self.query_one("#log", VerticalScroll)
        container.mount(Static(markup, markup=True))
        container.scroll_end(animate=False)

    def _open_stream_line(self):
        self._stream_text = ""
        self._stream_static = Static("[bold magenta]AI:[/] ", markup=True)
        container = self.query_one("#log", VerticalScroll)
        container.mount(self._stream_static)
        container.scroll_end(animate=False)

    def _append_stream(self, chunk: str):
        self._stream_text += chunk
        self._render_stream()

    def _render_stream(self):
        static = getattr(self, "_stream_static", None)
        if static is None:
            return
        static.update(f"[bold magenta]AI:[/] {_esc(self._stream_text)}")
        self.query_one("#log", VerticalScroll).scroll_end(animate=False)

    def _flush_stream(self):
        if self._streaming_tokens:
            chunk = "".join(self._streaming_tokens)
            self._streaming_tokens.clear()
            self._stream_text += chunk
            self._render_stream()

    def _finish_stream_line(self):
        self._stream_static = None
        self._stream_text = ""
        self._streaming_line_open = False

    def _close_stream_line(self):
        if self._streaming_line_open:
            self._flush_stream()
            self._finish_stream_line()

    def _stream_finish(self):
        self._flush_stream()
        self._streaming_tokens.clear()
        self._finish_stream_line()

    # ---------- 快捷键 ----------
    def action_clear(self):
        self.query_one("#log", VerticalScroll).remove_children()


def main():
    XAgentApp().run()


if __name__ == "__main__":
    main()
