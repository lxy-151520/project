"""Go 宠物医院 REST API 的异步 HTTP 客户端。

职责：
- 只通过 HTTP 调用上游，默认 ``GET /api/v1/pets``；
- 每次调用带超时，网络错误 / 5xx / 429 做有限重试；
- 把所有底层异常归类为统一的 ``BackendCallError``，不向 MCP 层暴露
  httpx 原始异常类型或堆栈。

测试时可通过 ``transport=httpx.MockTransport(...)`` 注入，不产生真实网络访问。
"""

from __future__ import annotations

from collections.abc import Mapping
from typing import Any

import httpx

from .errors import BackendCallError, ErrorCode

PETS_PATH = "/api/v1/pets"

# 第 n 次重试前的等待秒数（短，便于教学与测试）
_RETRY_BACKOFF_SECONDS: tuple[float, ...] = (0.02, 0.05)
_RETRYABLE_STATUS = frozenset({429, *range(500, 600)})


class PetHospitalClient:
    def __init__(
        self,
        base_url: str,
        *,
        timeout: float = 5.0,
        max_retries: int = 2,
        transport: httpx.AsyncBaseTransport | None = None,
    ) -> None:
        if not base_url or not base_url.strip():
            raise ValueError("base_url 不能为空")
        self._base_url = base_url.rstrip("/")
        self._timeout = timeout
        self._max_retries = max(0, max_retries)
        self._transport = transport
        self._client: httpx.AsyncClient | None = None

    async def __aenter__(self) -> "PetHospitalClient":
        return self

    async def __aexit__(self, *_exc: object) -> None:
        await self.aclose()

    def _get_client(self) -> httpx.AsyncClient:
        if self._client is None or self._client.is_closed:
            self._client = httpx.AsyncClient(
                base_url=self._base_url,
                timeout=httpx.Timeout(self._timeout, connect=self._timeout),
                transport=self._transport,
                headers={"Accept": "application/json"},
            )
        return self._client

    async def aclose(self) -> None:
        if self._client is not None and not self._client.is_closed:
            await self._client.aclose()
        self._client = None

    async def list_pets(self, params: Mapping[str, Any]) -> dict[str, Any]:
        """调用 ``GET /api/v1/pets``，成功时返回 Go 信封里的 ``data`` 对象。"""
        query = {key: value for key, value in params.items() if value is not None}
        return await self._get_json_with_retry(PETS_PATH, query)

    async def _get_json_with_retry(
        self, path: str, query: Mapping[str, Any]
    ) -> dict[str, Any]:
        attempts_max = self._max_retries + 1
        last_network_error: BackendCallError | None = None

        for attempt in range(1, attempts_max + 1):
            try:
                response = await self._get_client().get(path, params=dict(query))
            except httpx.TimeoutException:
                last_network_error = BackendCallError(
                    ErrorCode.BACKEND_TIMEOUT,
                    f"调用宠物医院服务超时（{self._timeout:g} 秒）",
                    {"path": path, "attempts": attempt},
                )
                if await self._should_retry(attempt):
                    continue
                raise last_network_error
            except httpx.TransportError:
                last_network_error = BackendCallError(
                    ErrorCode.BACKEND_UNAVAILABLE,
                    "无法连接宠物医院服务，请确认 Go REST API 已启动",
                    {"path": path, "attempts": attempt},
                )
                if await self._should_retry(attempt):
                    continue
                raise last_network_error

            if response.status_code in _RETRYABLE_STATUS and attempt < attempts_max:
                await self._sleep(_RETRY_BACKOFF_SECONDS[min(attempt - 1, len(_RETRY_BACKOFF_SECONDS) - 1)])
                continue

            if response.status_code >= 400:
                raise self._build_http_error(response, attempt)

            return self._parse_success(response, attempt)

        # 理论上不可达：循环要么 return 要么 raise
        raise last_network_error or BackendCallError(
            ErrorCode.INTERNAL_ERROR, "后端调用失败", {"path": path}
        )

    async def _should_retry(self, attempt: int) -> bool:
        if attempt >= self._max_retries + 1:
            return False
        await self._sleep(_RETRY_BACKOFF_SECONDS[min(attempt - 1, len(_RETRY_BACKOFF_SECONDS) - 1)])
        return True

    @staticmethod
    async def _sleep(seconds: float) -> None:
        import anyio

        await anyio.sleep(seconds)

    @staticmethod
    def _build_http_error(response: httpx.Response, attempts: int) -> BackendCallError:
        details: dict[str, Any] = {"httpStatus": response.status_code, "attempts": attempts}
        message: str
        try:
            payload = response.json()
        except ValueError:
            payload = None
        if isinstance(payload, dict):
            upstream_message = payload.get("message")
            if isinstance(upstream_message, str) and upstream_message.strip():
                message = f"宠物医院服务返回错误（HTTP {response.status_code}）：{upstream_message}"
            else:
                message = f"宠物医院服务返回错误（HTTP {response.status_code}）"
            if isinstance(payload.get("code"), int):
                details["upstreamCode"] = payload["code"]
        else:
            message = f"宠物医院服务返回错误（HTTP {response.status_code}）"
        return BackendCallError(ErrorCode.BACKEND_API_ERROR, message, details)

    @staticmethod
    def _parse_success(response: httpx.Response, attempts: int) -> dict[str, Any]:
        try:
            payload = response.json()
        except ValueError as exc:
            raise BackendCallError(
                ErrorCode.BACKEND_INVALID_RESPONSE,
                "宠物医院服务返回了无法解析的 JSON",
                {"path": str(response.request.url.path), "attempts": attempts},
            ) from exc

        if not isinstance(payload, dict):
            raise BackendCallError(
                ErrorCode.BACKEND_INVALID_RESPONSE,
                "宠物医院服务响应不是 JSON 对象",
                {"attempts": attempts},
            )

        upstream_code = payload.get("code")
        if upstream_code is not None and upstream_code != 200:
            raise BackendCallError(
                ErrorCode.BACKEND_API_ERROR,
                "宠物医院服务返回了失败的业务状态",
                {"upstreamCode": upstream_code, "attempts": attempts},
            )

        data = payload.get("data")
        if not isinstance(data, dict):
            raise BackendCallError(
                ErrorCode.BACKEND_INVALID_RESPONSE,
                "宠物医院服务响应缺少 data 对象",
                {"attempts": attempts},
            )
        return data
