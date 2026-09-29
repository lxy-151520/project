"""AnythingLLM MCP Server - MCP 2026-07-28, Streamable HTTP (JSON only, stateless).

运行: python server.py   ->  POST http://127.0.0.1:8848/mcp
"""
import base64
import json
import urllib.error
import urllib.parse
import urllib.request
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

# ---------- 配置 ----------
HOST, PORT = "127.0.0.1", 8848
PROTOCOL_VERSION = "2026-07-28"
ALLM_API = "http://localhost:3001/api"
ALLM_KEY = "SJAK8HK-N8P46VM-P2APCQD-2Y7BZM6"

SUPPORTED = [PROTOCOL_VERSION]
_local_hosts = ("127.0.0.1", "localhost")
_slug_cache = None


class AllmError(Exception):
    def __init__(self, status, body):
        super().__init__(f"AnythingLLM HTTP {status}: {body}")
        self.status, self.body = status, body


def allm(method, path, payload=None):
    req = urllib.request.Request(
        ALLM_API + path,
        data=None if payload is None else json.dumps(payload).encode("utf-8"),
        method=method,
        headers={"Authorization": "Bearer " + ALLM_KEY,
                 "Content-Type": "application/json"},
    )
    try:
        with urllib.request.urlopen(req, timeout=300) as resp:
            return json.loads(resp.read().decode("utf-8"))
    except urllib.error.HTTPError as e:
        raise AllmError(e.code, e.read().decode("utf-8", "replace")) from None


def first_workspace_slug():
    global _slug_cache
    if _slug_cache is None:
        workspaces = allm("GET", "/v1/workspaces").get("workspaces") or []
        if not workspaces:
            raise AllmError(500, "no workspaces found")
        _slug_cache = workspaces[0]["slug"]
    return _slug_cache


def ask_workspace(message):
    """query 模式: 从第一个工作区向量库检索信息并由 AI 回答。"""
    slug = first_workspace_slug()
    data = allm("POST", f"/v1/workspace/{slug}/chat",
                {"message": message, "mode": "query"})
    if data.get("error"):
        raise AllmError(500, str(data["error"]))
    return data.get("textResponse") or "", data.get("sources") or []


def rpc_ok(rid, result):
    return {"jsonrpc": "2.0", "id": rid, "result": result}


def rpc_err(rid, code, message, data=None):
    err = {"code": code, "message": message}
    if data is not None:
        err["data"] = data
    return {"jsonrpc": "2.0", "id": rid, "error": err}


def decode_header(value):
    """解码 Mcp-Name 的 Base64 sentinel 格式，其余原样返回。"""
    if value.startswith("=?base64?") and value.endswith("?="):
        return base64.b64decode(value[len("=?base64?"):-2]).decode("utf-8")
    return value


class Handler(BaseHTTPRequestHandler):
    protocol_version = "HTTP/1.1"

    def log_message(self, fmt, *args):
        print(f"[mcp] {fmt % args}")

    def _send(self, status, obj=None):
        body = b"" if obj is None else json.dumps(obj, ensure_ascii=False).encode("utf-8")
        self.send_response(status)
        if obj is not None:
            self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        if body:
            self.wfile.write(body)

    def do_GET(self):
        self._send(405)  # 2026-07-28: 无 GET 流端点

    def do_DELETE(self):
        self._send(405)  # 无会话

    def do_POST(self):
        if self.path.split("?")[0] != "/mcp":
            self._send(404)
            return
        origin = self.headers.get("Origin")
        if origin and (urllib.parse.urlsplit(origin).hostname not in _local_hosts):
            self._send(403, rpc_err(None, -32600, "Invalid Origin"))
            return
        try:
            msg = json.loads(self.rfile.read(int(self.headers.get("Content-Length") or 0)))
            if not isinstance(msg, dict):
                raise ValueError
        except ValueError:
            self._send(400, rpc_err(None, -32700, "Parse error"))
            return

        if "id" not in msg:  # 通知
            self._send(202)
            return

        status, resp = self._handle(msg)
        self._send(status, resp)

    def _handle(self, msg):
        rid = msg.get("id")
        params = msg.get("params") or {}
        meta = params.get("_meta") or {}
        method = msg.get("method")

        # --- 协议版本: 头与 body 一致性 + 版本支持 ---
        hv = self.headers.get("MCP-Protocol-Version")
        bv = meta.get("io.modelcontextprotocol/protocolVersion")
        if not hv or not bv or hv != bv:
            return 400, rpc_err(rid, -32020, "HeaderMismatch: MCP-Protocol-Version missing or does not match body")
        if bv not in SUPPORTED:
            return 400, rpc_err(rid, -32022, "Unsupported protocol version", {"supported": SUPPORTED})

        # --- _meta 必填字段 ---
        if not isinstance(meta.get("io.modelcontextprotocol/clientCapabilities"), dict):
            return 400, rpc_err(rid, -32602, "Invalid params: _meta.io.modelcontextprotocol/clientCapabilities is required")

        # --- Mcp-Method 一致性 ---
        if not isinstance(method, str):
            return 400, rpc_err(rid, -32600, "Invalid request: method is required")
        hm = self.headers.get("Mcp-Method")
        if not hm or hm != method:
            return 400, rpc_err(rid, -32020, f"HeaderMismatch: Mcp-Method '{hm}' != body method '{method}'")

        # --- Mcp-Name 一致性 (tools/call) ---
        if method == "tools/call":
            name = params.get("name")
            hn = self.headers.get("Mcp-Name")
            if not hn or decode_header(hn) != name:
                return 400, rpc_err(rid, -32020, f"HeaderMismatch: Mcp-Name '{hn}' != body name '{name}'")

        if method == "tools/list":
            return 200, rpc_ok(rid, {
                "resultType": "complete",
                "tools": [{
                    "name": "ask_workspace",
                    "description": "查询 AnythingLLM 第一个工作区：从该工作区知识库中检索相关信息，并由 AI 生成回答。",
                    "inputSchema": {
                        "type": "object",
                        "properties": {
                            "message": {"type": "string", "description": "要提问的问题"}
                        },
                        "required": ["message"],
                        "additionalProperties": False,
                    },
                }],
                "_meta": {"io.modelcontextprotocol/serverInfo":
                          {"name": "anythingllm-mcp", "version": "0.1.0"}},
            })

        if method == "tools/call":
            return self._call_tool(rid, params)

        return 404, rpc_err(rid, -32601, f"Method not found: {method}")

    def _call_tool(self, rid, params):
        name, args = params.get("name"), params.get("arguments") or {}
        if name != "ask_workspace":
            return 200, rpc_err(rid, -32602, f"Unknown tool: {name}")
        message = args.get("message")
        if not isinstance(message, str) or not message.strip():
            return 200, rpc_err(rid, -32602, "Invalid params: 'message' (non-empty string) is required")
        try:
            answer, sources = ask_workspace(message)
        except AllmError as e:
            return 200, rpc_err(rid, -32603, f"AnythingLLM error: {e}",
                                 {"status": e.status, "body": e.body})
        return 200, rpc_ok(rid, {
            "resultType": "complete",
            "content": [{"type": "text", "text": answer}],
            "structuredContent": {"answer": answer, "sources": sources},
            "_meta": {"io.modelcontextprotocol/serverInfo":
                      {"name": "anythingllm-mcp", "version": "0.1.0"}},
        })


if __name__ == "__main__":
    print(f"MCP server listening on http://{HOST}:{PORT}/mcp (protocol {PROTOCOL_VERSION})")
    ThreadingHTTPServer((HOST, PORT), Handler).serve_forever()
