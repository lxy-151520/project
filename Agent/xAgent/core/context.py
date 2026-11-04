# -*- coding: utf-8 -*-
"""上下文管理:Token 估算、原始上下文归档、LLM 压缩。

设计尽量简单、可读:
- Token 统计优先使用模型 API 返回的 usage;拿不到时用估算(中文按 1 字 1 token,英文按 4 字符 1 token)。
- 压缩前先把完整原始上下文写成 JSONL 归档,落盘成功后才继续替换上下文。
- 压缩只用一次普通 LLM 调用(不挂 tools),不引入向量库/Embedding。
"""
from __future__ import annotations

import json
from datetime import datetime
from pathlib import Path
from typing import Any

# 默认上下文窗口:无法从配置获取时使用 128k,并在 TUI 标注「默认」
DEFAULT_CONTEXT_WINDOW = 128_000
# 达到该比例即告警并暂停接收新任务
COMPACT_RATIO = 0.80
# 压缩后的摘要目标长度(仅用于提示词,不做强制截断)
SUMMARY_TARGET_TOKENS = 5_000
# 归档目录(相对项目根)
ARCHIVE_SUBDIR = Path(".agents") / "context"

COMPACT_PROMPT = """你是一名 AI Agent 的上下文管理助手。当前会话即将达到上下文窗口限制，需要将历史对话压缩为一份高质量的工作摘要，以便 Agent 在新的上下文中继续执行任务。

请认真阅读提供的历史上下文，提取对后续工作仍然有价值的信息，并生成一份约 5,000 Tokens 的 Markdown 摘要。

摘要应重点保留以下内容：

1. **用户目标与要求**：用户希望完成什么任务？有哪些必须遵守的约束、偏好和验收条件？
2. **已经完成的工作**：哪些任务已经完成？实现了哪些功能？获得了哪些已经验证的结果？
3. **当前工作状态**：Agent 正在处理什么任务？当前进展到哪一步？是否存在尚未解决的问题？
4. **关键技术信息**：保留重要的文件路径、函数名称、接口定义、配置项、执行命令、错误信息和必要的代码片段。
5. **关键决策与原因**：记录用户和 Agent 已经确定的技术方案，以及重要的设计取舍。
6. **下一步任务**：明确接下来应该执行的操作，以及需要继续验证的事项。

请遵守以下要求：

- 优先保留对后续任务有直接影响的信息，删除寒暄、重复讨论、过时的尝试和无关内容。
- 对已经验证的事实与尚未验证的推测作出明确区分。
- 不要将计划完成的任务描述为已经完成。
- 重要的文件路径、函数名称、配置名称和命令应保留准确原文。
- 对失败的尝试，只保留有助于避免重复错误的信息。
- 如果信息存在冲突，应优先保留用户最新确认的要求，并简要说明仍然存在的冲突。
- 如果某些历史细节无法在摘要中完整保留，可简要说明它们已保存到原始上下文归档中，后续可以通过 recallContext 工具重新检索。
- 使用清晰的 Markdown 结构输出摘要，不要附加解释或无关内容。

**最终目标：使一个从未阅读过原始对话的 Agent，仅凭这份摘要，就能够理解当前任务、继承关键决策，并继续开展工作。**"""

COMPACT_USER_SUFFIX = (
    "\n\n请根据以上历史上下文生成 Markdown 工作摘要。只输出摘要本身,不要附加任何解释。"
)


# ---------- Token 估算 ----------
def estimate_tokens(text: Any) -> int:
    """粗略估算文本 token 数。中文汉字按 1 token,其它字符按 1/4 token。"""
    if not text:
        return 0
    s = str(text)
    cjk = 0
    for ch in s:
        if "\u4e00" <= ch <= "\u9fff" or "\u3000" <= ch <= "\u303f" or "\uff00" <= ch <= "\uffef":
            cjk += 1
    other = len(s) - cjk
    return int(cjk + other / 4) + 1


