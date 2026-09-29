# Pet Hospital MCP Server

把现有 **Go 宠物医院 REST API** 暴露给 AI Agent 的独立 Python MCP 服务。

- 语言：Python 3.11+（开发环境 Python 3.13）
- MCP SDK：**官方 Python SDK `mcp==2.0.0`（SDK 2.x 的 `MCPServer`，不使用 FastMCP）**
- 协议版本：**MCP `2026-07-28`**
- 传输模型：**无状态 Streamable HTTP**（`stateless_http=True`、`json_response=True`）
- 阶段一只有一个工具：`list_pets`

> 无状态含义：每个 HTTP POST 都是自包含的一次 JSON-RPC 请求/响应，
> **没有旧协议 `initialize` 握手、没有 `Mcp-Session-Id`、没有会话存储/过期/恢复**。
> 能力发现使用 `2026-07-28` 的 `server/discover`。

## 目录结构

```text
pet_hospital_mcp/
├── pyproject.toml
├── README.md
├── UPGRADE_PROMPT.md
├── src/pet_hospital_mcp/
│   ├── __init__.py
│   ├── __main__.py          # python -m pet_hospital_mcp 入口（uvicorn）
│   ├── config.py            # 环境变量配置
│   ├── server.py            # MCPServer + 无状态 Streamable HTTP 装配 + /health
│   ├── rest_client.py       # Go REST API 异步客户端（超时/重试/错误分类）
│   ├── errors.py            # 统一结构化错误模型
│   ├── logging_config.py    # JSON logging + 敏感字段递归脱敏
│   └── tools/
│       ├── __init__.py
│       └── list_pets.py     # list_pets 工具：输入/输出模型 + 校验中间件
└── tests/                   # pytest + httpx.MockTransport，禁止访问真实 Go
```

## 1. 先启动 Go REST API

MCP 服务只是适配层，必须先启动 Go 宠物医院服务（默认监听 `http://127.0.0.1:8080`）。
确认后端可用：

```bash
curl http://127.0.0.1:8080/api/v1/pets?page=1&pageSize=1
```

## 2. 安装与启动 MCP 服务

```bash
cd pet_hospital_mcp

# 创建虚拟环境（已提供 .venv 可跳过）
python -m venv .venv
.venv\Scripts\activate            # Windows PowerShell: .venv\Scripts\Activate.ps1

pip install -e ".[dev]"

# 启动（先确保 Go 已在 8080 运行）
python -m pet_hospital_mcp
```

启动后看到：

```text
MCP 端点 : http://127.0.0.1:8000/mcp
健康检查 : http://127.0.0.1:8000/health
上游 Go  : http://127.0.0.1:8080
```

### 环境变量

| 变量 | 默认值 | 说明 |
| --- | --- | --- |
| `MCP_HOST` | `127.0.0.1` | MCP 服务监听地址（仅本机） |
| `MCP_PORT` | `8000` | MCP 服务监听端口 |
| `PET_HOSPITAL_BASE_URL` | `http://127.0.0.1:8080` | Go REST API 地址 |
| `PET_HOSPITAL_TIMEOUT_SECONDS` | `5` | 单次上游调用超时 |
| `PET_HOSPITAL_MAX_RETRIES` | `2` | 网络错误 / 5xx / 429 的最大重试次数 |
| `LOG_LEVEL` | `INFO` | 日志级别 |

教学场景：不实现认证、权限、CORS、Origin 校验。

## 3. 端点说明

| 端点 | 方法 | 说明 |
| --- | --- | --- |
| `/mcp` | `POST` | 无状态 MCP JSON-RPC 端点（一请求一响应） |
| `/health` | `GET` | 健康检查，返回服务/SDK/协议/上游信息 |

`GET /mcp` 在 `2026-07-28` 现代路径下返回 `405 Method Not Allowed`：
不存在 SSE 订阅端点，也不会下发任何会话标识。

### 2026-07-28 请求长什么样

