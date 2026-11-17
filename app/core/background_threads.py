# core/background_threads.py — тонкая обёртка.
# Реализация в LLM-Chat-Common/core/background_threads.py — единый источник правок.
from core.common_loader import load_common_module

globals().update({
    k: v for k, v in vars(load_common_module("core/background_threads")).items()
    if not (k.startswith("__") and k.endswith("__"))
})
