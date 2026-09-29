"""测试公共夹具与 2026-07-28 无状态 JSON-RPC 请求助手。

所有上游访问都通过 ``httpx.MockTransport`` 注入，测试期间不允许访问真实
Go 服务（也不访问 8080 端口）。
"""

from __future__ import annotations

from collections.abc import Callable
from typing import Any

import httpx
import pytest
from starlette.testclient import TestClient

from pet_hospital_mcp.config import Settings
from pet_hospital_mcp.rest_client import PetHospitalClient
from pet_hospital_mcp.server import build_app

PROTOCOL_VERSION = "2026-07-28"
META_PROTOCOL_KEY = "io.modelcontextprotocol/protocolVersion"
META_CAPS_KEY = "io.modelcontextprotocol/clientCapabilities"

UPSTREAM_BASE_URL = "http://pet-hospital.test"

# 一份贴近真实 Go /api/v1/pets 的成功 data（records / charges 含数组与 null 两种表现）
SAMPLE_PET = {
    "id": "PET-1001",
    "name": "旺财",
    "species": "犬",
    "breed": "金毛",
    "gender": "公",
    "ageMonths": 36,
    "color": "金色",
    "chipNo": "900111000000001",
    "ownerName": "张三",
    "ownerPhone": "13900000000",
    "ownerAddr": "北京市朝阳区幸福里 1 号",
    "doctor": "王医生",
    "disease": "肠胃炎",
    "status": "已康复",
    "allergy": "无",
    "note": "已痊愈",
    "records": [
        {
            "id": "REC-1",
            "visitDate": "2026-09-01",
            "doctor": "王医生",
            "diagnosis": "急性肠胃炎",
            "symptoms": "呕吐、腹泻",
            "treatment": "补液治疗",
            "prescription": ["蒙脱石散"],
            "weightKg": 24.5,
            "temperature": 38.7,
            "followUp": "一周后复查",
            "charge": 320.5,
            "createdAt": "2026-09-01T10:00:00Z",
        }
    ],
    "charges": [
        {"id": "CHG-1", "item": "血常规", "category": "检查", "amount": 80.0, "doctor": "王医生", "date": "2026-09-01"}
    ],
    "totalCost": 320.5,
    "visitCount": 1,
    "createdAt": "2026-09-01T09:00:00Z",
    "updatedAt": "2026-09-08T09:00:00Z",
}

SAMPLE_PET_NULL_ARRAYS = {
    "id": "PET-1002",
    "name": "咪咪",
    "species": "猫",
    "records": None,
    "charges": None,
    "totalCost": 0,
    "visitCount": 0,
}

SAMPLE_LIST_DATA = {
    "items": [SAMPLE_PET, SAMPLE_PET_NULL_ARRAYS],
    "total": 2,
    "page": 1,
    "pageSize": 20,
    "totalPages": 1,
    "totalCost": 320.5,
}


def ok_envelope(data: Any) -> dict[str, Any]:
    return {"code": 200, "message": "ok", "data": data, "time": "2026-09-16T10:00:00Z"}


def make_rest_client(
    handler: Callable[[httpx.Request], httpx.Response],
    *,
    max_retries: int = 2,
    timeout: float = 1.0,
) -> PetHospitalClient:
    return PetHospitalClient(
        UPSTREAM_BASE_URL,
        timeout=timeout,
        max_retries=max_retries,
        transport=httpx.MockTransport(handler),
    )


@pytest.fixture
def settings() -> Settings:
    return Settings(
        mcp_host="127.0.0.1",
        mcp_port=8000,
        pet_hospital_base_url=UPSTREAM_BASE_URL,
        backend_timeout_seconds=1.0,
        backend_max_retries=2,
        log_level="WARNING",
    )


class MCPClient:
    """针对无状态 /mcp 端点的最小 JSON-RPC 客户端。"""

    def __init__(self, test_client: TestClient) -> None:
        self.http = test_client
        self._request_id = 0

    def rpc(
        self,
        method: str,
        params: dict[str, Any] | None = None,
        *,
        include_meta: bool = True,
        include_headers: bool = True,
        extra_headers: dict[str, str] | None = None,
        name_header: str | None = None,
    ) -> httpx.Response:
        self._request_id += 1
        body_params: dict[str, Any] = {}
        if include_meta:
            body_params["_meta"] = {
                META_PROTOCOL_KEY: PROTOCOL_VERSION,
                META_CAPS_KEY: {},
            }
        if params:
            body_params.update(params)
        body: dict[str, Any] = {
            "jsonrpc": "2.0",
            "id": self._request_id,
            "method": method,
        }
        if include_meta or params:
            body["params"] = body_params

        headers = {
            "Content-Type": "application/json",
            "Accept": "application/json, text/event-stream",
        }
        if include_headers:
            headers["MCP-Protocol-Version"] = PROTOCOL_VERSION
            headers["MCP-Method"] = method
            if name_header is not None:
                headers["MCP-Name"] = name_header
        if extra_headers:
            headers.update(extra_headers)
        return self.http.post("/mcp", headers=headers, json=body)

    def call_tool(self, name: str, arguments: dict[str, Any]) -> httpx.Response:
        return self.rpc(
            "tools/call",
            {"name": name, "arguments": arguments},
            name_header=name,
        )

    def health(self) -> httpx.Response:
        return self.http.get("/health")

    def get_mcp(self) -> httpx.Response:
        """按 2026-07-28 现代客户端的方式 GET /mcp（无 SSE 升级意图）。"""
        return self.http.get(
            "/mcp",
            headers={
                "MCP-Protocol-Version": PROTOCOL_VERSION,
                "Accept": "application/json",
            },
        )


@pytest.fixture
def mcp_factory(settings: Settings):
    created_clients: list[PetHospitalClient] = []
    test_clients: list[TestClient] = []

    def _factory(handler: Callable[[httpx.Request], httpx.Response]) -> MCPClient:
        rest_client = make_rest_client(handler)
        created_clients.append(rest_client)
        app = build_app(settings, rest_client)
        # Host 必须是传输安全白名单内的回环地址，不能用默认 testserver
        test_client = TestClient(app, base_url="http://127.0.0.1:8000")
        test_client.__enter__()
        test_clients.append(test_client)
        return MCPClient(test_client)

    yield _factory

    for tc in test_clients:
        tc.__exit__(None, None, None)
    for rc in created_clients:
        import anyio

        try:
            anyio.run(rc.aclose)
        except Exception:  # noqa: BLE001
            pass
