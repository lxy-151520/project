# -*- coding: utf-8 -*-
"""系统信息查询工具：getDate / isLeapYear / getCWD / getFileType。"""
import os
import subprocess


def getDate() -> str:
    """调用 Windows 本地命令获取当前日期和时间。"""
    d = subprocess.run("cmd /c date /t", capture_output=True, text=True, shell=False).stdout.strip()
    t = subprocess.run("cmd /c time /t", capture_output=True, text=True, shell=False).stdout.strip()
    return f"日期:{d} 时间:{t}"


def isLeapYear(year: int) -> str:
    """判断某年是否闰年。"""
    leap = (year % 4 == 0 and year % 100 != 0) or (year % 400 == 0)
    return f"{year}年{'是' if leap else '不是'}闰年"


def getCWD() -> str:
    """返回当前工作目录。"""
    return os.getcwd()


def getFileType(path: str) -> str:
    """返回文件扩展名;无扩展名返回提示。"""
    _, ext = os.path.splitext(path)
    return f"文件类型: {ext}" if ext else "该文件没有扩展名"
