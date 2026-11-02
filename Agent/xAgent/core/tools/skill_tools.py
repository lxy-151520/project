# -*- coding: utf-8 -*-
"""Skill 工具:loadSkill 按需读取 .agents/skills 下的 Skill 内容,createSkill 按规范新建 Skill。"""
from __future__ import annotations

import re
from pathlib import Path

# 由 Agent 初始化时注入项目根目录,供 loadSkill / createSkill 共用
_PROJECT_ROOT: Path = Path.cwd()

# Skill 名称只允许小写字母、数字与连字符,不能以连字符开头/结尾,不能连续出现
_NAME_RE = re.compile(r"^[a-z0-9]+(?:-[a-z0-9]+)*$")
_MAX_NAME_LEN = 64


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
    from ..skills import load_skill_file
    return load_skill_file(_PROJECT_ROOT, name, filename)


# ---------- createSkill ----------
def _split_frontmatter(text: str) -> tuple[dict[str, str], str] | None:
    """拆分 YAML frontmatter 与正文;格式不合法时返回 None。"""
    lines = text.split("\n")
    i = 0
    while i < len(lines) and not lines[i].strip():
        i += 1
    if i >= len(lines) or lines[i].strip() != "---":
        return None
    j = i + 1
    while j < len(lines) and lines[j].strip() != "---":
        j += 1
    if j >= len(lines):
        return None

    meta: dict[str, str] = {}
    for line in lines[i + 1:j]:
        if not line.strip() or line.lstrip().startswith("#"):
            continue
        if line[:1] in (" ", "\t"):        # 缩进续行,不单独解析
            continue
        key, sep, value = line.partition(":")
        if not sep:
            continue
        meta[key.strip()] = value.strip().strip("'\"")
    return meta, "\n".join(lines[j + 1:]).strip()


def _validate_skill(name: str, content: str) -> str | None:
    """校验 createSkill 的参数,返回错误说明;通过则返回 None。"""
    if not name:
        return "创建失败:name 不能为空。name 应使用小写字母、数字和连字符,例如 'code-review'。"
    if len(name) > _MAX_NAME_LEN:
        return f"创建失败:name 过长({len(name)} 字符),上限 {_MAX_NAME_LEN}。"
    if not _NAME_RE.match(name):
        return (
            f"创建失败:name '{name}' 不符合规范。"
            "只允许小写字母、数字和连字符(-)组成的英文名称,例如 'code-review'、'pdf-parse'。"
            "请修正 name 后重试。"
        )
    if not content.strip():
        return "创建失败:skillContext 为空。请提供 SKILL.md 的完整内容。"

    parsed = _split_frontmatter(content)
    if parsed is None:
        return (
            "创建失败:skillContext 必须以 YAML frontmatter 开头,且用 --- 前后包裹,"
            "例如:\n---\nname: " + name + "\ndescription: 一句话说明该 Skill 的用途与触发时机\n---\n\n正文...\n"
            "请修正后重试。"
        )

    meta, body = parsed
    fm_name = meta.get("name", "")
    if not fm_name:
        return "创建失败:frontmatter 缺少 name 字段。请补上 name: " + name + " 后重试。"
    if fm_name != name:
        return (
            f"创建失败:frontmatter 中的 name('{fm_name}')与参数 name('{name}')不一致。"
            "两者必须完全相同,请修正后重试。"
        )
    if not meta.get("description"):
        return "创建失败:frontmatter 缺少 description 字段(说明该 Skill 的用途与触发时机)。请补充后重试。"
    if not body:
        return "创建失败:frontmatter 之后缺少正文内容。请在正文写清该 Skill 的用法步骤。"
    return None


def createSkill(name: str, skillContext: str) -> str:
    """创建新 Skill:写入 .agents/skills/<name>/SKILL.md;目标已存在时不覆盖。"""
    name = (name or "").strip()
    content = (skillContext or "").replace("\r\n", "\n").replace("\r", "\n")

    err = _validate_skill(name, content)
    if err:
        return err

    target_dir = _PROJECT_ROOT / ".agents" / "skills" / name
    skill_md = target_dir / "SKILL.md"

    if target_dir.exists():
        return (
            f"Skill 已存在:{skill_md}(未做任何修改,避免覆盖原有内容)。"
            "如需更新,请先 loadSkill / readFile 读取原文再 editFile 写入,或换一个不同的 name。"
        )

    try:
        target_dir.mkdir(parents=True, exist_ok=False)
        skill_md.write_text(content if content.endswith("\n") else content + "\n", encoding="utf-8")
    except FileExistsError:
        return f"Skill 已存在:{skill_md}(未做任何修改)。"
    except Exception as e:
        return f"创建 Skill 失败: {e}"

    return (
        f"已创建 Skill:{skill_md}\n"
        f"所在目录:{target_dir}\n"
        "如需补充 references/、scripts/ 等子目录或辅助文件,请继续使用 createDir / createFile 工具完成。"
    )
