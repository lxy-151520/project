# -*- coding: utf-8 -*-
"""会话事件日志:把对话按 JSONL 追加保存到 .agents/sessions/。

文件格式:
    第 1 行: {"kind": "session_meta", "id": "...", "created_at": "...", ...}
    之后每行: {"seq": n, "role": ..., "content": ..., ...}

事件日志采用「追加」的方式,便于保留完整原始对话;压缩上下文后会用
save_session 重写一次,保证文件与内存中的历史一致。
"""
from __future__ import annotations

import json
from datetime import datetime
from pathlib import Path

SESSION_SUBDIR = Path(".agents") / "sessions"


def new_session_id() -> str:
    """用时间戳生成会话编号,例如 20261104-110500。"""
    return datetime.now().strftime("%Y%m%d-%H%M%S")


def _folder(root: str | Path) -> Path:
    return Path(root).resolve() / SESSION_SUBDIR


def session_path(root: str | Path, sid: str) -> Path:
    return _folder(root) / f"{sid}.jsonl"


def create_session(root: str | Path, sid: str, meta: dict | None = None) -> Path:
    """新建会话文件(只写 meta 行)。"""
    path = session_path(root, sid)
    path.parent.mkdir(parents=True, exist_ok=True)
    record = {"kind": "session_meta", "id": sid, "created_at": datetime.now().isoformat(timespec="seconds")}
    if meta:
        record.update(meta)
    path.write_text(json.dumps(record, ensure_ascii=False) + "\n", encoding="utf-8")
    return path


def append_record(root: str | Path, sid: str, record: dict) -> None:
    """把一条消息追加为一行 JSON,自动补 seq(从 1 开始)。"""
    path = session_path(root, sid)
    path.parent.mkdir(parents=True, exist_ok=True)
    if not path.exists():
        create_session(root, sid)
    seq = _count_messages(path) + 1
    item = {"seq": seq}
    item.update(record)
    with path.open("a", encoding="utf-8") as fh:
        fh.write(json.dumps(item, ensure_ascii=False) + "\n")


def save_session(root: str | Path, sid: str, messages: list[dict], meta: dict | None = None) -> Path:
    """用内存中的完整历史重写会话文件(压缩后、/save 时使用)。"""
    path = session_path(root, sid)
    path.parent.mkdir(parents=True, exist_ok=True)
    header = {"kind": "session_meta", "id": sid, "updated_at": datetime.now().isoformat(timespec="seconds")}
    if meta:
        header.update(meta)
    lines = [json.dumps(header, ensure_ascii=False)]
    for i, msg in enumerate(messages):
        item = {"seq": i + 1}
        item.update(msg)
        lines.append(json.dumps(item, ensure_ascii=False))
    path.write_text("\n".join(lines) + "\n", encoding="utf-8")
    return path


def load_session(root: str | Path, sid: str) -> tuple[dict, list[dict]]:
    """读取会话文件,返回 (meta, messages)。"""
    path = session_path(root, sid)
    if not path.exists():
        raise FileNotFoundError(f"会话不存在: {sid}")
    meta: dict = {}
    messages: list[dict] = []
    for line in path.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if not line:
            continue
        try:
            record = json.loads(line)
        except json.JSONDecodeError:
            continue
        if record.get("kind") == "session_meta":
            meta = record
            continue
        record.pop("seq", None)
        record.pop("kind", None)
        messages.append(record)
    return meta, messages


def list_sessions(root: str | Path) -> list[dict]:
    """列出所有会话,最新的排在最前面。"""
    folder = _folder(root)
    if not folder.is_dir():
        return []
    out: list[dict] = []
    for path in folder.glob("*.jsonl"):
        meta, messages = _peek(path)
        preview = ""
        for m in messages:
            content = str(m.get("content") or "")
            if m.get("role") == "user" and not m.get("name") and not content.startswith("【项目规范"):
                preview = content.replace("\n", " ")[:40]
                break
        out.append({
            "id": path.stem,
            "updated_at": meta.get("updated_at") or meta.get("created_at") or "",
            "count": len(messages),
            "preview": preview,
        })
    out.sort(key=lambda x: x["id"], reverse=True)
    return out


# ---------- 内部工具 ----------
def _count_messages(path: Path) -> int:
    try:
        lines = path.read_text(encoding="utf-8").splitlines()
    except OSError:
        return 0
    count = 0
    for line in lines:
        line = line.strip()
        if not line:
            continue
        try:
            record = json.loads(line)
        except json.JSONDecodeError:
            continue
        if record.get("kind") != "session_meta":
            count += 1
    return count


def _peek(path: Path) -> tuple[dict, list[dict]]:
    meta: dict = {}
    messages: list[dict] = []
    try:
        lines = path.read_text(encoding="utf-8").splitlines()
    except OSError:
        return meta, messages
    for line in lines:
        line = line.strip()
        if not line:
            continue
        try:
            record = json.loads(line)
        except json.JSONDecodeError:
            continue
        if record.get("kind") == "session_meta":
            meta = record
        else:
            messages.append(record)
    return meta, messages
