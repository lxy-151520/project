# -*- coding: utf-8 -*-
"""配置加载模块：从 config.ini 读取 LLM 配置。"""
import configparser
from dataclasses import dataclass
from pathlib import Path


@dataclass
class LLMConfig:
    api_key: str
    base_url: str
    model: str


def load_config(ini_path: str | Path = "config.ini") -> LLMConfig:
    """从 config.ini 读取 [llm] 段。文件必须包含 api_key / base_url / model。"""
    ini_path = Path(ini_path)
    if not ini_path.exists():
        raise FileNotFoundError(f"配置文件不存在: {ini_path.resolve()}")
    cp = configparser.ConfigParser()
    cp.read(ini_path, encoding="utf-8")
    if "llm" not in cp:
        raise KeyError("config.ini 缺少 [llm] 段")
    sec = cp["llm"]
    return LLMConfig(
        api_key=sec["api_key"].strip(),
        base_url=sec["base_url"].strip(),
        model=sec["model"].strip(),
    )
