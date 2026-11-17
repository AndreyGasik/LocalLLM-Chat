# core/generation_loop.py — тонкая обёртка.
# Реализация в LLM-Chat-Common/core/generation_loop.py — единый источник правок.
from core.common_loader import load_common_module

globals().update({
    k: v for k, v in vars(load_common_module("core/generation_loop")).items()
    if not (k.startswith("__") and k.endswith("__"))
})
