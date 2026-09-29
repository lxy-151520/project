"""端到端（进程内 ASGI）：无状态 Streamable HTTP 装配、发现、工具调用、错误流。

覆盖任务要求的第 7 类场景：
- 不发旧 ``initialize``、不要求也不返回 ``Mcp-Session-Id``；
- 用 ``2026-07-28`` 的 ``server/discover`` 发现 + ``tools/list`` + ``tools/call``；
- ``GET /health`` 可用；
- 工具能经 HTTP MCP 端点被发现和调用。
"""

from __future__ import annotations

import json

import httpx

from conftest import SAMPLE_LIST_DATA, ok_envelope


def test_health_endpoint(mcp_factory) -> None:
    client = mcp_factory(lambda request: httpx.Response(200, json=ok_envelope(SAMPLE_LIST_DATA)))
    response = client.health()
    assert response.status_code == 200
    payload = response.json()
    assert payload["status"] == "healthy"
    assert payload["mcpSdkVersion"] == "2.0.0"
    assert payload["protocolVersion"] == "2026-07-28"
    assert payload["transport"] == "streamable-http-stateless"
    assert payload["mcpEndpoint"] == "/mcp"
    # 健康检查同样不带任何会话头
    assert response.headers.get("mcp-session-id") is None


def test_modern_discover_without_initialize_handshake(mcp_factory) -> None:
    client = mcp_factory(lambda request: httpx.Response(200, json=ok_envelope(SAMPLE_LIST_DATA)))
    response = client.rpc("server/discover")
    assert response.status_code == 200
    envelope = response.json()
    assert "error" not in envelope
    result = envelope["result"]
    assert "2026-07-28" in result["supportedVersions"]
    assert "tools" in result["capabilities"]
    assert "list_pets" in result["instructions"]
    assert response.headers.get("mcp-session-id") is None


def test_tools_list_exposes_single_tool_with_schema(mcp_factory) -> None:
    client = mcp_factory(lambda request: httpx.Response(200, json=ok_envelope(SAMPLE_LIST_DATA)))
    response = client.rpc("tools/list")
    assert response.status_code == 200
    result = response.json()["result"]
    tools = result["tools"]
    assert len(tools) == 1
    tool = tools[0]
    assert tool["name"] == "list_pets"
    assert "GET /api/v1/pets" in tool["description"]

    schema = tool["inputSchema"]
    assert schema["type"] == "object"
    properties = schema["properties"]
    assert set(properties) == {
        "q", "name", "ownerName", "ownerPhone", "species", "doctor", "disease",
        "status", "min", "max", "sortBy", "order", "page", "pageSize",
    }
    assert properties["species"]["anyOf"][0]["enum"] == ["犬", "猫", "兔", "鸟", "仓鼠", "爬宠", "其他"]
    assert properties["status"]["anyOf"][0]["enum"] == ["待就诊", "就诊中", "住院中", "已康复", "慢性病随访"]
    assert properties["order"]["anyOf"][0]["enum"] == ["asc", "desc"]
    assert properties["sortBy"]["anyOf"][0]["enum"] == [
        "id", "name", "ownerName", "species", "doctor", "disease", "status",
        "totalCost", "visitCount", "createdAt", "updatedAt",
    ]
    assert properties["page"]["anyOf"][0]["minimum"] == 1
    assert properties["pageSize"]["anyOf"][0] == {"minimum": 1, "maximum": 500, "type": "integer"}
    assert response.headers.get("mcp-session-id") is None


def test_tools_call_happy_path_forwards_all_filters(mcp_factory) -> None:
    captured: dict[str, object] = {}

    def handler(request: httpx.Request) -> httpx.Response:
        captured["path"] = request.url.path
        captured["params"] = dict(request.url.params)
        return httpx.Response(200, json=ok_envelope(SAMPLE_LIST_DATA))

    client = mcp_factory(handler)
    arguments = {
        "q": "肠胃炎",
        "name": "旺财",
        "ownerName": "张三",
        "ownerPhone": "13900000000",
        "species": "犬",
        "doctor": "王医生",
        "disease": "肠胃炎",
        "status": "已康复",
        "min": 100,
        "max": 5000,
        "sortBy": "totalCost",
        "order": "desc",
        "page": 1,
        "pageSize": 20,
    }
    response = client.call_tool("list_pets", arguments)

    assert response.status_code == 200
    envelope = response.json()
    assert "error" not in envelope
    result = envelope["result"]
    assert result.get("isError") is not True
    text = result["content"][0]["text"]
    payload = json.loads(text)
    assert payload["total"] == 2
    assert payload["pageSize"] == 20
    assert payload["items"][1]["records"] == []

    assert captured["path"] == "/api/v1/pets"
    assert captured["params"]["q"] == "肠胃炎"
    assert captured["params"]["species"] == "犬"
    # 经 SDK 参数模型后 int 被归一化为 float，Go query 解析等价
    assert captured["params"]["min"] == "100.0"
    assert captured["params"]["sortBy"] == "totalCost"
    assert captured["params"]["order"] == "desc"
    # 无状态响应：永远没有会话标识
    assert response.headers.get("mcp-session-id") is None


