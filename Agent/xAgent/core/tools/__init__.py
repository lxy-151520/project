# -*- coding: utf-8 -*-
"""工具汇总:TOOL_MAP (函数名 -> 可调用对象) 和 TOOL_SCHEMAS (OpenAI function calling schema)。"""
from . import system_tools, file_tools

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
    _fn("getDate", "获取当前本地日期和时间(调用 Windows 本地命令)", {}),
    _fn("isLeapYear", "判断某一年是否为闰年", {
        "year": {"type": "integer", "description": "年份,例如 2024"},
    }, ["year"]),
    _fn("getCWD", "获取当前工作目录的绝对路径", {}),
    _fn("getFileType", "根据文件路径返回扩展名", {
        "path": {"type": "string", "description": "文件路径"},
    }, ["path"]),
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
]
