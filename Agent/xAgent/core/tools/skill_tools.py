# -*- coding: utf-8 -*-
"""Skill 加载工具:loadSkill,按需读取 .agents/skills 下的 Skill 文件。"""
from __future__ import annotations

from pathlib import Path

# 由 Agent 初始化时注入项目根目录,供 loadSkill 使用
_PROJECT_ROOT: Path = Path.cwd()


def set_project_root(root: str | Path) -> None:
    global _PROJECT_ROOT
    _PROJECT_ROOT = Path(root).resolve()


def loadSkill(name: str, filename: str | None = None) -> str:
    """加载指定 Skill 的完整 SKILL.md,或 Skill 目录下的某个附属文件。

    参数:
        name: Skill 名称(必须,对应 SKILL.md frontmatter 的 name 字段或 Skill 目录名)
        filename: 可选,要读取的文件路径(相对于 Skill 目录、项目根、或绝对路径)
                  不传则默认读取 SKILL.md 全文

    路径解析优先级:绝对路径 -> 项目相对路径 -> Skill 目录相对路径 -> 文件名模糊匹配
    所有读取严格限制在 Skill 目录内部,防止路径穿越。
    """
    # 延迟 import,避免循环依赖
    from core.skills import load_skill_file
    return load_skill_file(_PROJECT_ROOT, name, filename)