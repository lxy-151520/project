# -*- coding: utf-8 -*-
"""Textual TUI 界面:消息列表 + 输入框,工具调用过程实时可见。"""
from __future__ import annotations

import sys
import traceback
from pathlib import Path

from textual.app import App, ComposeResult
from textual.binding import Binding
from textual.containers import Vertical, VerticalScroll
from textual.widgets import Footer, Header, Input, Static

from ..core import Agent, AgentCallbacks, LLMClient, load_config


def _esc(value) -> str:
    """把动态内容变成安全的 markup 字面量。

    注意不能用 rich.markup.escape:它只转义"像标签"的 [ (后跟字母/#/@),
    而 dict/list 的 repr(如 ['create', 'demo.pptx']) 里 [ 后面是引号,会漏掉,
    导致 MarkupError。这里无条件转义反斜杠和所有 [。
    """
    return str(value).replace("\\", "\\\\").replace("[", "\\[")


def _find_config_ini() -> Path:
    """智能定位 config.ini:源码运行和 PyInstaller 打包后都能找到。

    优先级:
    1. sys.frozen 模式(打包后):exe 所在目录
    2. 源码模式:__file__ 所在目录往上找到 xAgent/
    3. 兜底:相对路径 config.ini
    """
    # 情况 1: PyInstaller 打包后,exe 同级目录
    if getattr(sys, "frozen", False):
        base = Path(sys.executable).resolve().parent
        ini = base / "config.ini"
        if ini.exists():
            return ini
    # 情况 2:源码运行,__file__ → tui/ → xAgent/
    ini = Path(__file__).resolve().parent.parent / "config.ini"
    if ini.exists():
        return ini
    # 情况 3:兜底
    return Path("config.ini").resolve()


