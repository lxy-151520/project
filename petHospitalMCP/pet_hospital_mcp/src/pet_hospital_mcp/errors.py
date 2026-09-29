"""统一结构化错误模型与上游调用异常。

所有 MCP 工具失败都返回同一种信封（作为标记为失败的工具结果文本）::

    {"error": {"code": "ERROR_CODE", "message": "可读错误信息", "details": {}}}
"""

from __future__ import annotations

import json
from enum import Enum
from typing import Any

from pydantic import BaseModel, ConfigDict, Field


class ErrorCode(str, Enum):
    """工具错误码。"""

    VALIDATION_ERROR = "VALIDATION_ERROR"
    BACKEND_TIMEOUT = "BACKEND_TIMEOUT"
    BACKEND_UNAVAILABLE = "BACKEND_UNAVAILABLE"
    BACKEND_API_ERROR = "BACKEND_API_ERROR"
    BACKEND_INVALID_RESPONSE = "BACKEND_INVALID_RESPONSE"
    INTERNAL_ERROR = "INTERNAL_ERROR"


class ErrorDetail(BaseModel):
    model_config = ConfigDict(extra="forbid")

    code: str = Field(description="稳定的机器可读错误码")
    message: str = Field(description="面向调用方的可读错误信息")
    details: dict[str, Any] = Field(default_factory=dict, description="结构化补充信息")


class ErrorEnvelope(BaseModel):
    model_config = ConfigDict(extra="forbid")

    error: ErrorDetail


class BackendCallError(Exception):
    """调用上游 Go REST API 失败时抛出的领域异常。

    不携带 httpx / pydantic 原始堆栈，消息与 details 都经过本层整理。
    """

    def __init__(self, code: ErrorCode, message: str, details: dict[str, Any] | None = None) -> None:
        super().__init__(message)
        self.code = code
        self.message = message
        self.details: dict[str, Any] = details or {}

    def to_envelope(self) -> ErrorEnvelope:
        return ErrorEnvelope(
            error=ErrorDetail(code=self.code.value, message=self.message, details=dict(self.details))
        )


def make_error_envelope(
    code: ErrorCode, message: str, details: dict[str, Any] | None = None
) -> ErrorEnvelope:
    return ErrorEnvelope(
        error=ErrorDetail(code=code.value, message=message, details=dict(details or {}))
    )


def envelope_to_json(envelope: ErrorEnvelope) -> str:
    """序列化为紧凑 JSON 文本（保留中文、不转义非 ASCII）。"""
    return json.dumps(
        envelope.model_dump(mode="json"),
        ensure_ascii=False,
        separators=(",", ":"),
    )
