# -*- coding: utf-8 -*-
"""配置加载:config.ini -> AppConfig。

所有可调参数集中在这里,代码里不再写死数字;缺省值放在 DEFAULTS,
配置文件里不写某项时自动使用缺省值,并在启动日志里注明「默认」。
"""
from __future__ import annotations

import configparser
from dataclasses import dataclass, field
from pathlib import Path

# 无法从配置获取上下文窗口时使用的默认值(128k)
DEFAULT_CONTEXT_WINDOW = 128_000


# ---------- 缺省参数(配置项缺省时使用) ----------
DEFAULTS = {
    "llm": {
        "model": "glm-4-flash",
        "base_url": "https://open.bigmodel.cn/api/paas/v4",
        "context_window": DEFAULT_CONTEXT_WINDOW,
        "request_timeout": 120,
        "retry_times": 2,
    },
    "agent": {
        "max_tool_rounds": 16,
        "compact_ratio": 0.80,
        "summary_target_tokens": 5_000,
        "agents_md": True,
        "tool_preview_chars": 300,
    },
    "tools": {
        "command_timeout": 10,
        "command_timeout_max": 60,
        "run_timeout": 15,
        "run_timeout_max": 120,
        "output_max_chars": 4_000,
        "fetch_max_chars": 4_000,
        "search_top_k": 8,
        "search_top_k_max": 10,
        "recall_max_results": 8,
        "recall_snippet_chars": 300,
        "recall_max_output": 4_000,
    },
    "tui": {
        "sidebar_width": 34,
        "palette_height": 6,
    },
}

# 新建 config.ini 时写入的完整模板(mock 信息,需要用户自行修改)
CONFIG_TEMPLATE = """# xAgent 配置文件
# 首次运行会自动生成这份模板,请把 mock 值替换成你自己的真实配置,然后重启 xAgent。
# 任何一项没有填写时,程序会使用内置缺省值并在启动日志中标注「默认」。

[llm]
# 智谱 BigModel(OpenAI 兼容接口)的 API Key,必填
api_key = sk-mock-please-replace-with-your-key
# 接口地址,一般不用改
base_url = https://open.bigmodel.cn/api/paas/v4
# 模型名称
model = glm-4-flash
# 模型上下文窗口(token)。不知道就留空,程序按 128000 处理并标注「默认」
context_window =
# 单次 HTTP 请求超时(秒)
request_timeout = 120
# 超时/连接失败后的重试次数
retry_times = 2

[agent]
# 单次对话最多允许的连续工具调用轮数
max_tool_rounds = 16
# 上下文占用达到该比例就告警并暂停接收新任务(0~1)
compact_ratio = 0.80
# /compact 生成的摘要目标 token 数
summary_target_tokens = 5000
# 会话首次加载时是否注入项目根目录的 AGENTS.md
agents_md = true
# TUI 里工具调用/返回的预览字符数
tool_preview_chars = 300

[tools]
# runCommand 默认超时(秒)
command_timeout = 10
# Run 默认超时(秒)
run_timeout = 15
# 命令输出最大字符数
output_max_chars = 4000
# fetchWeb 默认返回正文最大字符数
fetch_max_chars = 4000
# searchWeb 默认返回条数
search_top_k = 8
# recallContext 单次最多返回条数
recall_max_results = 8
# recallContext 每条片段字符数
recall_snippet_chars = 300
# recallContext 输出总长度上限
recall_max_output = 4000

[search]
# 百度千帆 AI 搜索 API Key,搜索功能需要它;没有就留空
baidu_qianfan_api_key =

[tui]
# 左侧 MCP 面板宽度(字符)
sidebar_width = 34
# 斜杠命令补全面板最大高度(行)
palette_height = 6
"""


# ---------- 各段配置 ----------
@dataclass
class LLMConfig:
    api_key: str
    base_url: str
    model: str
    # 模型上下文窗口;未配置时用 128k,并标记为「默认」
    context_window: int = DEFAULT_CONTEXT_WINDOW
    context_window_is_default: bool = True
    request_timeout: int = 120
    retry_times: int = 2


@dataclass
class AgentConfig:
    max_tool_rounds: int = 16
    compact_ratio: float = 0.80
    summary_target_tokens: int = 5_000
    agents_md: bool = True
    tool_preview_chars: int = 300


@dataclass
class ToolsConfig:
    command_timeout: int = 10
    command_timeout_max: int = 60
    run_timeout: int = 15
    run_timeout_max: int = 120
    output_max_chars: int = 4_000
    fetch_max_chars: int = 4_000
    search_top_k: int = 8
    search_top_k_max: int = 10
    recall_max_results: int = 8
    recall_snippet_chars: int = 300
    recall_max_output: int = 4_000


@dataclass
class TuiConfig:
    sidebar_width: int = 34
    palette_height: int = 6


@dataclass
class AppConfig:
    llm: LLMConfig
    agent: AgentConfig = field(default_factory=AgentConfig)
    tools: ToolsConfig = field(default_factory=ToolsConfig)
    tui: TuiConfig = field(default_factory=TuiConfig)
    # 哪些段使用了缺省值(用于启动日志标注)
    default_sections: list[str] = field(default_factory=list)


# ---------- 解析辅助 ----------
def _get_int(sec, key: str, default: int, notes: list[str], label: str) -> int:
    raw = (sec.get(key) or "").strip()
    if not raw:
        notes.append(f"{label}.{key}")
        return default
    try:
        val = int(raw)
        return val if val > 0 else default
    except ValueError:
        notes.append(f"{label}.{key}")
        return default


