# -*- coding: utf-8 -*-
"""Skill 动态加载:发现 .agents/skills 下的 Skill,解析 SKILL.md,按需读取完整内容。

遵循 Agent Skills 规范:
- Skill 目录位于 <project_root>/.agents/skills/<skill_name>/
- 每个 Skill 子目录必须包含 SKILL.md,头部用 YAML frontmatter 声明 name / description
- 初始化仅加载 name + description,完整正文由 LLM 调用 loadSkill 工具时按需读取
"""
from __future__ import annotations

import os
import re
from dataclasses import dataclass
from pathlib import Path
from typing import Optional


@dataclass
class SkillInfo:
    """Skill 元信息(初始化时只加载这两个字段,不读正文)。"""
    name: str
    description: str
    dir_path: Path          # Skill 子目录的绝对路径
    skill_md_path: Path     # SKILL.md 的绝对路径


# ---------- YAML Frontmatter 简易解析 ----------
# 不依赖 PyYAML,只解析最简单的 key: value 行,够用
_FRONTMATTER_RE = re.compile(r"^---\s*$", re.MULTILINE)
_KV_RE = re.compile(r"^\s*([A-Za-z_][A-Za-z0-9_\-]*)\s*:\s*(.*?)\s*$")


def _parse_frontmatter(text: str) -> Optional[dict]:
    """从 markdown 文本顶部提取 YAML frontmatter 的 key-value 字典。

    frontmatter 格式:
        ---
        name: my-skill
        description: 这个技能能做什么
        ---
    """
    matches = list(_FRONTMATTER_RE.finditer(text))
    if len(matches) < 2:
        return None
    between = text[matches[0].end():matches[1].start()]
    result = {}
    for line in between.splitlines():
        m = _KV_RE.match(line)
        if m:
            key, val = m.group(1), m.group(2).strip().strip('"\'')
            result[key.lower()] = val
    return result if result else None


# ---------- Skill 发现 ----------
def discover_skills(project_root: str | os.PathLike) -> list[SkillInfo]:
    """扫描 <project_root>/.agents/skills/ 下所有 Skill 子目录。

    只读取 SKILL.md 的 frontmatter, 不加载正文。
    """
    skills_dir = Path(project_root) / ".agents" / "skills"
    if not skills_dir.is_dir():
        return []

    discovered: list[SkillInfo] = []
    for child in sorted(skills_dir.iterdir()):
        if not child.is_dir():
            continue
        skill_md = child / "SKILL.md"
        if not skill_md.is_file():
            continue
        try:
            text = skill_md.read_text(encoding="utf-8")
        except Exception:
            continue
        fm = _parse_frontmatter(text)
        if not fm:
            continue
        name = fm.get("name")
        description = fm.get("description")
        if not name or not description:
            continue
        discovered.append(SkillInfo(
            name=name,
            description=description,
            dir_path=child.resolve(),
            skill_md_path=skill_md.resolve(),
        ))
    return discovered


def build_skills_prompt(skills: list[SkillInfo]) -> str:
    """把发现的 Skill 整理成注入 System Prompt 的那段说明文字。"""
    if not skills:
        return ""
    lines = ["You have access to the following skills:"]
    for s in skills:
        lines.append(f"- `{s.name}`: {s.description}")
    lines.append(
        "Use the `loadSkill` tool to load the full instructions of a skill "
        "when needed. You can also load additional files referenced by a skill."
    )
    return "\n".join(lines)


# ---------- Skill 文件安全读取 ----------
def _resolve_skill_dir(project_root: str | os.PathLike, skill_name: str) -> Optional[Path]:
    """根据 skill_name 找 Skill 子目录(精确匹配 name frontmatter 或目录名)。"""
    skills_dir = Path(project_root) / ".agents" / "skills"
    if not skills_dir.is_dir():
        return None
    # 1. 按目录名精确匹配
    candidate = skills_dir / skill_name
    if candidate.is_dir():
        return candidate.resolve()
    # 2. 遍历所有 SKILL.md 找 frontmatter 的 name 匹配
    for child in skills_dir.iterdir():
        if not child.is_dir():
            continue
        skill_md = child / "SKILL.md"
        if not skill_md.is_file():
            continue
        try:
            text = skill_md.read_text(encoding="utf-8")
        except Exception:
            continue
        fm = _parse_frontmatter(text)
        if fm and fm.get("name") == skill_name:
            return child.resolve()
    return None


def _is_path_within(child: Path, parent: Path) -> bool:
    """防止路径穿越: child 必须在 parent 目录内部。"""
    try:
        child.relative_to(parent)
        return True
    except ValueError:
        return False


def load_skill_file(
    project_root: str | os.PathLike,
    skill_name: str,
    filename: Optional[str] = None,
) -> str:
    """读取 Skill 的 SKILL.md 全文或其附属文件。

    路径解析优先级:
    1. 精确路径(相对于 Skill 目录、项目相对路径、绝对路径)
    2. 仅提供文件名时,在 Skill 目录内递归搜索,唯一匹配则读取,多个匹配返回候选列表

    文件读取严格限制在 Skill 目录内,避免路径穿越。
    """
    skill_dir = _resolve_skill_dir(project_root, skill_name)
    if skill_dir is None:
        return f"[错误] 未找到 Skill: {skill_name}"

    skill_dir_resolved = skill_dir.resolve()

    # ----- 没给 filename -> 直接读 SKILL.md -----
    if not filename:
        target = skill_dir_resolved / "SKILL.md"
        if not target.is_file():
            return f"[错误] Skill 目录下没有 SKILL.md: {skill_dir}"
        return target.read_text(encoding="utf-8", errors="replace")

    # ----- 给了 filename -----
    candidates: list[Path] = []

    # 1. 绝对路径
    p_abs = Path(filename)
    if p_abs.is_absolute() and p_abs.is_file():
        resolved = p_abs.resolve()
        if _is_path_within(resolved, skill_dir_resolved):
            candidates.append(resolved)

    # 2. 相对于项目根
    p_proj = Path(project_root) / filename
    if p_proj.is_file():
        resolved = p_proj.resolve()
        if _is_path_within(resolved, skill_dir_resolved) and resolved not in candidates:
            candidates.append(resolved)

    # 3. 相对于 Skill 目录
    p_skill = skill_dir_resolved / filename
    if p_skill.is_file():
        resolved = p_skill.resolve()
        if _is_path_within(resolved, skill_dir_resolved) and resolved not in candidates:
            candidates.append(resolved)

    # 4. 文件名递归搜索
    name_only = Path(filename).name
    if name_only != filename:
        for hit in skill_dir_resolved.rglob(name_only):
            if hit.is_file():
                resolved = hit.resolve()
                if _is_path_within(resolved, skill_dir_resolved) and resolved not in candidates:
                    candidates.append(resolved)

    if not candidates:
        return f"[错误] Skill '{skill_name}' 下找不到文件: {filename}"
    if len(candidates) > 1:
        # 返回候选列表让 LLM 决定
        lines = [f"[歧义] 在 Skill '{skill_name}' 下找到多个同名文件,请用精确路径重试:"]
        for c in candidates:
            lines.append(f"  - {c.relative_to(skill_dir_resolved)}")
        return "\n".join(lines)

    return candidates[0].read_text(encoding="utf-8", errors="replace")