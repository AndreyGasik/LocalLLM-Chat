# app/ui/main_window/chat_io.py — тонкая обёртка.
# Реализация в LLM-Chat-Common/ui/main_window/chat_io.py.
from core.common_loader import load_common_module

globals().update({
    k: v for k, v in vars(load_common_module("ui/main_window/chat_io")).items()
    if not (k.startswith("__") and k.endswith("__"))
})
