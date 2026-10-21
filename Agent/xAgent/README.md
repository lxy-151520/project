# xAgent

基于 Practice02 `chat-stream-tool-fileOps.py` 重构的 **core/UI 分离** 智能体。
核心业务逻辑(LLM 调用、function call 循环、工具集)与界面完全解耦,为将来扩展 Web / Desktop 等多界面版本做好准备。

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
├── ui/                      # UI 层 (只通过 AgentCallbacks 订阅 core 事件)
│   ├── cli.py              # 命令行版本
│   └── tui.py              # Textual TUI 版本
├── main.py                  # 入口:TUI
├── main_cli.py              # 入口:CLI
└── config.ini               # LLM 配置(不随 Git 提交)
```

## 核心设计

| 层 | 职责 | 依赖 |
|---|---|---|
| `core` | LLM 通信、消息历史、工具调度 | 仅标准库 + `requests` |
| `ui`   | 渲染用户交互 | 仅依赖 `core.AgentCallbacks` |

UI 通过实现 `AgentCallbacks` 订阅 5 类事件:
`on_user_message / on_tool_call / on_tool_result / on_token / on_response_done / on_error`。
新增 Web (FastAPI + SSE) 或 Desktop (PySide) 界面时,只需再写一个实现这套回调的类,`core` 代码**零改动**。

## 运行

```powershell
# 安装依赖 (一次性)
pip install textual requests

# 启动 TUI
python -m xAgent.main

# 或启动 CLI
python -m xAgent.main_cli
```

注意 `config.ini` 需要放在运行目录(`xAgent/`)下。

## 测试提问

- `今天日期是多少?` → 调 `getDate`
- `2024 年是闰年吗?` → 调 `isLeapYear`
- `列出当前目录` → 调 `listDir`
- `创建文件 hello.txt 内容 你好` → 调 `createFile`
- `读取 hello.txt` → 调 `readFile`
