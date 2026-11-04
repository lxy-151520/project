# -*- coding: utf-8 -*-
"""配置加载模块：从 config.ini 读取 LLM 配置。"""
import configparser
from dataclasses import dataclass
from pathlib import Path

# 无法从配置获取上下文窗口时使用的默认值(128k)
DEFAULT_CONTEXT_WINDOW = 128_000


@dataclass
class LLMConfig:
    api_key: str
    base_url: str
    model: str
    # 模型上下文窗口;未配置时用 128k,并标记为「默认」
    context_window: int = DEFAULT_CONTEXT_WINDOW
    context_window_is_default: bool = True


def load_config(ini_path: str | Path = "config.ini") -> LLMConfig:
    """从 config.ini 读取 [llm] 段。文件必须包含 api_key / base_url / model。

    可选 context_window(整数,单位 token):某模型窗口不是 128k 时填这里,
    例如 glm-4-air 可填 128000,更小的模型填实际值。
    """
    ini_path = Path(ini_path)
    if not ini_path.exists():
        raise FileNotFoundError(f"配置文件不存在: {ini_path.resolve()}")
    cp = configparser.ConfigParser()
    cp.read(ini_path, encoding="utf-8")
    if "llm" not in cp:
        raise KeyError("config.ini 缺少 [llm] 段")

    sec = cp["llm"]
    window = DEFAULT_CONTEXT_WINDOW
    is_default = True
    raw = (sec.get("context_window") or "").strip()
    if raw:
        try:
            parsed = int(raw)
            if parsed > 0:
                window = parsed
                is_default = False
        except ValueError:
            pass

    return LLMConfig(
        api_key=sec["api_key"].strip(),
        base_url=sec["base_url"].strip(),
        model=sec["model"].strip(),
        context_window=window,
        context_window_is_default=is_default,
    )
