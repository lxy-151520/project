# xAgent

基于 Practice02 `chat-stream-tool-fileOps.py` 重构的 **core/UI 分离** 智能体。
核心业务逻辑(LLM 调用、function call 循环、工具集)与界面完全解耦,**前端按目录平级扩展**。

## 架构

```
xAgent/
├── core/                    # 核心层 (纯 Python,不依赖任何 UI 库)
│   ├── config.py           # 配置加载 (config.ini)
│   ├── llm.py              # LLM 客户端 (OpenAI 兼容接口,非流式+流式)
│   ├── agent.py            # Agent 主循环 + AgentCallbacks 事件回调
│   └── tools/
│       ├── system_tools.py # getDate / isLeapYear / getCWD / getFileType
│       ├── file_tools.py   # 8 个文件目录操作
│       └── __init__.py     # TOOL_MAP + TOOL_SCHEMAS 汇总
│
├── tui/                     # TUI 前端(Textual,终端图形界面)
│   ├── __init__.py
│   └── app.py              # XAgentApp
│
├── web/                     # 未来: Web 前端(FastAPI + 浏览器)
├── desktop/                 # 未来: 桌面前端(PySide6 / Electron)
├── mobile/                  # 未来: 移动前端(Kivy / 小程序)
│
├── main.py                  # 入口: 默认启动 tui
└── config.ini               # LLM 配置(不随 Git 提交)
```

## 核心设计

| 层 | 职责 | 依赖 |
|---|---|---|
| `core`     | LLM 通信、消息历史、工具调度 | 仅标准库 + `requests` |
| `tui`      | 终端 UI | `core.AgentCallbacks` + `textual` |
| `web`      | 浏览器 UI(未来) | 同上 |
| `desktop`  | 桌面 UI(未来) | 同上 |
| `mobile`   | 移动 UI(未来) | 同上 |

**任何前端只需实现 `AgentCallbacks` 中 6 个回调即可接入 core**:

```python
AgentCallbacks(
    on_user_message  = ...,   # 用户消息
    on_tool_call     = ...,   # 工具被调用
    on_tool_result   = ...,   # 工具返回
    on_token         = ...,   # 流式 token
    on_response_done = ...,   # 完整回复
    on_error         = ...,   # 错误
)
```

新增前端 = 新建目录 + 实现回调 + 启动 App,**core 代码零改动**。

## 运行

```powershell
# 安装依赖 (一次性)
pip install textual requests

# 在 Agent/ 目录下启动 TUI
python -m xAgent.main
```

注意 `config.ini` 需要放在运行目录(`xAgent/`)下。

## 测试提问

- `今天日期是多少?` → 调 `getDate`
- `2024 年是闰年吗?` → 调 `isLeapYear`
- `列出当前目录` → 调 `listDir`
- `创建文件 hello.txt 内容 你好` → 调 `createFile`
- `读取 hello.txt` → 调 `readFile`
