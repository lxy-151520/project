# -*- coding: utf-8 -*-
"""xAgent 入口:默认启动 Textual TUI。

同时兼容三种运行方式:
  1. python xAgent/main.py     (从父目录 Agent/ 运行)
  2. python main.py            (直接 cd 到 xAgent/ 运行)
  3. PyInstaller 打包后的 exe
"""
from __future__ import annotations

import sys
from pathlib import Path


def _ensure_xagent_on_path():
    """确保 sys.path 里有 xAgent 包的父目录。"""
    # 情况 1: PyInstaller 打包,__file__ 可能不存在或指向临时解压目录
    if getattr(sys, "frozen", False):
        # frozen 下 xAgent 作为 pkg 被打进 exe,无需手动加 path
        return
    here = Path(__file__).resolve().parent
    parent = here.parent
    # 如果父目录下有 xAgent/ 目录,把父目录加进 sys.path
    if (parent / "xAgent").is_dir():
        if str(parent) not in sys.path:
            sys.path.insert(0, str(parent))
    # 兜底:把当前目录也加进去 (兼容 `python main.py` 从 xAgent/ 内部跑)
    if str(here) not in sys.path:
        sys.path.insert(0, str(here))


_ensure_xagent_on_path()

# 现在 xAgent 包应该可以被 import 了
try:
    from xAgent.tui import main
except ImportError:
    # 终极兜底:直接引用 (当 xAgent 目录本身就是 sys.path 根时)
    from tui import main  # type: ignore


if __name__ == "__main__":
    main()
