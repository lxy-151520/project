# 阶段二升级 Prompt（复制给下一位开发者 / AI Agent）

> 本文件是把「宠物医院 MCP 服务」从阶段一（仅 `list_pets`）升级到阶段二
> （更多 Go REST API 能力）的任务交接说明。先通读 `README.md` 再开工。

## 背景（已完成的阶段一事实，不要推翻）

- 项目目录：`pet_hospital_mcp/`，src layout，包名 `pet_hospital_mcp`。
- Python 3.11+；**官方 SDK 固定 `mcp==2.0.0`**；协议 **`2026-07-28`**。
- 使用 SDK 2.x 的 `mcp.server.mcpserver.MCPServer`；
  **严禁**导入或退回 `mcp.server.fastmcp.FastMCP`。
- 装配为**无状态 Streamable HTTP**：
  `server.streamable_http_app(streamable_http_path="/mcp", stateless_http=True, json_response=True, host=...)`。
- 不实现旧协议 `initialize`、不发送/要求 `Mcp-Session-Id`、不做会话存储、
  过期、`max_sessions`、有状态 SSE 恢复；现代客户端通过 `server/discover`
  + 每请求 `_meta` 信封（`MCP-Protocol-Version` / `MCP-Method` / `MCP-Name` 头）访问。
- 不得修改 Go 后端；只能经 HTTP 调用 `PET_HOSPITAL_BASE_URL`（默认
  `http://127.0.0.1:8080`）。
- 教学场景无认证、无 CORS、无 Origin 校验；保留 `GET /health`。
- 阶段一唯一工具：`list_pets`（适配 `GET /api/v1/pets`）。测试 55 项全绿。

## 阶段二任务

1. 先用真实运行的 Go 服务调研要新增的接口（建议从 `GET /api/v1/meta` 与
   `GET /api/v1/endpoints` 取真实契约；必要时实际请求观察响应），
   **以真实响应字段、枚举值、可空表现为准，禁止凭猜测建模。**
2. 在 `src/pet_hospital_mcp/tools/` 下为每类能力新增模块
   （如 `get_pet.py`、`create_pet.py`、`update_pet.py`、`delete_pet.py`、
   `add_visit_record.py`、`list_meta.py` 等，以实际任务要求为准）。
3. 每个工具都必须：
   - 工具名 `snake_case`；只暴露真实后端支持的参数，不造私有参数；
   - 用 Pydantic 定义**输入 / 成功输出 / 错误输出**模型；
   - 输入模型 `model_config = ConfigDict(extra="forbid")`，枚举用真实允许值，
     数值范围与跨字段约束齐全，拒绝 NaN/Infinity 与错误类型；
   - 成功输出对应 Go 成功信封中的 `data`，对 `null`/数组等真实 JSON 表现做兼容；
   - docstring 写清用途、参数、适用场景、返回值与错误码。
4. 在 `rest_client.py` 的 `PetHospitalClient` 中复用/扩展方法（GET/POST/PUT/DELETE）：
   - 统一超时与有限重试（默认仅网络错误、429、5xx 重试，写操作默认不自动重试，
     除非确认接口幂等）；
   - 所有底层异常归类为 `errors.BackendCallError`，错误码复用现有集合；
     只有确有必要时才在 `ErrorCode` 中**新增**稳定码，不要随意膨胀；
   - 不向客户端泄漏 httpx / Pydantic / SDK / Python 堆栈。
5. 每个新工具注册一个与 `ListPetsValidationMiddleware` 同构的、仅拦截自己工具的
   `ServerMiddleware`（按 `ctx.method == "tools/call"` 与
   `ctx.params["name"] == 工具名` 过滤），在 SDK 参数校验前完成权威校验并短路返回
   统一错误 `CallToolResult(is_error=True)`；不要把非法输入放给 SDK 变成
   顶层 JSON-RPC `INVALID_PARAMS`。
6. 在 `server.py` 的 `create_server()` 中注册新工具与对应中间件。
7. 写操作若包含敏感字段（主人电话/地址/芯片号等），日志输出必须继续经过
   `logging_config.mask_sensitive`；出现新的敏感字段名时，把键名
   （camelCase 与 snake_case 都要）加进 `SENSITIVE_KEYS`。
8. 为每个新工具补测试，继续使用 `pytest` + `pytest-asyncio` +
   `httpx.MockTransport` + Starlette `TestClient` 的 2026-07-28 信封写法
   （参考 `tests/conftest.py`）：**禁止访问真实 Go 服务**。至少覆盖：
   正常转发与成功建模、输入校验失败、4xx/5xx、超时/连接异常、非法 JSON/不符模型、
   工具注册名与 JSON Schema、无状态 HTTP 调用与无 `Mcp-Session-Id`。
   保持 `cd pet_hospital_mcp && pytest -q` 全绿。
9. 更新 `README.md`（工具清单、参数表、调用示例），但保留无状态/错误码/日志章节。

## 硬性禁令（阶段二同样适用）

- 不修改 Go 代码、不在 Python 侧直连 SQLite、不复制业务逻辑；
- 不引入会话状态、不实现握手兼容、不换传输模式；
- 不把上游原始异常文本、堆栈、内部 URL/凭据写进工具错误或日志；
- 不新增任务未要求的工具，不做认证/CORS 等超范围改造；
- 不降低既有测试质量：阶段一的 55 项测试必须持续通过。

## 验收交付

完成后输出：新增/修改文件列表、真实 `pytest -q` 结果、新工具的 curl
无状态调用示例（含必需 `MCP-*` 头与 `_meta` 信封）、错误信封示例、
以及「未实现的能力」清单。
