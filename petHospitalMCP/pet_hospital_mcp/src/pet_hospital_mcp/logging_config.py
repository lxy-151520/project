"""标准库 JSON logging。

每条工具访问日志至少包含：
``timestamp``、``tool_name``、``params``、``status``、``duration_ms``。

``ownerPhone``、``ownerAddr``、``chipNo`` 及其 snake_case 写法在写入日志前
递归脱敏，完整敏感数据不落盘。
"""

from __future__ import annotations

import json
import logging
from datetime import datetime, timezone
from typing import Any

# 同时覆盖 Go 风格 camelCase 与 Python 风格 snake_case
SENSITIVE_KEYS = frozenset(
    {
        "ownerphone",
        "owneraddr",
        "chipno",
        "owner_phone",
        "owner_addr",
        "chip_no",
    }
)

REDACTED = "***REDACTED***"

_LOGGER_NAME = "pet_hospital_mcp"


def mask_sensitive(value: Any) -> Any:
    """递归遍历 dict / list，把敏感键的值替换为 ``***REDACTED***``。"""
    if isinstance(value, dict):
        masked: dict[str, Any] = {}
        for key, item in value.items():
            if isinstance(key, str) and key.lower() in SENSITIVE_KEYS:
                masked[key] = REDACTED
            else:
                masked[key] = mask_sensitive(item)
        return masked
    if isinstance(value, (list, tuple)):
        return [mask_sensitive(item) for item in value]
    return value


class _JsonFormatter(logging.Formatter):
    def format(self, record: logging.LogRecord) -> str:
        payload: dict[str, Any] = {
            "timestamp": datetime.now(timezone.utc).isoformat(),
            "level": record.levelname,
            "logger": record.name,
            "message": record.getMessage(),
        }
        extra = getattr(record, "event_fields", None)
        if isinstance(extra, dict):
            payload.update(mask_sensitive(extra))
        return json.dumps(payload, ensure_ascii=False, default=str)


def setup_logging(level: str = "INFO") -> logging.Logger:
    """配置并返回包级 logger（重复调用安全，不重复加 handler）。"""
    logger = logging.getLogger(_LOGGER_NAME)
    logger.setLevel(level.upper())
    logger.propagate = False
    if not any(getattr(h, "_pet_hospital_mcp", False) for h in logger.handlers):
        handler = logging.StreamHandler()
        handler.setFormatter(_JsonFormatter())
        handler._pet_hospital_mcp = True  # type: ignore[attr-defined]
        logger.addHandler(handler)
    return logger


def get_logger() -> logging.Logger:
    return logging.getLogger(_LOGGER_NAME)


def log_tool_event(
    *,
    tool_name: str,
    params: dict[str, Any] | None,
    status: str,
    duration_ms: float,
    error_code: str | None = None,
) -> None:
    """记录一条工具访问日志（params 自动脱敏）。"""
    fields: dict[str, Any] = {
        "tool_name": tool_name,
        "params": mask_sensitive(params or {}),
        "status": status,
        "duration_ms": round(duration_ms, 3),
    }
    if error_code is not None:
        fields["error_code"] = error_code
    logger = get_logger()
    logger.info(
        "tool invocation",
        extra={"event_fields": fields},
    )
