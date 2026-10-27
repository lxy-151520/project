# -*- coding: utf-8 -*-
"""Run 工具: 纯 subprocess 封装, 接收 command + args 执行本地 CLI.

教学目标: 让学生理解 Agent 调用本地工具的完整链路.
暂时不实现白名单/黑名单, 仅限制超时和输出长度.
命令以运行 xAgent 的当前用户权限执行.
"""
from __future__ import annotations

import subprocess
import os


DEFAULT_TIMEOUT = 15          # 秒
MAX_OUTPUT_CHARS = 4000      # 截断输出


def Run(command: str, args: list[str] | None = None, timeout: int = DEFAULT_TIMEOUT) -> str:
    """执行一条本地命令, 用 subprocess + shell=False, 避免注入.

    Args:
        command:  可执行程序的名称或完整路径, 例如 "python" 或 "git".
        args:     参数列表, 例如 ["-V"], 默认空.
        timeout:  超时秒数, 默认 15s, 上限 120s.

    Returns:
        格式:
            [Run] exit_code=0, 命令: python -V
            Python 3.13.14
        失败/超时会在 exit_code 行标注原因.
    """
    if not command or not command.strip():
        return "[Run 参数错误] command 不能为空"

    args = args or []
    # 构造 subprocess 需要的列表 (command + args)
    cmd_list = [command.strip()] + [str(a) for a in args]

    timeout = max(1, min(int(timeout), 120))

    try:
        result = subprocess.run(
            cmd_list,
            capture_output=True,
            text=True,
            timeout=timeout,
            shell=False,          # 关键: 不用 shell, 防命令注入
            encoding="utf-8",
            errors="replace",
            env={**os.environ},   # 继承 PATH 等环境变量
        )
    except subprocess.TimeoutExpired:
        cmd_preview = " ".join(cmd_list)
        return f"[Run 超时] 命令在 {timeout}s 内未完成: {cmd_preview[:200]}"
    except FileNotFoundError:
        return f"[Run 错误] 未找到可执行文件: {command} (请确认已安装或在 PATH 中)"
    except Exception as e:
        return f"[Run 执行异常] {type(e).__name__}: {e}"

    stdout = result.stdout or ""
    stderr = result.stderr or ""
    exit_code = result.returncode

    # 组合输出
    output_parts = []
    if stdout.strip():
        output_parts.append(stdout.strip())
    if stderr.strip():
        output_parts.append(f"[stderr] {stderr.strip()}")
    output = "\n".join(output_parts) if output_parts else "(命令无输出)"

    # 截断
    if len(output) > MAX_OUTPUT_CHARS:
        output = output[:MAX_OUTPUT_CHARS] + "\n...(输出已截断)"

    # 头部: exit_code + 完整命令预览
    cmd_preview = " ".join(cmd_list)
    header = f"[Run] exit_code={exit_code}, 命令: {cmd_preview}\n"

    return header + output
