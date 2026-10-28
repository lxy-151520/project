# -*- coding: utf-8 -*-
"""集成验证:Skill 发现 + loadSkill + TOOL_MAP/TOOL_SCHEMAS 注册。"""
import sys
sys.path.insert(0, ".")

from core.skills import discover_skills, build_skills_prompt, load_skill_file

ROOT = r"C:\Users\lxy15\Desktop\项目\progess\Agent\xAgent"

# 1. 发现 Skill
print("=== 1. 发现 Skill ===")
skills = discover_skills(ROOT)
for s in skills:
    print(f"  name={s.name!r}  desc={s.description!r}  dir={s.dir_path}")
print(f"共发现 {len(skills)} 个 Skill\n")

# 2. Skill Prompt 片段
print("=== 2. Skill Prompt 注入片段 ===")
print(build_skills_prompt(skills))
print()

# 3. 读 SKILL.md
print("=== 3. loadSkill('code-review') 正文前 300 字 ===")
content = load_skill_file(ROOT, "code-review")
print(content[:300])
print("...(截断)\n")

# 4. 错误 name
print("=== 4. loadSkill('not-exist') ===")
print(load_skill_file(ROOT, "not-exist"))
print()

# 5. TOOL_MAP / TOOL_SCHEMAS
print("=== 5. TOOL_MAP / TOOL_SCHEMAS 含 loadSkill ===")
from core.tools import TOOL_MAP, TOOL_SCHEMAS
assert "loadSkill" in TOOL_MAP, "loadSkill 不在 TOOL_MAP"
schema_names = [s["function"]["name"] for s in TOOL_SCHEMAS]
assert "loadSkill" in schema_names, "loadSkill 不在 TOOL_SCHEMAS"
print(f"TOOL_MAP 含 loadSkill: True")
print(f"TOOL_SCHEMAS 含 loadSkill: True")
print(f"TOOL_MAP 总数: {len(TOOL_MAP)}, TOOL_SCHEMAS 总数: {len(TOOL_SCHEMAS)}\n")

# 6. Agent 初始化 + System Prompt 检查
print("=== 6. Agent 初始化 System Prompt ===")
from core.agent import Agent
from core.llm import LLMClient

# 用一个假的 LLMClient, 只关心 system prompt
class _FakeLLM:
    def chat(self, messages, tools=None):
        return None
    def chat_stream(self, messages):
        return []

agent = Agent(llm=_FakeLLM())
system_msg = agent.messages[0]["content"]
# 检查 skill prompt 是否注入
assert "code-review" in system_msg, "code-review 未注入 system prompt"
assert "commit-helper" in system_msg, "commit-helper 未注入 system prompt"
assert "loadSkill" in system_msg, "loadSkill 未注入 system prompt"
print("system prompt 片段(含 skill 的部分):")
# 打印后半段
tail = system_msg[-500:]
print(tail)
print("\n全部通过!")