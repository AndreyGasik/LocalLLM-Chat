# core/model_profiles/nanbeige.py
#
# Модуль из плана доработки (nanbeige-integration-plan.md, раздел 2.1),
# дополненный найденным фиксом бага с tool-calling (раздел "Фикс").
#
# Диагноз (см. хвост плана): приложение в tool_mode="text" одновременно
# инструктирует модель ДВУМЯ синтаксисами — голым "SEARCH: <запрос>" для
# поиска/скрейпинга и JSON-в-тегах <tool_call>{...}</tool_call> для
# write_text_file. Nanbeige обучена ровно на одном родном формате
# (<tool_call>{"name":...,"arguments":{...}}</tool_call>) и, получив
# инструкцию "напиши строкой SEARCH: <запрос>", попыталась впихнуть её в
# привычный tool_call, родив невалидный гибрид:
#   <tool_call>{"name": "SEARCH: <запрос>, <уточнение>"></tool_call>
# — ни один } не закрыт, поля arguments нет, _parse_text_tool_calls такое
# не распознаёт (ему нужен настоящий сбалансированный JSON внутри тегов),
# и сырой мусор утекает прямо в чат пользователю.
#
# Фикс — не в парсере (он уже универсален и ничего чинить не нужно), а в
# промпте: для Nanbeige ВСЕ инструменты (включая search/scrape/read_file/
# memory_*) описываются как JSON-схемы и модели предлагается ровно один
# способ их вызвать — тот же <tool_call>{...}</tool_call>, который
# _parse_text_tool_calls и так умеет разбирать. Это тот же паттерн, что и
# у LFM2 (_build_lfm2_tools_block), просто в родном для Nanbeige синтаксисе.
import json
import re

_NANBEIGE_RE = re.compile(r"nanbeige", re.IGNORECASE)


def is_nanbeige_model(model_name: str) -> bool:
    return bool(_NANBEIGE_RE.search(model_name or ""))


# Пресеты из карточки модели (см. раздел Quickstart):
#   агентные/тул-юз сценарии: temperature=1.0, max_new_tokens=65536
#   рассуждения/чат:          temperature=0.6, top_p=0.95, top_k=20,
#                              max_new_tokens=131072
NANBEIGE_SAMPLING = {
    "agentic":   {"temperature": 1.0, "top_p": 0.95, "top_k": 20, "max_tokens": 65536},
    "reasoning": {"temperature": 0.6, "top_p": 0.95, "top_k": 20, "max_tokens": 131072},
}


def nanbeige_payload_overrides(use_search_or_tools: bool) -> dict:
    """Поля для подмешивания в payload запроса, если выбрана модель
    Nanbeige. Ничего не решает сама — только параметры из официальной
    карточки модели (включая top_k, который приложение сейчас вообще не
    отправляет ни для одной другой модели)."""
    preset = NANBEIGE_SAMPLING["agentic" if use_search_or_tools else "reasoning"]
    return dict(preset)


# Уникальный маркер этого блока в системном промпте. Существующая проверка
# "не добавлять instr повторно" в core/worker.py::run() завязана на строки
# из старого текстового формата ("READ_FILE:", "tool_call_start"), которых
# в JSON-схемах Nanbeige попросту нет — без отдельного маркера инструкция
# задваивалась бы на каждой итерации MAX_TOOL_ITER-цикла. Строка нарочно
# не похожа на обычный текст ответа модели, чтобы не словить ложное
# совпадение.
NANBEIGE_TOOLS_MARKER = "<!-- nanbeige-tools-block -->"


def build_nanbeige_tools_block(tools: list[dict]) -> str:
    """Аналог core/tool_parsing.py::_build_lfm2_tools_block, но для родного
    формата Nanbeige. На вход — список тех же tool-схем, что уже
    используются в core/tool_definitions.py (SEARCH_TOOL, FETCH_TOOLS,
    FILE_TOOLS, MEMORY_*_TOOL) плюс WRITE_TOOLS — то есть ВСЕ доступные в
    этом раунде инструменты одним списком, а не вперемешку с текстовым
    SEARCH:-синтаксисом.

    Парсить результат отдельно не нужно: он ловится существующим
    core/tool_parsing.py::_parse_text_tool_calls (regex на
    <tool_call>\\s*(\\{...\\})\\s*</tool_call>), который уже разбирает
    write_text_file в tool_mode="text" — просто теперь по этому же
    синтаксису пойдут и search/scrape/read_file/memory_*.
    """
    schemas = []
    for t in tools:
        if t.get("type") == "function" and isinstance(t.get("function"), dict):
            schemas.append(t["function"])
        elif isinstance(t.get("name"), str):
            schemas.append(t)
    return (
        f"{NANBEIGE_TOOLS_MARKER}\n"
        "Доступные инструменты (JSON-схемы ниже). Чтобы вызвать инструмент, "
        "используй РОВНО этот формат и никакой другой:\n"
        "<tool_call>{\"name\": \"<имя_инструмента>\", \"arguments\": {...}}</tool_call>\n"
        "Не изобретай других префиксов (SEARCH:, SCRAPE: и т.п.) — только "
        "<tool_call> с именем и arguments из схемы ниже.\n\n"
        f"{json.dumps(schemas, ensure_ascii=False, indent=2)}"
    )
