# ui/result_file_card.py — тонкая обёртка.
# Реализация в LLM-Chat-Common/ui/result_file_card.py — единый источник правок.
from core.common_loader import load_common_module

globals().update({
    k: v for k, v in vars(load_common_module("ui/result_file_card")).items()
    if not (k.startswith("__") and k.endswith("__"))
})
