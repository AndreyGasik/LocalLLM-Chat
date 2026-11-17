# core/write_tool_definitions.py — тонкая обёртка.
# Реализация в LLM-Chat-Common/core/write_tool_definitions.py — единый источник правок.
from core.common_loader import load_common_module

globals().update({
    k: v for k, v in vars(load_common_module("core/write_tool_definitions")).items()
    if not (k.startswith("__") and k.endswith("__"))
})