def message_tokens(msg: dict) -> int:
    """单条消息的 token 估算,包含 tool_calls 参数。"""
    if not isinstance(msg, dict):
        return 0
    total = estimate_tokens(msg.get("content") or "")
    calls = msg.get("tool_calls")
    if calls:
        total += estimate_tokens(json.dumps(calls, ensure_ascii=False))
    if msg.get("name"):
        total += estimate_tokens(msg["name"])
    return total


def conversation_tokens(messages: list[dict]) -> int:
    """整段对话(System Prompt + 历史 + 工具消息)的 token 估算。"""
    return sum(message_tokens(m) for m in messages)


# ---------- 归档 ----------
def new_archive_id(now: datetime | None = None) -> str:
    """生成归档编号,格式 20261022-153000。"""
    return (now or datetime.now()).strftime("%Y%m%d-%H%M%S")


def archive_path(root: str | Path) -> Path:
    return Path(root).resolve() / ARCHIVE_SUBDIR


def archive_messages(root: str | Path, messages: list[dict]) -> tuple[str, Path]:
    """把完整原始上下文写入 .agents/context/<编号>.jsonl。

    每条消息一行 JSON,保留 role / content / tool_calls / tool_call_id / name
    以及消息顺序(seq)。返回 (归档编号, 文件路径);写入失败会抛出异常,
    调用方应在落盘成功后才继续压缩。
    """
    folder = archive_path(root)
    folder.mkdir(parents=True, exist_ok=True)

    aid = new_archive_id()
    path = folder / f"{aid}.jsonl"
    while path.exists():                     # 极端情况:同一秒内重复触发
        aid = new_archive_id(datetime.now()) + "-1"
        path = folder / f"{aid}.jsonl"

    with path.open("w", encoding="utf-8") as f:
        for seq, msg in enumerate(messages):
            record = {"seq": seq}
            record.update({k: v for k, v in msg.items() if k != "seq"})
            f.write(json.dumps(record, ensure_ascii=False) + "\n")
    return aid, path


# ---------- 供压缩用 LLM 阅读的纯文本 ----------
def _render_message(msg: dict) -> str:
    role = msg.get("role", "?")
    content = (msg.get("content") or "").strip()
    if role == "user":
        return f"### 用户\n{content}"
    if role == "assistant":
        parts = [f"### 助手\n{content}"]
        for tc in msg.get("tool_calls") or []:
            fn = tc.get("function", {})
            parts.append(f"- 调用工具 {fn.get('name')} 参数 {fn.get('arguments')}")
        return "\n".join(p for p in parts if p.strip())
    if role == "tool":
        return f"### 工具返回({msg.get('name', '?')})\n{content}"
    return f"### {role}\n{content}"


def render_transcript(messages: list[dict], max_chars: int = 60_000) -> str:
    """把对话渲染为压缩用文本;过长时保留开头与结尾(开头通常含用户目标)。"""
    blocks = [_render_message(m) for m in messages if m.get("role") != "system"]
    text = "\n\n".join(b for b in blocks if b.strip())
    if len(text) <= max_chars:
        return text

    head_len = min(10_000, max_chars // 5)
    tail_len = max_chars - head_len
    omitted = len(text) - head_len - tail_len
    return (
        text[:head_len]
        + f"\n\n[...中间 {omitted} 个字符已省略,完整原文已归档到 .agents/context ...]\n\n"
        + text[-tail_len:]
    )


def archive_note(archive_id: str, when: datetime | None = None) -> str:
    """压缩摘要末尾必须追加的归档说明。"""
    ts = (when or datetime.now()).strftime("%Y-%m-%d %H:%M:%S")
    return (
        f"此前上下文已于 {ts} 完成压缩,原始上下文保存在编号为 {archive_id} 的归档文件中。"
        "如需查找历史信息,请使用 recallContext 工具。"
    )


def compact_prompt(target_tokens: int = SUMMARY_TARGET_TOKENS) -> str:
    """按配置的摘要目标 token 数生成专用压缩 Prompt。"""
    return COMPACT_PROMPT.replace("约 5,000 Tokens", f"约 {target_tokens:,} Tokens")

