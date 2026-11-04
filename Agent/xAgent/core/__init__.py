# -*- coding: utf-8 -*-
"""xAgent 核心层(与 UI 无关)。"""
from .agent import Agent, AgentCallbacks, DEFAULT_SYSTEM, AGENTS_MD_MARKER
from .config import (
    AppConfig, AgentConfig, ToolsConfig, TuiConfig,
    LLMConfig, load_config, ensure_config, DEFAULT_CONTEXT_WINDOW,
)
from .llm import LLMClient
from .tools import TOOL_MAP, TOOL_SCHEMAS
from . import context, session

__all__ = [
    "Agent", "AgentCallbacks", "DEFAULT_SYSTEM", "AGENTS_MD_MARKER",
    "AppConfig", "AgentConfig", "ToolsConfig", "TuiConfig",
    "LLMConfig", "load_config", "ensure_config", "DEFAULT_CONTEXT_WINDOW",
    "LLMClient",
    "TOOL_MAP", "TOOL_SCHEMAS",
    "context", "session",
]
