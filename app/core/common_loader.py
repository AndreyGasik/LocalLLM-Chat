# core/common_loader.py
"""Загрузчик общих модулей из LLM-Chat-Common — единого источника правок
всей общей логики приложения.

Каждый общий модуль кэшируется в sys.modules под именем
llmchat_common_<имя>: все, кто импортирует через этот загрузчик (прямо
или через обёртки), получают ОДИН и тот же объект класса/состояния."""
import importlib.util
import os
import sys
from pathlib import Path

_PREFIX = "llmchat_common_"


def _find_common() -> Path:
    here = Path(__file__).resolve()
    cands = []
    env = os.environ.get("LLMCHAT_COMMON")
    if env:
        cands.append(Path(env))
    cands += [here.parents[2] / "LLM-Chat-Common", here.parents[1] / "common"]
    for c in cands:
        if c.is_dir():
            return c
    raise ImportError(
        "Не найдена папка LLM-Chat-Common. Положите её рядом с папкой проекта "
        "или задайте LLMCHAT_COMMON=/путь/к/LLM-Chat-Common. Искал: "
        + ", ".join(str(c) for c in cands)
    )


def load_common_module(rel: str):
    """Загрузить LLM-Chat-Common/<rel>.py (например 'core/markdown')."""
    # Общая папка нужна и как источник модулей через загрузчик, и на
    # sys.path — сами общие модули импортируют aurora/chat_widgets
    # обычными абсолютными импортами.
    common_dir = str(_find_common())
    if common_dir not in sys.path:
        sys.path.insert(0, common_dir)
    mod_name = _PREFIX + rel.replace("/", "_").replace("\\", "_")
    if mod_name in sys.modules:
        return sys.modules[mod_name]
    path = _find_common() / (rel + ".py")
    spec = importlib.util.spec_from_file_location(mod_name, path)
    mod = importlib.util.module_from_spec(spec)
    sys.modules[mod_name] = mod
    spec.loader.exec_module(mod)
    return mod
