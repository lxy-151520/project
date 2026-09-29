"""``python -m pet_hospital_mcp`` 入口。

先启动 Go 宠物医院 REST API（默认 http://127.0.0.1:8080），再启动本服务。
可用环境变量：``MCP_HOST``、``MCP_PORT``、``PET_HOSPITAL_BASE_URL``、
``PET_HOSPITAL_TIMEOUT_SECONDS``、``PET_HOSPITAL_MAX_RETRIES``、``LOG_LEVEL``。
"""

from __future__ import annotations

import asyncio
import signal

import uvicorn
from mcp_types.version import LATEST_MODERN_VERSION

from .config import Settings
from .logging_config import get_logger, setup_logging
from .rest_client import PetHospitalClient
from .server import MCP_PATH, SERVER_NAME, build_app, mcp_sdk_version


async def _serve(settings: Settings) -> None:
    logger = get_logger()
    async with PetHospitalClient(
        settings.pet_hospital_base_url,
        timeout=settings.backend_timeout_seconds,
        max_retries=settings.backend_max_retries,
    ) as client:
        app = build_app(settings, client)
        config = uvicorn.Config(
            app,
            host=settings.mcp_host,
            port=settings.mcp_port,
            log_level=settings.log_level.lower(),
            access_log=False,
        )
        server = uvicorn.Server(config)

        print("=" * 72)
        print(f"  {SERVER_NAME} 已启动（无状态 Streamable HTTP）")
        print(f"  MCP SDK: mcp=={mcp_sdk_version()}   协议版本: {LATEST_MODERN_VERSION}")
        print(f"  MCP 端点 : http://{settings.mcp_host}:{settings.mcp_port}{MCP_PATH}")
        print(f"  健康检查 : http://{settings.mcp_host}:{settings.mcp_port}/health")
        print(f"  上游 Go  : {settings.pet_hospital_base_url}")
        print("  按 Ctrl+C 退出")
        print("=" * 72)

        task = asyncio.create_task(server.serve())
        loop = asyncio.get_running_loop()
        for sig_name in ("SIGINT", "SIGTERM"):
            sig = getattr(signal, sig_name, None)
            if sig is not None:
                try:
                    loop.add_signal_handler(sig, task.cancel)
                except NotImplementedError:  # pragma: no cover - Windows
                    pass
        try:
            await task
        except asyncio.CancelledError:
            pass
        finally:
            logger.info("service stopped")


def main() -> None:
    settings = Settings.from_env()
    setup_logging(settings.log_level)
    try:
        asyncio.run(_serve(settings))
    except (KeyboardInterrupt, SystemExit):
        pass


if __name__ == "__main__":
    main()
