# Practice02 - LLM Function Call 对话工具

基于智谱 GLM-4-Flash 实现的命令行 AI 对话程序，通过 **function call（函数调用）** 让大模型能够调用本地工具，完成文件系统操作、日期查询、闰年判断等任务。

## 📂 项目结构

```
Practice02/
├── chat-stream-tool-getDate.py      # 任务(一)：getDate 工具
├── chat-stream-tool-isLeapYear.py   # 任务(二)：getDate + isLeapYear
├── chat-stream-tool-fileOps.py      # 任务(三)：新增 10 个文件操作工具
├── architecture.mmd                 # 任务(四)：Mermaid 代码架构图
├── README.md                        # 项目说明（本文件）
└── config.ini                       # LLM 配置（已被 .gitignore 排除）
```

## ✨ 功能列表

### 任务(一) chat-stream-tool-getDate.py
| 工具 | 功能 |
|---|---|
| `getDate` | 调用 Windows `date /t` + `time /t` 命令获取日期时间 |

### 任务(二) chat-stream-tool-isLeapYear.py
在任务(一)基础上新增：
| 工具 | 功能 |
|---|---|
| `isLeapYear` | Python 算法判断某年是否为闰年（能被4整除但不能被100整除，或能被400整除） |

### 任务(三) chat-stream-tool-fileOps.py
在任务(二)基础上新增 10 个文件操作工具：

| 工具 | 功能 | 实现方式 |
|---|---|---|
| `getCWD` | 获取当前工作目录 | `os.getcwd()` |
| `listDir` | 列出目录下所有文件和子目录 | `os.listdir()` |
| `getFileType` | 获取文件扩展名 | `os.path.splitext()` |
| `readFile` | 读取纯文本文件内容 | `open()` |
| `createFile` | 创建新文件（可含初始内容） | `open(mode='w')` |
| `editFile` | 编辑文件（覆盖或追加） | `open(mode='w'/'a')` |
| `createDir` | 创建目录（自动创建中间层级） | `os.makedirs()` |
| `deleteDir` | 删除目录（含非空） | `shutil.rmtree()` |
| `deleteFile` | 删除文件 | `os.remove()` |
| `rename` | 重命名/移动文件或目录 | `os.rename()` |

## 🚀 运行方法

### 前置条件
- Python 3.8+
- 已安装 `requests` 库：`pip install requests`
- 已配置 `config.ini`（含智谱 API Key）

### 启动任意一个版本

```powershell
cd "C:\Users\lxy15\Desktop\项目\progess\Agent\Practice02"

# 任务(一)
python chat-stream-tool-getDate.py

# 任务(二)
python chat-stream-tool-isLeapYear.py

# 任务(三)
python chat-stream-tool-fileOps.py
```

### 对话示例

```
你: 今天日期是多少？
[调用工具] getDate({})
[工具返回] 当前日期: 周二 2026/10/20, 当前时间: 11:48
AI: 今天是2026年10月20日，星期二。

你: 列出当前目录下的文件
[调用工具] listDir({})
[工具返回] 目录 ... 下有 5 项: ...
AI: 当前目录包含以下文件：...

你: 创建一个文件 hello.txt，内容是 你好世界
[调用工具] createFile({'filename': 'hello.txt', 'content': '你好世界'})
[工具返回] 文件创建成功: ...hello.txt (12 字节)
AI: 已为您创建 hello.txt 文件。

你: 2024年是闰年吗
[调用工具] isLeapYear({'year': 2024})
[工具返回] 2024 年是闰年
AI: 是的，2024年是闰年。
```

退出：按 `Ctrl+C`

## 🏗️ 架构说明

详见 [architecture.mmd](./architecture.mmd)（Mermaid 格式，可粘贴到 https://mermaid.live/ 查看图形化架构）。

核心流程：
1. 维护 `messages` 历史列表（system + user + assistant + tool）
2. 首次请求**非流式**，检查 `finish_reason` 是否为 `tool_calls`
3. 若是 → 通过 `tool_map` 分发到对应 Python 函数执行 → 把结果作为 `role:tool` 消息追加 → 再次请求 LLM
4. 直到 `finish_reason == "stop"` → **流式输出**最终回复（打字机效果）
5. 追加 assistant 消息，回到主循环等待下一轮输入

## 🔧 技术栈

- **LLM**：智谱 AI GLM-4-Flash（OpenAI 兼容 API）
- **协议**：HTTP + SSE（流式输出）
- **核心库**：`requests`、`configparser`、`os`、`shutil`、`json`
- **特性**：function call、多轮 tool_calls 循环、流式输出、对话历史记忆

## ⚠️ 注意事项

- `config.ini` 包含 API Key，已通过 `.gitignore` 排除，请勿上传
- `readFile` 仅支持纯文本格式，二进制文件（如图片、视频）会拒绝读取
- `deleteDir` 会**彻底删除非空目录**，请谨慎使用
- 文件读写默认使用 UTF-8 编码
