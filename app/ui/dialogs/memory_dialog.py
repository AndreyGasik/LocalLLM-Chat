# ui/dialogs/memory_dialog.py — тонкая обёртка.
# Реализация в LLM-Chat-Common/ui/dialogs/memory_dialog.py — единый источник правок.
from core.common_loader import load_common_module

globals().update({
    k: v for k, v in vars(load_common_module("ui/dialogs/memory_dialog")).items()
    if not (k.startswith("__") and k.endswith("__"))
})
