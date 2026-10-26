# -*- coding: utf-8 -*-
"""本地 CLI 工具: runCommand —— 安全地执行本地命令行。

使用 subprocess + 参数列表方式, 禁止 shell=True, 防止命令注入。
限制命令执行时间, 对输出做长度截断。
"""
from __future__ import annotations

import subprocess
import shlex
import os


# 命令白名单前缀 (可选: 只允许这些命令)
# 设为空列表则不做白名单限制, 但仍有危险命令黑名单
WHITELIST_COMMANDS: list[str] = [
    # 开发常用
    "python", "python3", "pip", "pip3",
    "node", "npm", "npx",
    "git",
    "ls", "dir",          # 跨平台目录查看
    "cat", "type",        # 跨平台文件查看
    "echo",
    "pwd", "cd",
]

# 危险命令黑名单 (前缀匹配, 命中则直接拒绝)
DANGEROUS_PATTERNS: list[str] = [
    "rm -rf /",
    "del /f /s",
    "format ",
    "rd /s",
    "mkfs",
    "> /dev/sda",
    "chmod -R 777 /",
    "shutdown",
    "poweroff",
    "reboot",
    "curl .*\\| sh",
    "wget .*\\| sh",
]

DEFAULT_TIMEOUT = 10          # 秒
MAX_OUTPUT_CHARS = 4000      # 截断输出


def _is_dangerous(command_line: str) -> bool:
    """简单黑名单检查。"""
    lower = command_line.lower().strip()
    for pat in DANGEROUS_PATTERNS:
        if pat in lower:
            return True
    return False


def _split_args(command_line: str) -> list[str]:
    """把用户输入的命令行字符串拆成参数列表。"""
    try:
        # shlex 在 Windows 上对引号处理更准确
        return shlex.split(command_line, posix=False)
    except ValueError:
        # fallback: 简单按空格切
        return command_line.split()


def runCommand(command: str, timeout: int = DEFAULT_TIMEOUT) -> str:
    """执行一条本地命令, 返回 stdout + stderr。

    Args:
        command: 要执行的命令行 (字符串), 例如 "python -V"。
        timeout: 超时秒数, 默认 10s, 上限 60s。

    Returns:
        命令输出 (stdout + stderr), 超长截断; 失败时返回错误描述。
    """
    if not command or not command.strip():
        return "[runCommand 参数错误] command 不能为空"

    command = command.strip()

    # 安全检查 1: 危险命令
    if _is_dangerous(command):
        return f"[runCommand 被拒绝] 命令疑似危险操作: {command[:100]}"

    # 安全检查 2: 白名单 (只检查第一个 token)
    args = _split_args(command)
    if not args:
        return "[runCommand 错误] 无法解析命令"

    first_token = args[0].lower()
    # 如果白名单非空, 必须命中
    if WHITELIST_COMMANDS and first_token not in WHITELIST_COMMANDS:
        return (
            f"[runCommand 被拒绝] 命令 \"{first_token}\" 不在允许列表中。\n"
            f"允许的命令: {', '.join(WHITELIST_COMMANDS)}"
        )

    # 限制超时上限
    timeout = max(1, min(int(timeout), 60))

    try:
        result = subprocess.run(
            args,
            capture_output=True,
            text=True,
            timeout=timeout,
            shell=False,          # 关键: 不用 shell, 防注入
            encoding="utf-8",
            errors="replace",
            env={**os.environ},    # 继承 PATH 等环境变量
        )
    except subprocess.TimeoutExpired:
        return f"[runCommand 超时] 命令在 {timeout}s 内未完成: {command}"
    except FileNotFoundError:
        return f"[runCommand 错误] 未找到可执行文件: {first_token} (请确认已安装或在 PATH 中)"
    except Exception as e:
        return f"[runCommand 执行异常] {type(e).__name__}: {e}"

    # 组合输出
    stdout = result.stdout or ""
    stderr = result.stderr or ""
    parts = []
    if stdout.strip():
        parts.append(stdout.strip())
    if stderr.strip():
        parts.append(f"[stderr] {stderr.strip()}")
    output = "\n".join(parts) if parts else "(命令无输出)"

    # 截断
    if len(output) > MAX_OUTPUT_CHARS:
        output = output[:MAX_OUTPUT_CHARS] + "\n...(输出已截断)"

    # 退出码
    prefix = f"[runCommand] exit_code={result.returncode}, 命令: {command}\n"
    return prefix + output