def test_tools_call_validation_error_uses_unified_envelope(mcp_factory) -> None:
    upstream_calls = {"n": 0}

    def handler(request: httpx.Request) -> httpx.Response:
        upstream_calls["n"] += 1
        raise AssertionError("非法入参不应到达上游")

    client = mcp_factory(handler)

    # 中间件在 SDK 参数校验之前短路：越界值得到统一 VALIDATION_ERROR，且是工具失败而非顶层 JSON-RPC 错误
    response = client.call_tool("list_pets", {"pageSize": 9999})
    assert response.status_code == 200
    result = response.json()["result"]
    assert result["isError"] is True
    body = json.loads(result["content"][0]["text"])
    assert body["error"]["code"] == "VALIDATION_ERROR"
    assert body["error"]["details"]["validationErrors"]
    assert upstream_calls["n"] == 0

    # 未知字段同样被拒
    response2 = client.call_tool("list_pets", {"page": 1, "hack": True})
    result2 = response2.json()["result"]
    assert result2["isError"] is True
    assert json.loads(result2["content"][0]["text"])["error"]["code"] == "VALIDATION_ERROR"
    assert upstream_calls["n"] == 0


def test_tools_call_backend_unavailable(mcp_factory) -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        raise httpx.ConnectError("down")

    client = mcp_factory(handler)
    response = client.call_tool("list_pets", {"q": "x"})
    assert response.status_code == 200
    result = response.json()["result"]
    assert result["isError"] is True
    body = json.loads(result["content"][0]["text"])
    assert body["error"]["code"] == "BACKEND_UNAVAILABLE"
    assert response.headers.get("mcp-session-id") is None


def test_stateless_requests_are_independent(mcp_factory) -> None:
    """连续两个请求互不依赖：第二个不携带任何会话头也能成功。"""

    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, json=ok_envelope(SAMPLE_LIST_DATA))

    client = mcp_factory(handler)
    first = client.call_tool("list_pets", {"page": 1, "pageSize": 20})
    second = client.call_tool("list_pets", {"page": 2, "pageSize": 5})
    assert first.status_code == 200
    assert second.status_code == 200
    assert first.headers.get("mcp-session-id") is None
    assert second.headers.get("mcp-session-id") is None
    assert json.loads(second.json()["result"]["content"][0]["text"])["page"] == 1


def test_get_on_mcp_endpoint_is_method_not_allowed(mcp_factory) -> None:
    """现代（2026-07-28）路径下 GET /mcp 直接 405：不存在 SSE 订阅端点。"""
    client = mcp_factory(lambda request: httpx.Response(200, json=ok_envelope(SAMPLE_LIST_DATA)))
    response = client.get_mcp()
    assert response.status_code == 405
    assert response.headers.get("mcp-session-id") is None


def test_missing_modern_meta_envelope_is_rejected(mcp_factory) -> None:
    client = mcp_factory(lambda request: httpx.Response(200, json=ok_envelope(SAMPLE_LIST_DATA)))
    response = client.rpc("tools/list", include_meta=False)
    assert response.status_code == 400
    payload = response.json()
    assert payload["error"]["code"] == -32602


def test_wrong_protocol_version_header_is_rejected(mcp_factory) -> None:
    client = mcp_factory(lambda request: httpx.Response(200, json=ok_envelope(SAMPLE_LIST_DATA)))
    # 头与 body _meta 的协议版本不一致（且头不是旧握手版本）-> 现代路径 HEADER_MISMATCH
    response = client.rpc(
        "tools/list",
        extra_headers={"MCP-Protocol-Version": "2099-01-01"},
    )
    assert response.status_code == 400
    assert "error" in response.json()
    assert response.headers.get("mcp-session-id") is None