每个请求必须：

- HTTP 头携带 `MCP-Protocol-Version: 2026-07-28`、`MCP-Method: <方法名>`；
  调用工具时还要带 `MCP-Name: <工具名>`；
- `Accept` 包含 `application/json`；
- body 的 `params._meta` 携带
  `"io.modelcontextprotocol/protocolVersion": "2026-07-28"` 与
  `"io.modelcontextprotocol/clientCapabilities": {}`；
- **不需要**任何前置 `initialize`，请求之间相互独立。

## 4. 验证步骤

### 4.1 健康检查

```bash
curl http://127.0.0.1:8000/health
```

```json
{
  "status": "healthy",
  "service": "pet-hospital-mcp",
  "version": "1.0.0",
  "mcpSdkVersion": "2.0.0",
  "protocolVersion": "2026-07-28",
  "transport": "streamable-http-stateless",
  "mcpEndpoint": "/mcp",
  "upstreamBaseUrl": "http://127.0.0.1:8080"
}
```

### 4.2 能力发现（server/discover）

```bash
curl -i -X POST http://127.0.0.1:8000/mcp ^
  -H "Content-Type: application/json" ^
  -H "Accept: application/json" ^
  -H "MCP-Protocol-Version: 2026-07-28" ^
  -H "MCP-Method: server/discover" ^
  -d "{\"jsonrpc\":\"2.0\",\"id\":1,\"method\":\"server/discover\",\"params\":{\"_meta\":{\"io.modelcontextprotocol/protocolVersion\":\"2026-07-28\",\"io.modelcontextprotocol/clientCapabilities\":{}}}}"
```

响应 `result.supportedVersions` 包含 `2026-07-28`，`result.capabilities.tools` 存在；
**响应头中没有 `mcp-session-id`**。

### 4.3 列出工具（tools/list）

```bash
curl -X POST http://127.0.0.1:8000/mcp ^
  -H "Content-Type: application/json" -H "Accept: application/json" ^
  -H "MCP-Protocol-Version: 2026-07-28" -H "MCP-Method: tools/list" ^
  -d "{\"jsonrpc\":\"2.0\",\"id\":2,\"method\":\"tools/list\",\"params\":{\"_meta\":{\"io.modelcontextprotocol/protocolVersion\":\"2026-07-28\",\"io.modelcontextprotocol/clientCapabilities\":{}}}}"
```

只返回一个工具：`list_pets`，其中 `inputSchema` 声明了全部 14 个查询参数、
枚举允许值与数值范围。

### 4.4 调用 list_pets（tools/call）

调用头需要额外的 `MCP-Name: list_pets`：

```bash
curl -X POST http://127.0.0.1:8000/mcp ^
  -H "Content-Type: application/json" -H "Accept: application/json" ^
  -H "MCP-Protocol-Version: 2026-07-28" -H "MCP-Method: tools/call" -H "MCP-Name: list_pets" ^
  -d "{\"jsonrpc\":\"2.0\",\"id\":3,\"method\":\"tools/call\",\"params\":{\"_meta\":{\"io.modelcontextprotocol/protocolVersion\":\"2026-07-28\",\"io.modelcontextprotocol/clientCapabilities\":{}},\"name\":\"list_pets\",\"arguments\":{\"species\":\"犬\",\"status\":\"已康复\",\"min\":100,\"max\":5000,\"sortBy\":\"totalCost\",\"order\":\"desc\",\"page\":1,\"pageSize\":20}}}"
```

成功结果（`result.content[0].text` 即 JSON 文本，对应 Go 信封的 `data`）：

```json
{
  "items": [
    {
      "id": "PET-1001",
      "name": "旺财",
      "species": "犬",
      "records": ["...病历对象..."],
      "charges": ["...收费对象..."]
    }
  ],
  "total": 2,
  "page": 1,
  "pageSize": 20,
  "totalPages": 1,
  "totalCost": 320.5
}
```

