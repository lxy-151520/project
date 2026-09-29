# AnythingLLM MCP Server

MCP **2026-07-28** 版本的 Python MCP Server（Streamable HTTP，无状态，仅 JSON 响应，不使用 stdio），调用本机 AnythingLLM，暴露一个工具：

- `ask_workspace(message)` — 查询**第一个工作区**，从其知识库检索信息并由 AI 回答（`mode: "query"`）。

## 运行

```bash
python server.py
```

监听 `http://127.0.0.1:8848/mcp`（仅 localhost）。零第三方依赖，Python 3.8+。

## MCP 客户端连接

Streamable HTTP 端点：`http://127.0.0.1:8848/mcp`

2026-07-28 版无 `initialize` 握手、无会话；每个请求一个 POST，必须携带：

| Header | 值 |
| --- | --- |
| `MCP-Protocol-Version` | `2026-07-28`（须与 body `_meta` 一致） |
| `Mcp-Method` | 如 `tools/list`、`tools/call` |
| `Mcp-Name` | `tools/call` 时为工具名 |
| `Accept` | `application/json, text/event-stream` |

body 的 `params._meta` 必须含 `io.modelcontextprotocol/protocolVersion` 与 `io.modelcontextprotocol/clientCapabilities`。

示例（列出工具）：

```bash
curl -s http://127.0.0.1:8848/mcp -H "Content-Type: application/json" ^
  -H "Accept: application/json, text/event-stream" ^
  -H "MCP-Protocol-Version: 2026-07-28" -H "Mcp-Method: tools/list" ^
  -d "{\"jsonrpc\":\"2.0\",\"id\":1,\"method\":\"tools/list\",\"params\":{\"_meta\":{\"io.modelcontextprotocol/protocolVersion\":\"2026-07-28\",\"io.modelcontextprotocol/clientCapabilities\":{}}}}"
```

## 配置

`server.py` 顶部常量：

```python
ALLM_API = "http://localhost:3001/api"
ALLM_KEY = "<AnythingLLM 开发者 API key>"   # Settings → Developer API，不是模型 sk- key
```

## 行为约定

- `GET`/`DELETE` → 405（无 GET 流、无会话）；未知方法 → 404 + `-32601`
- 头与 body 不一致/缺失 → 400 + `-32020 HeaderMismatch`
- 协议版本不支持 → 400 + `-32022`；缺 `_meta` 必填字段 → 400 + `-32602`
- 非本机 `Origin` → 403（防 DNS rebinding）
- AnythingLLM 调用失败 → JSON-RPC `-32603`，`data` 含 HTTP 状态与响应体

## 文件

- `server.py` — 服务端全部逻辑
- `README.md` — 本说明
