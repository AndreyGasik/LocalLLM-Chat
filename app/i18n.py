# i18n.py — тонкая обёртка.
# Реализация в LLM-Chat-Common/i18n.py — единый источник правок.
from core.common_loader import load_common_module

globals().update({
    k: v for k, v in vars(load_common_module("core/i18n")).items()
    if not (k.startswith("__") and k.endswith("__"))
})
