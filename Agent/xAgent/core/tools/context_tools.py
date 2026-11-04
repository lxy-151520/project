# -*- coding: utf-8 -*-
"""recallContext 工具:在 .agents/context 的历史归档中做本地全文关键词检索。

不依赖向量库或 Embedding,只用 Python 字符串匹配,便于学生理解和维护。
"""
from __future__ import annotations

import json
from pathlib import Path

# 由 Agent 初始化时注入项目根目录
_PROJECT_ROOT: Path = Path.cwd()

ARCHIVE_SUBDIR = Path(".agents") / "context"

# 单次检索的输出上限,避免检索结果再次占满上下文(可由 config.ini [tools] 覆盖)
_MAX_RESULTS = 8
_MAX_SNIPPET = 300
_MAX_OUTPUT = 4_000


def configure(max_results: int | None = None, snippet_chars: int | None = None,
              max_output: int | None = None) -> None:
    """由 config.ini 注入运行参数。"""
    global _MAX_RESULTS, _MAX_SNIPPET, _MAX_OUTPUT
    if max_results:
        _MAX_RESULTS = max_results
    if snippet_chars:
        _MAX_SNIPPET = snippet_chars
    if max_output:
        _MAX_OUTPUT = max_output


def set_project_root(root: str | Path) -> None:
    global _PROJECT_ROOT
    _PROJECT_ROOT = Path(root).resolve()


def _archive_folder() -> Path:
    return _PROJECT_ROOT / ARCHIVE_SUBDIR


def _list_archives() -> list[Path]:
    folder = _archive_folder()
    if not folder.is_dir():
        return []
    return sorted(folder.glob("*.jsonl"), reverse=True)   # 新归档优先


def _message_text(record: dict) -> str:
    """把一条归档记录拼成可检索的文本。"""
    parts = [
        str(record.get("role") or ""),
        str(record.get("name") or ""),
        str(record.get("content") or ""),
    ]
    if record.get("tool_calls"):
        parts.append(json.dumps(record["tool_calls"], ensure_ascii=False))
    return "\n".join(p for p in parts if p)


def _terms(text: str) -> list[str]:
    """把查询串拆成关键词;中文按空格/标点切分,英文不区分大小写。"""
    raw = text.replace("\u3000", " ")
    for ch in "，。、；：？！,.;:?!()（）[]【】\"'":
        raw = raw.replace(ch, " ")
    out: list[str] = []
    for t in raw.split():
        t = t.strip().lower()
        if t and t not in out:
            out.append(t)
    return out


def _snippet(haystack: str, terms: list[str]) -> str:
    """截取第一处命中附近的片段。"""
    low = haystack.lower()
    pos = -1
    for t in terms:
        p = low.find(t)
        if p >= 0:
            pos = p
            break
    if pos < 0:
        return haystack[:_MAX_SNIPPET]
    start = max(0, pos - _MAX_SNIPPET // 3)
    piece = haystack[start:start + _MAX_SNIPPET]
    if start > 0:
        piece = "..." + piece
    if start + _MAX_SNIPPET < len(haystack):
        piece = piece + "..."
    return piece.replace("\n", " ").strip()


def recallContext(text: str, id: str | None = None) -> str:
    """在上下文归档中检索关键词。

    id 为空时检索 .agents/context 下所有归档;指定 id 时只查该归档。
    """
    keyword = (text or "").strip()
    if not keyword:
        return "检索失败:text(检索关键词)不能为空。请传入要查找的关键词或文本片段。"

    archives = _list_archives()
    if not archives:
        return "尚无上下文归档:.agents/context 目录下没有归档文件,会话还未执行过 /compact。"

    if id:
        archives = [p for p in archives if p.stem == str(id).strip()]
        if not archives:
            ids = ", ".join(p.stem for p in _list_archives()[:10]) or "无"
            return f"找不到编号为 {id} 的归档。现有归档编号:{ids}"

    terms = _terms(keyword)
    if not terms:
        return "检索失败:没能从 text 中解析出有效关键词。"

    hits: list[tuple[int, str, int, str, str]] = []   # (score, aid, seq, role, snippet)
    for path in archives:
        try:
            lines = path.read_text(encoding="utf-8").splitlines()
        except OSError as e:
            return f"读取归档失败: {e}"
        for line in lines:
            try:
                record = json.loads(line)
            except json.JSONDecodeError:
                continue
            haystack = _message_text(record)
            if record.get("role") == "system":      # System Prompt 是固定模板,不参与检索
                continue
            low = haystack.lower()
            score = sum(low.count(t) for t in terms)
            if score == 0:
                continue
            hits.append((
                score,
                path.stem,
                int(record.get("seq", -1)),
                str(record.get("role") or "?"),
                _snippet(haystack, terms),
            ))

    if not hits:
        return f"未找到与“{keyword}”匹配的历史内容。可换用更短的关键词,或指定归档编号 id 再试。"

    hits.sort(key=lambda h: (-h[0], h[1]))
    parts = [f"在上下文归档中检索“{keyword}”,命中 {len(hits)} 处,以下为最相关的 {min(len(hits), _MAX_RESULTS)} 处:"]
    for score, aid, seq, role, snippet in hits[:_MAX_RESULTS]:
        parts.append(f"\n[{aid}] 第 {seq} 条 ({role}, 命中 {score} 次)\n{snippet}")

    output = "\n".join(parts)
    if len(output) > _MAX_OUTPUT:
        output = output[:_MAX_OUTPUT] + "\n[...结果过长已截断,可用更精确的关键词或指定 id 缩小范围]"
    return output
