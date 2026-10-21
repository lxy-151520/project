# -*- coding: utf-8 -*-
"""文件/目录操作工具:listDir / readFile / createFile / editFile / createDir / deleteDir / deleteFile / rename。"""
import os
import shutil


def listDir(path: str = ".") -> str:
    """列出目录下的文件与子目录,带大小。"""
    if not os.path.exists(path):
        return f"路径不存在: {path}"
    if not os.path.isdir(path):
        return f"不是目录: {path}"
    lines = [f"目录 {os.path.abspath(path)} 内容:"]
    for name in sorted(os.listdir(path)):
        full = os.path.join(path, name)
        if os.path.isdir(full):
            lines.append(f"  [文件夹] {name}")
        else:
            size = os.path.getsize(full)
            lines.append(f"  [文件]   {name} ({size} B)")
    return "\n".join(lines) if len(lines) > 1 else "(空目录)"


def readFile(path: str) -> str:
    """读取文本文件内容。"""
    if not os.path.exists(path):
        return f"文件不存在: {path}"
    try:
        with open(path, "r", encoding="utf-8") as f:
            return f.read()
    except Exception as e:
        return f"读取失败: {e}"


def createFile(path: str, content: str = "") -> str:
    """创建新文件并写入内容;父目录自动创建。"""
    try:
        parent = os.path.dirname(path)
        if parent:
            os.makedirs(parent, exist_ok=True)
        with open(path, "w", encoding="utf-8") as f:
            f.write(content)
        return f"已创建文件: {path} ({len(content)} 字符)"
    except Exception as e:
        return f"创建失败: {e}"


def editFile(path: str, content: str, mode: str = "overwrite") -> str:
    """编辑文件。mode: overwrite(覆盖) 或 append(追加)。"""
    if not os.path.exists(path):
        return f"文件不存在: {path}"
    if mode not in ("overwrite", "append"):
        return f"不支持的模式: {mode},应为 overwrite / append"
    try:
        with open(path, "w" if mode == "overwrite" else "a", encoding="utf-8") as f:
            f.write(content)
        return f"已{'覆盖' if mode == 'overwrite' else '追加'}写入: {path}"
    except Exception as e:
        return f"写入失败: {e}"


def createDir(path: str) -> str:
    """创建目录(支持多级)。"""
    try:
        os.makedirs(path, exist_ok=True)
        return f"目录已创建: {path}"
    except Exception as e:
        return f"创建目录失败: {e}"


def deleteDir(path: str) -> str:
    """删除目录(含其所有内容)。"""
    if not os.path.exists(path):
        return f"目录不存在: {path}"
    if not os.path.isdir(path):
        return f"不是目录: {path}"
    try:
        shutil.rmtree(path)
        return f"目录已删除: {path}"
    except Exception as e:
        return f"删除目录失败: {e}"


def deleteFile(path: str) -> str:
    """删除文件。"""
    if not os.path.exists(path):
        return f"文件不存在: {path}"
    if not os.path.isfile(path):
        return f"不是文件: {path}"
    try:
        os.remove(path)
        return f"文件已删除: {path}"
    except Exception as e:
        return f"删除文件失败: {e}"


def rename(src: str, dst: str) -> str:
    """重命名/移动 文件或目录。"""
    if not os.path.exists(src):
        return f"路径不存在: {src}"
    try:
        os.rename(src, dst)
        return f"已重命名: {src} -> {dst}"
    except Exception as e:
        return f"重命名失败: {e}"
