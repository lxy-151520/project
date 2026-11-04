# -*- coding: utf-8 -*-
"""MCP Client:连接外部 MCP Server(stdio / Streamable HTTP),
发现工具并通过 Function Calling 转发调用。

设计原则:
- 每次 list_tools / call_tool 都新建一次连接(stateless),
  避免长连接/后台事件循环带来的生命周期问题,也方便错误隔离。
- 暴露给 LLM 的工具名 = "<服务器名>__<原始工具名>",经 _sanitize 转成
  合法的 OpenAI function name,避免不同服务器间重名。
"""
from __future__ import annotations

import asyncio
import contextlib
import json
import re
from pathlib import Path
from typing import Any

from mcp import ClientSession
from mcp.client.stdio import StdioServerParameters, stdio_client
from mcp.client.streamable_http import streamable_http_client


_NAME_RE = re.compile(r"[^a-zA-Z0-9_-]")


def load_mcp_config(project_root: Path) -> dict | None:
    """读取 <项目根>/.mcp.json。文件不存在或解析失败返回 None。"""
    path = Path(project_root) / ".mcp.json"
    if not path.is_file():
        return None
    try:
        with path.open("r", encoding="utf-8") as f:
            data = json.load(f)
    except (OSError, json.JSONDecodeError):
        return None
    if not isinstance(data, dict) or "mcpServers" not in data:
        return None
    return data


def _sanitize(name: str) -> str:
    """把任意字符串变成合法的 OpenAI function name(^[a-zA-Z0-9_-]{1,64}$)。"""
    s = _NAME_RE.sub("_", str(name))
    return s[:64] or "tool"


def _declared_type(spec: dict) -> str | None:
    """取 schema 声明的有效类型。

    MCP 服务端(pydantic 生成)常用 {"anyOf":[{"type":"integer"},{"type":"null"}]}
    表示可选参数,这里取第一个非 null 的类型。
    """
    t = spec.get("type")
    if isinstance(t, str) and t != "null":
        return t
    for sub in spec.get("anyOf") or spec.get("oneOf") or []:
        if isinstance(sub, dict):
            st = sub.get("type")
            if isinstance(st, str) and st != "null":
                return st
    return None


def _coerce_args(arguments: dict, props: dict) -> dict:
    """按 inputSchema 把 LLM 传来的参数值纠正成声明的类型。

    模型经常把整数/布尔写成字符串(如 pageSize="3"),服务端 pydantic 会
    直接拒绝并且模型会反复用同样的错误参数重试。这里做一次宽松转换。
    """
    if not isinstance(arguments, dict):
        return {}
    out = dict(arguments)
    for key, spec in (props or {}).items():
        if key not in out or not isinstance(spec, dict):
            continue
        want = _declared_type(spec)
        val = out[key]
        try:
            if want == "integer":
                if isinstance(val, str):
                    out[key] = int(float(val.strip()))
                elif isinstance(val, float) and val.is_integer():
                    out[key] = int(val)
            elif want == "number" and isinstance(val, str):
                out[key] = float(val.strip())
            elif want == "boolean" and isinstance(val, str):
                low = val.strip().lower()
                if low in ("true", "1", "yes"):
                    out[key] = True
                elif low in ("false", "0", "no"):
                    out[key] = False
            elif want == "array" and isinstance(val, str):
                parsed = json.loads(val)
                if isinstance(parsed, list):
                    out[key] = parsed
        except (ValueError, json.JSONDecodeError):
            pass
    return out


def _schema(exposed_name: str, description: str, input_schema: dict | None) -> dict:
    """把 MCP Tool 转成 OpenAI function calling schema。"""
    params = input_schema if isinstance(input_schema, dict) else {}
    params.setdefault("type", "object")
    params.setdefault("properties", {})
    return {
        "type": "function",
        "function": {
            "name": exposed_name,
            "description": description or "",
            "parameters": params,
        },
    }


