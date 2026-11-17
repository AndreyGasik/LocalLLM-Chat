# core/file_writer.py
"""
Безопасная запись файлов, которые генерирует модель.

Правила безопасности (важно не ослаблять при доработках):
  1. Модель НИКОГДА не пишет по пути, который она сама придумала.
     Из предложенного ею имени берётся только basename (без ../, без
     абсолютных путей) — реальная директория всегда фиксированная,
     см. config.GENERATED_FILES_DIR.
  2. Оригинальный файл, который пользователь прикрепил к сообщению,
     этот модуль вообще не открывает на запись — только на чтение
     (да и то не здесь, а в core/worker.py::read_file/read_pdf).
  3. Существующие файлы в папке вывода никогда не перезаписываются
     молча — при совпадении имени подбирается свободное (_1, _2, ...).
  4. Перенос черновика в конечное место (поверх чего-либо) выполняет
     только пользователь вручную, через диалог "Сохранить как" в UI.
"""
import re
import shutil
import subprocess
from pathlib import Path
from config import GENERATED_FILES_DIR

_SAFE_NAME_RE = re.compile(r'[^\w\-. а-яА-ЯёЁ]', re.UNICODE)


def _sanitize_filename(raw: str, fallback: str = "документ") -> str:
    """Оставляет только имя файла (без пути) и убирает всё «подозрительное»."""
    name = Path((raw or "").strip() or fallback).name
    name = _SAFE_NAME_RE.sub("_", name).strip(" ._")
    return name or fallback


def _unique_path(directory: Path, stem: str, ext: str) -> Path:
    directory.mkdir(parents=True, exist_ok=True)
    candidate = directory / f"{stem}{ext}"
    i = 1
    while candidate.exists():
        candidate = directory / f"{stem}_{i}{ext}"
        i += 1
    return candidate


def stage_markdown(requested_name: str, content: str) -> Path:
    """Сохраняет текст как новый .md-черновик в изолированной папке вывода."""
    safe = _sanitize_filename(requested_name)
    stem = Path(safe).stem or "документ"
    out = _unique_path(GENERATED_FILES_DIR, stem, ".md")
    out.write_text(content, encoding="utf-8")
    return out


def pandoc_available() -> bool:
    return shutil.which("pandoc") is not None


def convert_with_pandoc(md_path: Path, target_ext: str) -> Path | None:
    """target_ext: '.docx' или '.pdf'. None при отсутствии pandoc/ошибке —
    в этом случае вызывающий код просто оставляет .md-черновик как есть."""
    if not pandoc_available():
        return None
    out_path = md_path.with_suffix(target_ext)

    cmd_variants = [["pandoc", str(md_path), "-o", str(out_path)]]
    if target_ext == ".pdf" and shutil.which("typst"):
        # typst — лёгкий движок (мегабайты, не гигабайты, как texlive),
        # пробуем его первым; если недоступен или упал — падаем на
        # обычный вызов (сработает, если у пользователя стоит texlive).
        cmd_variants.insert(0, ["pandoc", str(md_path), "-o", str(out_path), "--pdf-engine=typst"])

    for cmd in cmd_variants:
        try:
            r = subprocess.run(cmd, capture_output=True, text=True, timeout=60)
            if r.returncode == 0 and out_path.exists():
                return out_path
        except Exception:
            pass
    return None