Go 对新档案可能把 `records` / `charges` 序列化为 `null`，本服务统一归一化为 `[]`。

### 4.5 错误长什么样

非法输入（如 `pageSize=9999`、未知字段、`min>max`、NaN）会在 SDK 参数校验之前
被本服务中间件拦截，返回 HTTP 200 的工具失败结果（`result.isError: true`），
文本内容为统一错误信封：

```json
{
  "error": {
    "code": "VALIDATION_ERROR",
    "message": "list_pets 输入参数校验失败",
    "details": { "validationErrors": [ { "loc": ["pageSize"], "msg": "..." } ] }
  }
}
```

错误码：`VALIDATION_ERROR`、`BACKEND_TIMEOUT`、`BACKEND_UNAVAILABLE`、
`BACKEND_API_ERROR`、`BACKEND_INVALID_RESPONSE`、`INTERNAL_ERROR`。
httpx / Pydantic / SDK / Python 的原始异常类型与堆栈不会暴露给客户端。

### 4.6 MCP Inspector / SDK 2.x 客户端

- MCP Inspector 连接类型选择 **Streamable HTTP**，URL 填 `http://127.0.0.1:8000/mcp`；
  客户端需按 `2026-07-28` 发送无状态信封（自动带协议发现与 `MCP-*` 头），
  不进行旧 `initialize` 握手。
- 也可以用任意 SDK 2.x 的 streamable-http 客户端以无状态方式直连 `/mcp`；
- 最可靠的手工验证方式是 4.2–4.4 的 `curl`（不依赖任何会话状态，重复发送结果一致）。

## 5. list_pets 工具

适配 `GET /api/v1/pets`，**只支持**以下 14 个参数（与 Go 查询参数同名，无私有参数）：

| 参数 | 类型 / 允许值 | 约束 |
| --- | --- | --- |
| `q` | string | 全文检索关键词 |
| `name` | string | 宠物姓名 |
| `ownerName` | string | 主人姓名 |
| `ownerPhone` | string | 主人电话 |
| `species` | enum | 犬 / 猫 / 兔 / 鸟 / 仓鼠 / 爬宠 / 其他 |
| `doctor` | string | 主治医生 |
| `disease` | string | 疾病关键词 |
| `status` | enum | 待就诊 / 就诊中 / 住院中 / 已康复 / 慢性病随访 |
| `min` | number | 总花费下限，非负 |
| `max` | number | 总花费上限，非负，且 `min <= max` |
| `sortBy` | enum | id/name/ownerName/species/doctor/disease/status/totalCost/visitCount/createdAt/updatedAt |
| `order` | enum | `asc` / `desc` |
| `page` | integer | `>= 1` |
| `pageSize` | integer | `1 <= pageSize <= 500` |

严格校验：拒绝未知字段、NaN/Infinity、类型不匹配、数字字符串隐式转换、布尔冒充整数。

## 6. 日志

标准库 JSON logging（stdout）。每次工具调用输出一条结构化记录，至少包含：
`timestamp`、`tool_name`、`params`、`status`、`duration_ms`，
失败时额外包含 `error_code`。

`ownerPhone`、`ownerAddr`、`chipNo` 及其 snake_case
（`owner_phone`、`owner_addr`、`chip_no`）在任意嵌套层级都会被替换为
`***REDACTED***`，敏感数据不落盘。

## 7. 运行测试

测试全部使用 `httpx.MockTransport` 与进程内 ASGI `TestClient`，
**不会访问真实 Go 服务**。

```bash
cd pet_hospital_mcp
pytest -q
```

预期结果：

```text
.......................................................................
55 passed
```

覆盖：参数完整转发、输入校验失败、4xx/5xx、5xx 重试、超时与连接异常、
非法 JSON / 不符数据模型、工具注册与 JSON Schema、
`2026-07-28` 无状态发现/调用流程、无 `Mcp-Session-Id`、`/health`、
`GET /mcp` 405、缺失现代信封拒绝。