class McpManager:
    """管理多个 MCP Server 的连接、工具发现与调用转发。"""

    def __init__(self, config: dict):
        # server_name -> config dict
        self._servers: dict[str, dict] = dict(config.get("mcpServers", {}))
        # exposed_name -> (server_name, original_tool_name)
        self._route: dict[str, tuple[str, str]] = {}
        # 暴露给 LLM 的 schema 列表
        self.schemas: list[dict] = []
        # exposed_name -> inputSchema.properties(用于参数类型纠正)
        self._props: dict[str, dict] = {}

    # ---------- 公开 API ----------
    def bootstrap(self) -> list[str]:
        """连接所有 server,列出工具,构建路由与 schema。返回错误信息列表。"""
        errors: list[str] = []
        for sname, cfg in self._servers.items():
            try:
                tools = asyncio.run(self._list_tools(cfg))
            except Exception as e:  # noqa: BLE001
                errors.append(f"MCP server '{sname}' 连接/发现工具失败: {e}")
                continue
            for tool in tools:
                exposed = _sanitize(f"{sname}__{tool.name}")
                # 极端情况下暴露名冲突:加序号
                base = exposed
                i = 2
                while exposed in self._route:
                    exposed = _sanitize(f"{base}_{i}")
                    i += 1
                self._route[exposed] = (sname, tool.name)
                schema = tool.input_schema if isinstance(tool.input_schema, dict) else {}
                self._props[exposed] = schema.get("properties", {}) if isinstance(schema.get("properties"), dict) else {}
                self.schemas.append(_schema(exposed, tool.description, tool.input_schema))
        return errors

    def call(self, exposed_name: str, arguments: dict) -> str:
        """根据暴露名找到对应 server + 原始工具名,转发调用,返回文本结果。"""
        route = self._route.get(exposed_name)
        if route is None:
            return f"未知 MCP 工具: {exposed_name}"
        sname, original = route
        cfg = self._servers.get(sname)
        if cfg is None:
            return f"MCP server '{sname}' 不可用"
        try:
            args = _coerce_args(arguments, self._props.get(exposed_name, {}))
            return asyncio.run(self._call_tool(cfg, original, args))
        except Exception as e:  # noqa: BLE001
            return f"[MCP 调用错误] server={sname} tool={original}: {e}"

    # ---------- 内部 ----------
    @contextlib.asynccontextmanager
    async def _client(self, cfg: dict):
        stype = str(cfg.get("type", "stdio")).lower()
        if stype == "stdio":
            params = StdioServerParameters(
                command=cfg["command"],
                args=list(cfg.get("args", []) or []),
                env=cfg.get("env"),
            )
            async with stdio_client(params) as streams:
                yield streams
        elif stype in ("streamable_http", "http", "streamable-http"):
            url = cfg["url"]
            async with streamable_http_client(url) as streams:
                yield streams
        else:
            raise ValueError(f"不支持的 MCP 连接类型: {stype}")

    async def _list_tools(self, cfg: dict):
        async with self._client(cfg) as (read, write):
            async with ClientSession(read, write) as session:
                await session.initialize()
                res = await session.list_tools()
                return res.tools

    async def _call_tool(self, cfg: dict, name: str, arguments: dict):
        async with self._client(cfg) as (read, write):
            async with ClientSession(read, write) as session:
                await session.initialize()
                res = await session.call_tool(name, arguments)
                return self._flatten(res)

    @staticmethod
    def _flatten(res: Any) -> str:
        parts: list[str] = []
        for c in getattr(res, "content", []) or []:
            ctype = getattr(c, "type", "")
            if ctype == "text":
                parts.append(getattr(c, "text", ""))
            elif ctype == "image":
                parts.append(f"[image {getattr(c, 'mimeType', '?')}]")
            else:
                try:
                    parts.append(c.model_dump_json())
                except Exception:  # noqa: BLE001
                    parts.append(str(c))
        text = "\n".join(p for p in parts if p is not None)
        if getattr(res, "isError", False):
            text = f"[MCP 工具返回错误] {text}"
        return text
