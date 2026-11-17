# core/model_profiles/spark.py — тонкая обёртка.
# Реализация в LLM-Chat-Common/core/model_profiles/spark.py — единый источник правок.
from core.common_loader import load_common_module

globals().update({
    k: v for k, v in vars(load_common_module("core/model_profiles/spark")).items()
    if not (k.startswith("__") and k.endswith("__"))
})
