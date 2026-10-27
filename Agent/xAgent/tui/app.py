# -*- coding: utf-8 -*-
"""Textual TUI 界面:消息列表 + 输入框,工具调用过程实时可见。"""
from __future__ import annotations

import sys
import traceback
from pathlib import Path

from textual.app import App, ComposeResult
from textual.binding import Binding
from textual.containers import Vertical
from textual.widgets import Footer, Header, Input, RichLog

from ..core import Agent, AgentCallbacks, LLMClient, load_config


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
    #log {
        height: 1fr;
        border: solid $primary;
        padding: 0 1;
    }
    #input {
        dock: bottom;
        margin: 1 1;
    }
    """

    BINDINGS = [
        Binding("ctrl+c", "quit", "退出"),
        Binding("ctrl+l", "clear", "清屏"),
    ]

    def __init__(self):
        super().__init__()
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
            )
            self.agent = Agent(llm=llm, callbacks=cb)
        except Exception as e:
            # 启动失败时打印完整 traceback,然后让 TUI 还能起来显示错误
            print("=" * 50, file=sys.stderr)
            print(f"[xAgent 启动失败] {e}", file=sys.stderr)
            traceback.print_exc()
            print("=" * 50, file=sys.stderr)
            # 让 app 还能启动,但 agent 为 None,避免崩掉
            self.agent = None
        self._streaming_tokens: list[str] = []
        self._streaming_line_open = False

    # ---------- UI 布局 ----------
    def compose(self) -> ComposeResult:
        yield Header(show_clock=True, name="xAgent")
        with Vertical():
            yield RichLog(id="log", markup=True, auto_scroll=True, wrap=True)
            yield Input(placeholder="输入消息,Enter 发送...", id="input")
        yield Footer()

    def on_mount(self):
        self.title = "xAgent TUI"
        self.sub_title = "core/UI 分离架构演示"
        self.query_one("#input", Input).focus()
        log = self.query_one("#log", RichLog)
        if self.agent is None:
            log.write("[bold red]⚠ Agent 初始化失败[/] 请确认 config.ini 在 exe 同级目录,且 API key 正确")
            log.write("[dim]启动时的详细错误已打印到终端窗口[/]\n")
        else:
            log.write("[bold cyan]xAgent 已启动[/]  支持工具: getDate / isLeapYear / 文件目录操作 / searchWeb / fetchWeb / Run")
            log.write("[dim]试试: 今天日期 / 2024年是闰年吗 / 搜索国庆放几天 / 运行 python -V[/]\n")

    # ---------- 输入提交 ----------
    def on_input_submitted(self, event: Input.Submitted):
        text = event.value.strip()
        if not text:
            return
        event.input.value = ""
        log = self.query_one("#log", RichLog)
        if self.agent is None:
            log.write("[bold red]Agent 未就绪[/] 无法处理请求,请检查配置后重启")
            return
        log.write(f"[bold green]你:[/] {text}")
        self._close_stream_line()
        self._run_agent(text)

    # ---------- 后台调用 Agent(不阻塞 UI) ----------
    def _run_agent(self, text: str):
        def job():
            self.agent.chat(text)
        self.run_worker(job, thread=True, exclusive=True, group="chat")

    # ---------- Agent 回调(注意:在 worker 线程中触发) ----------
    def _ev_tool_call(self, name: str, args: dict):
        self.call_from_thread(self._write, f"  [yellow]⚙ 调用工具[/] [bold]{name}[/]({args})")

    def _ev_tool_result(self, name: str, result: str):
        short = result if len(result) <= 300 else result[:300] + "..."
        self.call_from_thread(self._write, f"  [blue]↩ 返回[/] {short}")

    def _ev_token(self, piece: str):
        """把流式 token 累积,攒够就 write (RichLog 不支持 end 参数)。"""
        self._streaming_tokens.append(piece)
        if not self._streaming_line_open:
            self._streaming_line_open = True
            self.call_from_thread(self._write, "[bold magenta]AI:[/] ", flush_stream=False)
        # 攒够就批量输出 (减少刷新频率)
        if len(self._streaming_tokens) >= 3:
            chunk = "".join(self._streaming_tokens)
            self._streaming_tokens.clear()
            self.call_from_thread(self._write_stream_chunk, chunk)

    def _ev_error(self, msg: str):
        # 先把残留 token 输出掉
        self._flush_stream()
        self.call_from_thread(self._write, f"[bold red]错误:[/] {msg}", flush_stream=True)

    def _ev_response_done(self, full_text: str):
        """Agent 完整回复完成 —— 冲刷残留 token,重置状态。"""
        self.call_from_thread(self._stream_finish)

    # ---------- 线程安全的 UI 更新 ----------
    def _write(self, markup: str, flush_stream: bool = True):
        log = self.query_one("#log", RichLog)
        if flush_stream:
            self._flush_stream()
        log.write(markup)

    def _write_stream_chunk(self, chunk: str):
        log = self.query_one("#log", RichLog)
        # 转义 [ 避免被当 markup
        safe = chunk.replace("[", "\\[")
        log.write(safe)

    def _flush_stream(self):
        """把残留的流式 token 全部输出 (换行)。"""
        if self._streaming_tokens:
            chunk = "".join(self._streaming_tokens)
            self._streaming_tokens.clear()
            log = self.query_one("#log", RichLog)
            log.write(chunk.replace("[", "\\["))

    def _close_stream_line(self):
        if self._streaming_line_open:
            self._streaming_line_open = False
            self._flush_stream()

    def _stream_finish(self):
        """流式输出结束 —— 冲刷 + 换状态。"""
        self._flush_stream()
        self._streaming_line_open = False
        self._streaming_tokens.clear()

    # ---------- 快捷键 ----------
    def action_clear(self):
        self.query_one("#log", RichLog).clear()


def main():
    XAgentApp().run()


if __name__ == "__main__":
    main()
