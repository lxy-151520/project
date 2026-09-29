"""运行配置：全部来自环境变量，教学场景不读取配置文件。"""

from __future__ import annotations

import os
from dataclasses import dataclass

DEFAULT_BASE_URL = "http://127.0.0.1:8080"
DEFAULT_HOST = "127.0.0.1"
DEFAULT_PORT = 8000
DEFAULT_TIMEOUT_SECONDS = 5.0
DEFAULT_MAX_RETRIES = 2
DEFAULT_LOG_LEVEL = "INFO"


def _env_str(name: str, default: str) -> str:
    value = os.environ.get(name)
    if value is None or value.strip() == "":
        return default
    return value.strip()


def _env_float(name: str, default: float) -> float:
    raw = os.environ.get(name)
    if raw is None or raw.strip() == "":
        return default
    try:
        value = float(raw)
    except ValueError:
        return default
    return value if value > 0 else default


def _env_int(name: str, default: int) -> int:
    raw = os.environ.get(name)
    if raw is None or raw.strip() == "":
        return default
    try:
        value = int(raw)
    except ValueError:
        return default
    return value if value >= 0 else default


@dataclass(frozen=True)
class Settings:
    """MCP 服务与上游 Go REST API 的连接配置。"""

    mcp_host: str
    mcp_port: int
    pet_hospital_base_url: str
    backend_timeout_seconds: float
    backend_max_retries: int
    log_level: str

    @classmethod
    def from_env(cls) -> "Settings":
        return cls(
            mcp_host=_env_str("MCP_HOST", DEFAULT_HOST),
            mcp_port=_env_int("MCP_PORT", DEFAULT_PORT),
            pet_hospital_base_url=_env_str("PET_HOSPITAL_BASE_URL", DEFAULT_BASE_URL).rstrip("/"),
            backend_timeout_seconds=_env_float("PET_HOSPITAL_TIMEOUT_SECONDS", DEFAULT_TIMEOUT_SECONDS),
            backend_max_retries=_env_int("PET_HOSPITAL_MAX_RETRIES", DEFAULT_MAX_RETRIES),
            log_level=_env_str("LOG_LEVEL", DEFAULT_LOG_LEVEL).upper(),
        )
