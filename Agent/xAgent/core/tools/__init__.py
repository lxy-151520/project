# -*- coding: utf-8 -*-
"""工具汇总:TOOL_MAP (函数名 -> 可调用对象) 和 TOOL_SCHEMAS (OpenAI function calling schema)。"""
from . import system_tools, file_tools, web_tools, cli_tools, run_tool

# ---------- 函数名 -> 实际函数 ----------
TOOL_MAP = {
    # 系统信息
    "getDate":     system_tools.getDate,
    "isLeapYear":  system_tools.isLeapYear,
    "getCWD":      system_tools.getCWD,
    "getFileType": system_tools.getFileType,
    # 文件/目录操作
    "listDir":     file_tools.listDir,
    "readFile":    file_tools.readFile,
    "createFile":  file_tools.createFile,
    "editFile":    file_tools.editFile,
    "createDir":   file_tools.createDir,
    "deleteDir":   file_tools.deleteDir,
    "deleteFile":  file_tools.deleteFile,
    "rename":      file_tools.rename,
    # 网络工具
    "searchWeb":   web_tools.searchWeb,
    "fetchWeb":    web_tools.fetchWeb,
    # 本地 CLI
    "runCommand":  cli_tools.runCommand,
    # Run 工具 (教学版: subprocess + shell=False, 带白名单/黑名单)
    "Run":         run_tool.Run,
}


def _fn(name: str, desc: str, properties: dict, required: list[str] | None = None) -> dict:
    return {
        "type": "function",
        "function": {
            "name": name,
            "description": desc,
            "parameters": {
                "type": "object",
                "properties": properties,
                "required": required or [],
            },
        },
    }


# ---------- OpenAI tools schema ----------
TOOL_SCHEMAS = [
    # ---- 系统信息 ----
    _fn("getDate", "获取当前本地日期和时间(调用 Windows 本地命令)", {}),
    _fn("isLeapYear", "判断某一年是否为闰年", {
        "year": {"type": "integer", "description": "年份,例如 2024"},
    }, ["year"]),
    _fn("getCWD", "获取当前工作目录的绝对路径", {}),
    _fn("getFileType", "根据文件路径返回扩展名", {
        "path": {"type": "string", "description": "文件路径"},
    }, ["path"]),

    # ---- 文件/目录操作 ----
    _fn("listDir", "列出目录下的文件与子目录及大小", {
        "path": {"type": "string", "description": "目录路径,默认当前目录"},
    }),
    _fn("readFile", "读取文本文件的全部内容", {
        "path": {"type": "string", "description": "文件路径"},
    }, ["path"]),
    _fn("createFile", "创建一个新文件并写入内容(父目录不存在会自动创建)", {
        "path":    {"type": "string", "description": "文件路径"},
        "content": {"type": "string", "description": "文件内容,默认空"},
    }, ["path"]),
    _fn("editFile", "编辑已存在的文件,支持覆盖或追加", {
        "path":    {"type": "string", "description": "文件路径"},
        "content": {"type": "string", "description": "要写入的内容"},
        "mode":    {"type": "string", "enum": ["overwrite", "append"], "description": "覆盖或追加,默认 overwrite"},
    }, ["path", "content"]),
    _fn("createDir", "创建目录(支持多级)", {
        "path": {"type": "string", "description": "目录路径"},
    }, ["path"]),
    _fn("deleteDir", "删除目录及其所有内容(谨慎使用)", {
        "path": {"type": "string", "description": "目录路径"},
    }, ["path"]),
    _fn("deleteFile", "删除指定文件", {
        "path": {"type": "string", "description": "文件路径"},
    }, ["path"]),
    _fn("rename", "重命名/移动 文件或目录", {
        "src": {"type": "string", "description": "原路径"},
        "dst": {"type": "string", "description": "新路径"},
    }, ["src", "dst"]),

    # ---- 网络工具 ----
    _fn("searchWeb", "调用百度千帆 AI 搜索,搜索互联网上的实时信息,返回标题/摘要/URL。需要 config.ini 的 [search] 段配置 baidu_qianfan_api_key。", {
        "query": {"type": "string", "description": "搜索关键词或问题,例如 '2026年国庆放几天假'"},
        "top_k": {"type": "integer", "description": "返回结果条数,默认 8,上限 10"},
    }, ["query"]),
    _fn("fetchWeb", "抓取指定 URL 的网页,用 trafilatura 提取正文并转为 Markdown。适合阅读文章、查看文档内容。", {
        "url": {"type": "string", "description": "完整的网页 URL,例如 'https://example.com/article'"},
        "max_chars": {"type": "integer", "description": "返回正文最大字符数,默认 4000"},
    }, ["url"]),

    # ---- 本地 CLI ----
    _fn("runCommand", "执行一条本地命令行(如 python -V、git status、pip list 等)。有安全白名单,危险命令会被拒绝。", {
        "command": {"type": "string", "description": "要执行的命令行,例如 'python -V' 或 'git status'"},
        "timeout": {"type": "integer", "description": "超时秒数,默认 10,上限 60"},
    }, ["command"]),

    # ---- Run (教学版) ----
    _fn("Run", "执行一条本地 CLI 程序,返回 stdout/stderr/exit_code。用 subprocess + shell=False,参数列表方式避免注入。", {
        "command": {"type": "string", "description": "可执行程序名或路径,例如 'python'、'git'、'pip'"},
        "args":    {"type": "array", "items": {"type": "string"}, "description": "参数列表,例如 ['-V']、['status']、['list']"},
        "timeout": {"type": "integer", "description": "超时秒数,默认 15,上限 120"},
    }, ["command"]),
]
