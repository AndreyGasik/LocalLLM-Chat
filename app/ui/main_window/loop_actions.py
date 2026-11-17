# app/ui/main_window/loop_actions.py — тонкая обёртка.
# Реализация в LLM-Chat-Common/ui/main_window/loop_actions.py.
from core.common_loader import load_common_module

globals().update({
    k: v for k, v in vars(load_common_module("ui/main_window/loop_actions")).items()
    if not (k.startswith("__") and k.endswith("__"))
})
