# core/skills.py
"""
"Skills" — процедурные инструкции для модели (не факты о пользователе,
поэтому не в memory_db). Каждый skill — отдельный .md-файл в папке
skills/, подключаемый ЦЕЛИКОМ и ТОЛЬКО на один конкретный запрос, никогда
не сохраняется в историю и не примешивается к обычному system-промпту
по умолчанию — иначе модель начала бы применять его сама, без команды.
"""
from pathlib import Path

_SKILLS_DIR = Path(__file__).resolve().parent.parent / "skills"


def load_skill(name: str) -> str:
    path = _SKILLS_DIR / f"{name}.md"
    try:
        return path.read_text(encoding="utf-8").strip()
    except Exception:
        return ""
