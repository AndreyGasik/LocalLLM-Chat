# ui/widgets.py — тонкая обёртка.
# Реализация в LLM-Chat-Common/ui/widgets.py — единый источник правок.
from core.common_loader import load_common_module

globals().update({
    k: v for k, v in vars(load_common_module("ui/widgets")).items()
    if not (k.startswith("__") and k.endswith("__"))
})
