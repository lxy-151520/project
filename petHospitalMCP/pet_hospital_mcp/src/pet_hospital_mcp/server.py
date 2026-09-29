"""MCP 服务装配。

使用 SDK 2.x 的 ``mcp.server.mcpserver.MCPServer``（不使用 FastMCP），
装配为**无状态** Streamable HTTP 应用：

- ``stateless_http=True``：每个 POST 自包含，无会话存储 / 过期 / 恢复；
- ``json_response=True``：单次 JSON-RPC 请求返回单个 JSON 响应；
- 不实现旧协议 ``initialize``、不发送也不要求 ``Mcp-Session-Id``；
- 协议 ``2026-07-28`` 时代通过 ``server/discover`` 发现能力；
- 保留独立的 ``GET /health`` 健康检查端点。
"""

from __future__ import annotations

from importlib.metadata import PackageNotFoundError, version as package_version
from typing import TYPE_CHECKING

from mcp.server.mcpserver import MCPServer
from mcp_types.version import LATEST_MODERN_VERSION
from starlette.responses import JSONResponse

from . import __version__
from .config import DEFAULT_BASE_URL, Settings
from .rest_client import PetHospitalClient
from .tools import ListPetsValidationMiddleware, register_list_pets

if TYPE_CHECKING:
    from starlette.applications import Starlette

SERVER_NAME = "pet-hospital-mcp"
MCP_PATH = "/mcp"
HEALTH_PATH = "/health"
INSTRUCTIONS = (
    "宠物医院 MCP 服务：封装 Go 宠物医院 REST API。"
    "协议 2026-07-28，无状态 Streamable HTTP。"
    "阶段一仅提供 list_pets 工具，用于查询宠物档案列表（过滤 / 排序 / 分页）。"
)


def mcp_sdk_version() -> str:
    try:
        return package_version("mcp")
    except PackageNotFoundError:  # pragma: no cover
        return "unknown"


def create_server(client: PetHospitalClient, *, upstream_base_url: str = DEFAULT_BASE_URL) -> MCPServer:
    """创建并注册 MCPServer（含 /health 与阶段一唯一工具 list_pets）。"""
    server = MCPServer(
        SERVER_NAME,
        version=__version__,
        instructions=INSTRUCTIONS,
        middleware=[ListPetsValidationMiddleware()],
    )

    register_list_pets(server, client)

    @server.custom_route(HEALTH_PATH, methods=["GET"])
    async def health_check(_request: object) -> JSONResponse:
        return JSONResponse(
            {
                "status": "healthy",
                "service": SERVER_NAME,
                "version": __version__,
                "mcpSdkVersion": mcp_sdk_version(),
                "protocolVersion": LATEST_MODERN_VERSION,
                "transport": "streamable-http-stateless",
                "mcpEndpoint": MCP_PATH,
                "upstreamBaseUrl": upstream_base_url,
            }
        )

    return server


def create_starlette_app(server: MCPServer, *, host: str) -> "Starlette":
    """装配无状态 Streamable HTTP Starlette 应用。"""
    return server.streamable_http_app(
        streamable_http_path=MCP_PATH,
        stateless_http=True,
        json_response=True,
        host=host,
    )


def build_app(settings: Settings, client: PetHospitalClient) -> "Starlette":
    server = create_server(client, upstream_base_url=settings.pet_hospital_base_url)
    return create_starlette_app(server, host=settings.mcp_host)