class XAgentApp(App):
    """xAgent Textual 界面。"""

    CSS = """
    #ctxbar {
        height: 1;
        background: $panel;
        padding: 0 1;
        content-align: left middle;
    }
    #log {
        height: 1fr;
        border: solid $primary;
        padding: 0 1;
    }
    #input {
        height: 3;
        margin: 0 1 1 1;
    }
    """

    BINDINGS = [
        Binding("ctrl+c", "quit", "退出"),
        Binding("ctrl+l", "clear", "清屏"),
    ]

    def __init__(self):
        super().__init__()
        self._init_error: str | None = None
        try:
            ini_path = _find_config_ini()
            cfg = load_config(ini_path)
            llm = LLMClient(cfg)
            cb = AgentCallbacks(
                on_tool_call=self._ev_tool_call,
                on_tool_result=self._ev_tool_result,
                on_token=self._ev_token,
                on_response_done=self._ev_response_done,
                on_error=self._ev_error,
                on_context_usage=self._ev_context_usage,
            )
            self.agent = Agent(llm=llm, callbacks=cb)
        except Exception as e:
            tb = traceback.format_exc()
            self._init_error = f"{e}\n\n{tb}"
            # 启动失败时也打印到 stderr
            print("=" * 50, file=sys.stderr)
            print(f"[xAgent 启动失败] {e}", file=sys.stderr)
            traceback.print_exc()
            print("=" * 50, file=sys.stderr)
            # 同时写一份到本地文件 (PyInstaller 打包后看不到 stderr 时用)
            try:
                log_path = Path.cwd() / "_xagent_init_error.log"
                log_path.write_text(
                    f"[{ini_path if 'ini_path' in dir() else 'unknown'}]\n{self._init_error}",
                    encoding="utf-8",
                )
            except Exception:
                pass
            self.agent = None
        self._streaming_tokens: list[str] = []
        self._streaming_line_open = False
        self._stream_text: str = ""
        self._stream_static: Static | None = None
        # 上下文压缩状态
        self._compacting = False
        self._warned_full = False

    # ---------- UI 布局 ----------
    def compose(self) -> ComposeResult:
        yield Header(show_clock=True, name="xAgent")
        with Vertical():
            yield VerticalScroll(id="log")
            yield Static("上下文: 未就绪", id="ctxbar")
            yield Input(placeholder="输入消息,Enter 发送... (压缩上下文请用 /compact)", id="input")
        yield Footer()

    def on_mount(self):
        self.title = "xAgent TUI"
        self.sub_title = "core/UI 分离架构演示"
        self.query_one("#input", Input).focus()
        if self.agent is None:
            self._log("[bold red]⚠ Agent 初始化失败[/] 详细错误如下 (也已写入 _xagent_init_error.log):")
            if self._init_error:
                self._log(f"[dim]{_esc(self._init_error)}[/]")
        else:
            self._log("[bold cyan]xAgent 已启动[/]  支持工具: getDate / isLeapYear / 文件目录操作 / searchWeb / fetchWeb / Run / loadSkill / createSkill / recallContext")
            self._log("[dim]试试: 今天日期 / 2024年是闰年吗 / 搜索国庆放几天 / 运行 python -V[/]")
            self._log("[dim]上下文接近上限时输入 [bold]/compact[/bold] 手动压缩[/]")
            self._update_ctxbar()

    # ---------- 输入提交 ----------
    def on_input_submitted(self, event: Input.Submitted):
        text = event.value.strip()
        if not text:
            return
        event.input.value = ""

        if self._compacting:
            self._log("[yellow]上下文压缩进行中,请稍候再输入…[/]")
            return
        if self.agent is None:
            self._log("[bold red]Agent 未就绪[/] 无法处理请求,请检查配置后重启")
            return

        # 手动触发上下文压缩
        if text.lower() == "/compact":
            self._start_compact()
            return
        if text.startswith("/"):
            self._log(f"[yellow]未知命令:[/] {_esc(text)}  可用命令: [bold]/compact[/]")
            return

        # 达到 80% 后暂停接收普通提示词
        if self.agent.is_context_full():
            self._log("[bold red]⚠ 上下文已占用 80% 以上,已暂停接收新任务。[/] 请先执行 [bold]/compact[/] 压缩上下文")
            return

        self._log(f"[bold green]你:[/] {_esc(text)}")
        self._close_stream_line()
        self._run_agent(text)

    # ---------- 后台调用 Agent(不阻塞 UI) ----------
    def _run_agent(self, text: str):
        def job():
            self.agent.chat(text)
        self.run_worker(job, thread=True, exclusive=True, group="chat")

    # ---------- 上下文压缩 ----------
    def _start_compact(self):
        """手动触发 /compact:归档 -> LLM 摘要 -> 替换上下文。"""
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
            self._log("[dim]摘要已替换历史上下文,可以继续输入任务;缺失的历史细节可用 recallContext 检索归档。[/]")
            self._update_ctxbar()
        else:
            self._log(f"[bold red]✗ 上下文压缩失败:[/] {_esc(result.get('error', '未知错误'))}")
            self._log("[dim]原有上下文已保留,可重新执行 /compact 再试。[/]")

    # ---------- 上下文占用显示 ----------
    def _update_ctxbar(self, status: dict | None = None):
        """在顶部固定位置显示 使用量 / 窗口 / 百分比。"""
        bar = self.query_one("#ctxbar", Static)
        if self.agent is None:
            bar.update("[dim]上下文: 未就绪[/]")
            return

        st = status or self.agent.context_status()
        pct = st["percent"] * 100
        color = "red" if pct >= 80 else ("yellow" if pct >= 60 else "green")
        used = f"{st['used'] / 1000:.1f}k"
        window = f"{st['window'] / 1000:.1f}k"
        text = f"[bold {color}]上下文 {used} / {window} ({pct:.1f}%)[/]"
        if st.get("is_default"):
            text += " [dim]· 窗口大小默认 128k[/]"
        if pct >= 80:
            text += " [bold red]⚠ 已达 80%,请执行 /compact[/]"
        bar.update(text)
        # 同时在标题栏显示一份,避免某些终端把独立状态行裁成半行
        plain = f"上下文 {used}/{window} ({pct:.1f}%)"
        self.sub_title = plain if pct < 80 else plain + " ⚠ 请 /compact"

        # 首次越过阈值时在日志区提示一次,避免刷屏
        if pct >= 80 and not self._warned_full:
            self._warned_full = True
            self._log("[bold red]⚠ 上下文占用已达 80%,已暂停接收新任务。请输入 /compact 压缩上下文。[/]")
        elif pct < 80:
            self._warned_full = False

    def _ev_context_usage(self, status: dict):
        """Agent 每次 LLM 响应后回调(worker 线程)。"""
        self.call_from_thread(self._update_ctxbar, status)

    # ---------- Agent 回调(注意:在 worker 线程中触发) ----------
    def _ev_tool_call(self, name: str, args: dict):
        self.call_from_thread(
            self._log,
            f"  [yellow]⚙ 调用工具[/] [bold]{_esc(name)}[/]({_esc(args)})",
        )

    def _ev_tool_result(self, name: str, result: str):
        short = result if len(result) <= 300 else result[:300] + "..."
        self.call_from_thread(self._log, f"  [blue]↩ 返回[/] {_esc(short)}")

    def _ev_token(self, piece: str):
        """流式 token:累积后追加到同一个 Static,保证一段回复只有一行。"""
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
        """Agent 完整回复完成 —— 冲刷残留 token,重置状态。"""
        self.call_from_thread(self._stream_finish)

    # ---------- 线程安全的 UI 更新 ----------
    def _log(self, markup: str):
        """追加一行日志(markup 字符串)。"""
        container = self.query_one("#log", VerticalScroll)
        container.mount(Static(markup, markup=True))
        container.scroll_end(animate=False)

    def _open_stream_line(self):
        """开一个新的流式行占位。"""
        self._stream_text = ""
        self._stream_static = Static("[bold magenta]AI:[/] ", markup=True)
        container = self.query_one("#log", VerticalScroll)
        container.mount(self._stream_static)
        container.scroll_end(animate=False)

    def _append_stream(self, chunk: str):
        """把新 chunk 拼接到当前流式行末尾(原地更新,不换行)。"""
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