def _get_float(sec, key: str, default: float, notes: list[str], label: str) -> float:
    raw = (sec.get(key) or "").strip()
    if not raw:
        notes.append(f"{label}.{key}")
        return default
    try:
        val = float(raw)
        return val if 0 < val < 1 else default
    except ValueError:
        notes.append(f"{label}.{key}")
        return default


def _get_bool(sec, key: str, default: bool, notes: list[str], label: str) -> bool:
    raw = (sec.get(key) or "").strip().lower()
    if not raw:
        notes.append(f"{label}.{key}")
        return default
    return raw in ("1", "true", "yes", "on")


def ensure_config(ini_path: str | Path) -> bool:
    """配置文件不存在时创建一份完整模板(含 mock 信息)。

    返回 True 表示本次新建了文件,调用方应提示用户修改后重启。
    """
    path = Path(ini_path)
    if path.exists():
        return False
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(CONFIG_TEMPLATE, encoding="utf-8")
    return True


def load_config(ini_path: str | Path = "config.ini") -> AppConfig:
    """读取 config.ini;文件必须存在,且必须包含 [llm] 段与 api_key。

    其余段落/项都可以省略,省略时使用 DEFAULTS 并在 default_sections 里记录,
    TUI 会把这些项显示为「默认」。
    """
    ini_path = Path(ini_path)
    if not ini_path.exists():
        raise FileNotFoundError(f"配置文件不存在: {ini_path.resolve()}")

    cp = configparser.ConfigParser()
    cp.read(ini_path, encoding="utf-8")
    if "llm" not in cp:
        raise KeyError("config.ini 缺少 [llm] 段")
    sec = cp["llm"]
    api_key = (sec.get("api_key") or "").strip()
    if not api_key:
        raise KeyError("config.ini 的 [llm] 段缺少 api_key")
    base_url = (sec.get("base_url") or "").strip() or DEFAULTS["llm"]["base_url"]
    model = (sec.get("model") or "").strip() or DEFAULTS["llm"]["model"]

    notes: list[str] = []

    # 上下文窗口:空值 = 默认 128k
    window_default = DEFAULTS["llm"]["context_window"]
    is_default = True
    window = window_default
    raw_window = (sec.get("context_window") or "").strip()
    if raw_window:
        try:
            parsed = int(raw_window)
            if parsed > 0:
                window = parsed
                is_default = False
        except ValueError:
            notes.append("llm.context_window")

    llm = LLMConfig(
        api_key=api_key,
        base_url=base_url,
        model=model,
        context_window=window,
        context_window_is_default=is_default,
        request_timeout=_get_int(sec, "request_timeout", DEFAULTS["llm"]["request_timeout"], notes, "llm"),
        retry_times=_get_int(sec, "retry_times", DEFAULTS["llm"]["retry_times"], notes, "llm"),
    )

    sec_a = cp["agent"] if "agent" in cp else {}
    agent = AgentConfig(
        max_tool_rounds=_get_int(sec_a, "max_tool_rounds", DEFAULTS["agent"]["max_tool_rounds"], notes, "agent"),
        compact_ratio=_get_float(sec_a, "compact_ratio", DEFAULTS["agent"]["compact_ratio"], notes, "agent"),
        summary_target_tokens=_get_int(sec_a, "summary_target_tokens", DEFAULTS["agent"]["summary_target_tokens"], notes, "agent"),
        agents_md=_get_bool(sec_a, "agents_md", DEFAULTS["agent"]["agents_md"], notes, "agent"),
        tool_preview_chars=_get_int(sec_a, "tool_preview_chars", DEFAULTS["agent"]["tool_preview_chars"], notes, "agent"),
    )

    sec_t = cp["tools"] if "tools" in cp else {}
    tools = ToolsConfig(
        command_timeout=_get_int(sec_t, "command_timeout", DEFAULTS["tools"]["command_timeout"], notes, "tools"),
        command_timeout_max=_get_int(sec_t, "command_timeout_max", DEFAULTS["tools"]["command_timeout_max"], notes, "tools"),
        run_timeout=_get_int(sec_t, "run_timeout", DEFAULTS["tools"]["run_timeout"], notes, "tools"),
        run_timeout_max=_get_int(sec_t, "run_timeout_max", DEFAULTS["tools"]["run_timeout_max"], notes, "tools"),
        output_max_chars=_get_int(sec_t, "output_max_chars", DEFAULTS["tools"]["output_max_chars"], notes, "tools"),
        fetch_max_chars=_get_int(sec_t, "fetch_max_chars", DEFAULTS["tools"]["fetch_max_chars"], notes, "tools"),
        search_top_k=_get_int(sec_t, "search_top_k", DEFAULTS["tools"]["search_top_k"], notes, "tools"),
        search_top_k_max=_get_int(sec_t, "search_top_k_max", DEFAULTS["tools"]["search_top_k_max"], notes, "tools"),
        recall_max_results=_get_int(sec_t, "recall_max_results", DEFAULTS["tools"]["recall_max_results"], notes, "tools"),
        recall_snippet_chars=_get_int(sec_t, "recall_snippet_chars", DEFAULTS["tools"]["recall_snippet_chars"], notes, "tools"),
        recall_max_output=_get_int(sec_t, "recall_max_output", DEFAULTS["tools"]["recall_max_output"], notes, "tools"),
    )

    sec_ui = cp["tui"] if "tui" in cp else {}
    tui = TuiConfig(
        sidebar_width=_get_int(sec_ui, "sidebar_width", DEFAULTS["tui"]["sidebar_width"], notes, "tui"),
        palette_height=_get_int(sec_ui, "palette_height", DEFAULTS["tui"]["palette_height"], notes, "tui"),
    )

    return AppConfig(llm=llm, agent=agent, tools=tools, tui=tui, default_sections=notes)
