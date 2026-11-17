"""Тесты общего разбора tool-call'ов. Запуск: pytest LLM-Chat-Common/tests"""
import importlib.util
from pathlib import Path

import pytest

_path = Path(__file__).resolve().parents[1] / "tool_parsing.py"
_spec = importlib.util.spec_from_file_location("tp_under_test", _path)
tp = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(tp)


# ─────────────── Толерантность маркеров: двойники, скобки, опечатки ───────
# Маленькие модели (LFM3-1.7B и т.п.) пишут маркер с кириллическими
# буквами-двойниками («СЕARCH»), теряют буквы («CEARCH» = SEARCH без S) и
# оборачивают вызов в скобки «[SEARCH: …]» по аналогии с «[Результат …]».
# Диагностика ноябрь 2026: без этого «ни один инструмент не вызывается».
@pytest.mark.parametrize("text,expected_query", [
    ("[СЕARCH: В.И.Ленин место рождения]", "В.И.Ленин место рождения"),
    ("CEARCH: курс евро",                  "курс евро"),
    ("SARCH: погода",                      "погода"),
    ("SEARCH: погода в Хельсинки",         "погода в Хельсинки"),
])
def test_marker_typo_tolerance(text, expected_query):
    result = tp._parse_simple_text_tools(text)
    assert calls(result) == [("search", {"query": expected_query})]


def test_marker_labeled_prefix_still_works():
    assert calls(tp._parse_simple_text_tools("Инструмент: SCRAPE: https://a.ru")) == \
        [("scrape_url", {"url": "https://a.ru"})]


def test_documentation_lines_are_not_calls():
    assert tp._parse_simple_text_tools("SEARCH — только для сведений из интернета") is None
    assert tp._parse_simple_text_tools("Чтобы найти, напиши SEARCH: <запрос>") is None
    assert tp._parse_simple_text_tools("Дата: 2026-01-17") is None
    assert tp._parse_simple_text_tools("Note: это просто текст") is None
    assert tp._parse_simple_text_tools("EXEC_CMD: <команда>") is None


def test_memory_read_bare_still_works():
    assert calls(tp._parse_simple_text_tools("MEMORY_READ:")) == \
        [("memory_read", {})]


def test_strip_cleans_bracketed_typo_marker():
    cleaned = tp._strip_text_tool_call("[СЕARCH: вопрос]\nВот ответ.")
    assert "СЕARCH" not in cleaned and "Вот ответ." in cleaned


# ─────────────── Детектор «фейкового результата» ──────────────────────────
# Настоящие результаты приходят ОТДЕЛЬНЫМИ user-сообщениями; строка
# «[Результат …]» в тексте ответа — всегда имитация выполнения моделью.
def test_fake_result_line_detected():
    assert tp._FAKE_RESULT_LINE_RE.search(
        "[Результат execute_terminal_command]: 2026-01-17 10:23:45 CST (UTC+8)")
    assert tp._FAKE_RESULT_LINE_RE.search("[Результат search ← {\"query\": \"x\"}]")


def test_fake_result_line_stripped_keeps_real_text():
    t = "[Результат execute_terminal_command]: фейк\nНастоящий текст"
    assert tp._FAKE_RESULT_LINE_RE.sub("", t).strip() == "Настоящий текст"


def calls(result):
    """[(имя, аргументы)] — для компактных сравнений."""
    return [(c["function"]["name"], c["function"]["arguments"]) for c in (result or [])]


# ───────────────────────── SEARCH:/SCRAPE: (простой текстовый режим)
@pytest.mark.parametrize("text,expected", [
    ("SEARCH: погода в Хельсинки", [("search", {"query": "погода в Хельсинки"})]),
    ("search: курс евро",           [("search", {"query": "курс евро"})]),
    ("Инструмент: SCRAPE: https://a.ru", [("scrape_url", {"url": "https://a.ru"})]),
    ("READ_FILE: /etc/hostname",    [("read_file", {"path": "/etc/hostname"})]),
    ("SEARCHPAGE: https://a.ru | цена",
        [("search_page", {"url": "https://a.ru", "query": "цена"})]),
    ("MEMORY_WRITE: note | k | значение",
        [("memory_write", {"category": "note", "key": "k", "value": "значение"})]),
])
def test_simple_formats(text, expected):
    assert calls(tp._parse_simple_text_tools(text)) == expected


def test_scrape_with_commas_becomes_scrape_multiple():
    r = tp._parse_simple_text_tools("SCRAPE: https://a.ru, https://b.ru")
    assert calls(r) == [("scrape_multiple", {"urls": ["https://a.ru", "https://b.ru"]})]


def test_placeholder_line_is_documentation_not_call():
    assert tp._parse_simple_text_tools("Формат: SEARCH: <запрос>") is None


def test_real_call_after_documentation_line():
    r = tp._parse_simple_text_tools("SEARCH: <запрос>\nSEARCH: курс евро")
    assert calls(r) == [("search", {"query": "курс евро"})]


def test_keyword_must_start_the_line():
    # описание синтаксиса посреди предложения — не вызов
    assert tp._parse_simple_text_tools("Чтобы искать, напиши слово SEARCH: и запрос") is None


def test_stray_closing_tags_are_stripped():          # привычка Spark
    r = tp._parse_simple_text_tools("SEARCH: ленин</arg_value>")
    assert calls(r) == [("search", {"query": "ленин"})]


# ───────────────────────── JSON / lfm2 / ```tool_call
def test_tool_call_json_wrapper():
    t = ('Сохраняю.\n<tool_call>{"name":"write_text_file","arguments":'
         '{"suggested_name":"a.md","content":"x"}}</tool_call>')
    assert calls(tp._parse_text_tool_calls(t)) == [
        ("write_text_file", {"suggested_name": "a.md", "content": "x"})]


def test_lfm2_tool_call_markers():
    t = '<|tool_call_start|>call:search{"query":"q"}<|tool_call_end|>'
    assert calls(tp._parse_text_tool_calls(t)) == [("search", {"query": "q"})]


def test_bare_json_call_that_dominates_text():
    t = '{"name":"search","arguments":{"query":"x"}}'
    assert calls(tp._parse_text_tool_calls(t)) == [("search", {"query": "x"})]


def test_json_example_after_cue_is_ignored():
    t = ('Например: {"name":"search","arguments":{"query":"x"}} — так выглядит '
         'вызов, а ещё много текста вокруг него, чтобы объект не доминировал.')
    assert tp._parse_text_tool_calls(t) == []


def test_json_with_braces_inside_string_value():
    t = '{"name":"write_text_file","arguments":{"suggested_name":"a.md","content":"код {x}"}}'
    assert calls(tp._parse_text_tool_calls(t))[0][1]["content"] == "код {x}"


# ───────────────────────── Spark / GLM: NAME<arg_key>..<arg_value>
def test_argkv_with_tool_call_wrapper():
    t = ("Нужно найти.\n<tool_call>search\n<arg_key>query</arg_key>"
         "<arg_value>где родился Ленин</arg_value>\n</tool_call>")
    assert calls(tp._parse_argkv_tool_calls(t)) == [("search", {"query": "где родился Ленин"})]


def test_argkv_multiple_urls():
    t = ("<tool_call>scrape_multiple<arg_key>urls</arg_key>"
         "<arg_value>https://a.ru, https://b.ru</arg_value></tool_call>")
    r = calls(tp._parse_argkv_tool_calls(t))
    assert r and r[0][0] == "scrape_multiple"


def test_argkv_unknown_name_is_not_a_call():
    assert not tp._parse_argkv_tool_calls(
        "<tool_call>foo<arg_key>a</arg_key><arg_value>b</arg_value></tool_call>")


def test_strip_removes_argkv_call_but_keeps_text():
    t = ("Привет.\n<tool_call>search<arg_key>query</arg_key>"
         "<arg_value>x</arg_value></tool_call>\nПока.")
    cleaned = tp._strip_text_tool_call(t)
    assert "arg_key" not in cleaned and "Привет." in cleaned and "Пока." in cleaned


def test_strip_leaves_documentation_untouched():
    assert tp._strip_text_tool_call("Формат: SEARCH: <запрос>") == "Формат: SEARCH: <запрос>"


def test_is_spark_model():
    assert tp._is_spark_model("Spark-X2.6-4B-Q4_K_M.gguf")
    assert tp._is_spark_model("hf.co/XHToken/Spark-X2.6-4B-GGUF:Q4_K_M")
    assert not tp._is_spark_model("llama3.1:8b")
    assert not tp._is_spark_model("sparkle.gguf")


def test_spark_instruction_modes():
    first = tp._build_spark_tools_instruction(True, False, False, False)
    after = tp._build_spark_tools_instruction(True, False, False, False, after_result=True)
    assert "<tool_call>" in first and "сначала вызови search" in first
    assert "сначала вызови search" not in after and "повторно" in after
    assert tp._build_spark_tools_instruction(False, False, False, False) == ""


# ───────────────────────── ToolSyntaxGate (live-фильтр показа)
def _run_gate(text, step):
    g = tp.ToolSyntaxGate()
    out = "".join(g.feed(text[i:i + step]) for i in range(0, len(text), step)) + g.flush()
    return out, g.suppressed_any


CALL = ("Привет\n<tool_call>search\n<arg_key>query</arg_key>"
        "<arg_value>x</arg_value>\n</tool_call>\nХвост")


@pytest.mark.parametrize("step", [1, 3, 7, 200])      # не зависит от нарезки на чанки
def test_gate_hides_syntax_for_any_chunking(step):
    out, suppressed = _run_gate(CALL, step)
    assert "arg_key" not in out and "Привет" in out and suppressed


def test_gate_plain_text_passes_unchanged():
    text = "Обычный ответ.\nВторая строка"
    out, suppressed = _run_gate(text, 2)
    assert out == text and not suppressed


def test_gate_flush_returns_short_ambiguous_tail():
    assert _run_gate("Ответ.\nM", 1)[0] == "Ответ.\nM"


def test_gate_hides_search_line():
    out, _ = _run_gate("Думаю.\nSEARCH: курс евро\n", 5)
    assert "SEARCH" not in out


# ───────────────────────── history / think
def test_strip_orphan_think_keeps_answer_after_closing_tag():
    assert tp._strip_orphan_think("черновик</think>Ответ").strip() == "Ответ"


def test_clean_for_history_removes_pairs_and_unescapes():
    assert tp._clean_for_history("&lt;think&gt;x&lt;/think&gt;Ответ") == "Ответ"


# ───────────────────────── Регрессии: вызов, обложенный прозой / оградой
# Кейс пользователя: модель пишет «выполняю поиск», рядом выводит валидный
# JSON-вызов — раньше эвристика ≥50% отбрасывала его, инструмент не
# запускался, пользователь видел только «обещание» поиска.

def _first_call(result):
    r = calls(result)
    return r[0] if r else None


def test_fenced_json_call_with_prose_around():
    t = ("Сейчас выполню поиск актуальной информации.\n"
         "```json\n"
         '{"name": "search", "arguments": {"query": "кто выиграл выборы"}}\n'
         "```\n"
         "После получения результатов проанализирую данные.")
    assert _first_call(tp._parse_text_tool_calls(t)) ==         ("search", {"query": "кто выиграл выборы"})


def test_fenced_json_without_language_marker():
    t = ('Подождите.\n```\n{"name": "scrape_url", "arguments": '
         '{"url": "https://a.ru"}}\n```\nСкоро отвечу.')
    assert _first_call(tp._parse_text_tool_calls(t)) ==         ("scrape_url", {"url": "https://a.ru"})


def test_bare_json_call_with_long_prose_known_tool():
    # имя — известный инструмент: вызов принимается даже при <50% текста
    t = ('Сейчас я вызову инструмент поиска.\n'
         '{"name": "search", "arguments": {"query": "погода Москва"}}\n'
         "Как только получу результаты, сразу отвечу подробно.")
    assert _first_call(tp._parse_text_tool_calls(t)) ==         ("search", {"query": "погода Москва"})


def test_bare_json_unknown_name_without_dominance_still_rejected():
    # неизвестное имя + недоминирующий объект — по-прежнему не вызов
    t = ('Какая-то болтовня.\n{"name": "not_a_tool", "arguments": {"x": 1}}\n'
         "и ещё длинный текст после объекта, чтобы он не доминировал.")
    assert tp._parse_text_tool_calls(t) == []


def test_json_example_after_cue_is_still_ignored():
    t = ('Чтобы выполнить поиск, используй формат, например:\n'
         '{"name": "search", "arguments": {"query": "test"}}\n'
         'Сейчас сделаю так.')
    assert tp._parse_text_tool_calls(t) == []


def test_deepseek_native_toolcall_tokens_as_text():
    # спецтокены (U+FF5C ｜, U+2581 ▁), напечатанные моделью как обычный текст
    t = ("<｜tool▁calls▁begin｜><｜tool▁call▁begin｜>function"
         "<｜tool▁name｜>search\n"
         '<｜tool▁input｜>{"query": "Ленин место рождения"}\n'
         "<｜tool▁call▁end｜><｜tool▁calls▁end｜>")
    assert _first_call(tp._parse_text_tool_calls(t)) ==         ("search", {"query": "Ленин место рождения"})


def test_deepseek_ascii_toolcall_variant():
    t = ('<|tool_name|>scrape_url\n<|tool_input|>{"url": "https://a.ru"}')
    assert _first_call(tp._parse_text_tool_calls(t)) ==         ("scrape_url", {"url": "https://a.ru"})


def test_duplicate_calls_deduplicated():
    t = ('```json\n{"name": "search", "arguments": {"query": "x"}}\n```\n'
         '{"name": "search", "arguments": {"query": "x"}}')
    r = tp._parse_text_tool_calls(t)
    assert calls(r) == [("search", {"query": "x"})]


def test_braces_and_escaped_quotes_inside_string_value():
    # скобки и КАВЫЧКИ внутри строковых значений не ломают подсчёт глубины
    # и не режут значение; кавычки в JSON-строке экранированы backslash'ом
    # (chr(92) — чтобы не зависеть от экранирования в исходнике теста)
    BS = chr(92)  # обратный слеш
    escaped = '{' + BS + '"y' + BS + '": 1}'
    t = ('Болтовня вокруг.\n'
         '{"name": "write_text_file", "arguments": '
         '{"suggested_name": "a.md", "content": "код {x} и ' + escaped + '"}}\n'
         'и длинный хвост после объекта.')
    name, args = _first_call(tp._parse_text_tool_calls(t))
    assert name == "write_text_file"
    # json.loads корректно разэкранирует \" → "
    assert args["content"] == 'код {x} и {"y": 1}'
def test_strip_removes_fenced_call_block():
    t = ("Сейчас выполню поиск.\n"
         "```json\n"
         '{"name": "search", "arguments": {"query": "курс евро"}}\n'
         "```\nВсё готово.")
    cleaned = tp._strip_text_tool_call(t)
    assert "search" not in cleaned and "```" not in cleaned
    assert "Сейчас выполню поиск." in cleaned and "Всё готово." in cleaned


def test_strip_removes_deepseek_block_completely():
    t = ("<｜tool▁calls▁begin｜><｜tool▁call▁begin｜>function"
         "<｜tool▁name｜>search\n"
         '<｜tool▁input｜>{"query": "x"}\n'
         "<｜tool▁call▁end｜><｜tool▁calls▁end｜>Ответ")
    cleaned = tp._strip_text_tool_call(t)
    assert cleaned == "Ответ"


# ───────────────────────── «например:» перед ОГРАЖДЁННЫМ вызовом
# (регрессия к анализу: ограда после подводки-цитирования — документация,
# а не вызов; правила приёма и вычистки зеркальны)

def test_fenced_call_after_cue_is_ignored():
    t = ('Формат вызова такой, например:\n'
         '```json\n'
         '{"name": "search", "arguments": {"query": "пример запроса"}}\n'
         '```')
    assert tp._parse_text_tool_calls(t) == []


def test_fenced_call_after_english_cue_is_ignored():
    t = ('The tool call format looks like, for example:\n'
         '```json\n'
         '{"name": "search", "arguments": {"query": "sample"}}\n'
         '```')
    assert tp._parse_text_tool_calls(t) == []


def test_fenced_call_without_cue_is_accepted():
    t = ('Сейчас выполню поиск…\n'
         '```json\n'
         '{"name": "search", "arguments": {"query": "Ленин"}}\n'
         '```')
    assert calls(tp._parse_text_tool_calls(t)) == [("search", {"query": "Ленин"})]


def test_fenced_documentation_survives_strip():
    # зеркальность: что parse не признал вызовом (документация), strip не чистит
    t = ('Формат вызова такой, например:\n'
         '```json\n'
         '{"name": "search", "arguments": {"query": "пример"}}\n'
         '```')
    cleaned = tp._strip_text_tool_call(t)
    assert "```json" in cleaned and "пример" in cleaned


def test_mixed_documentation_and_real_call():
    # документация с «например:» рядом с настоящим вызовом: распознаётся
    # ровно один — настоящий (сканер «голого» JSON не должен подхватить
    # содержимое ограды-документации вторично)
    t = ('Формат такой, например:\n'
         '```json\n'
         '{"name": "search", "arguments": {"query": "шаблон"}}\n'
         '```\n'
         'А теперь реально ищу:\n'
         '```json\n'
         '{"name": "search", "arguments": {"query": "Ленин"}}\n'
         '```')
    assert calls(tp._parse_text_tool_calls(t)) == [("search", {"query": "Ленин"})]


def test_fenced_config_not_accepted_and_not_stripped():
    t = ('Вот конфиг:\n'
         '```json\n'
         '{"model": "qwen3", "context": 8192}\n'
         '```\n'
         'Использую его.')
    assert tp._parse_text_tool_calls(t) == []
    assert "qwen3" in tp._strip_text_tool_call(t)


# ───────────────────────── EXEC_CMD: (терминал)
def test_exec_cmd_simple():
    assert calls(tp._parse_simple_text_tools("EXEC_CMD: uname -a")) == [
        ("execute_terminal_command", {"command": "uname -a"})]


def test_exec_cmd_lowercase_and_prefix():
    r = tp._parse_simple_text_tools("Инструмент: exec_cmd: ls -la /tmp")
    assert calls(r) == [("execute_terminal_command", {"command": "ls -la /tmp"})]


def test_exec_cmd_placeholder_line_is_documentation():
    assert tp._parse_simple_text_tools("EXEC_CMD: <команда>") is None


def test_exec_cmd_strip_removes_line():
    cleaned = tp._strip_text_tool_call("Вот.\nEXEC_CMD: ps aux\nПока.")
    assert "EXEC_CMD" not in cleaned and "Вот." in cleaned and "Пока." in cleaned


def test_exec_cmd_xml_tag():
    r = tp._parse_xml_tag_tool_calls("<EXEC_CMD>uname -r</EXEC_CMD>")
    assert calls(r) == [("execute_terminal_command", {"command": "uname -r"})]


def test_exec_cmd_argkv_with_arg_key():
    t = ("<tool_call>execute_terminal_command"
         "<arg_key>command</arg_key><arg_value>whoami</arg_value></tool_call>")
    r = tp._parse_argkv_tool_calls(t)
    assert calls(r) == [("execute_terminal_command", {"command": "whoami"})]


def test_exec_cmd_gate_hides_line():
    out, suppressed = _run_gate("Думаю.\nEXEC_CMD: ps aux\n", 5)
    assert "EXEC_CMD" not in out and suppressed


def test_spark_instruction_with_terminal():
    s = tp._build_spark_tools_instruction(False, False, False, False,
                                          enable_terminal=True)
    assert "execute_terminal_command" in s
    # без инструментов инструкция по-прежнему пустая
    assert tp._build_spark_tools_instruction(False, False, False, False) == ""


# ── Единая текстовая инструкция (_build_text_tools_instruction) ─────────────
# Единая текстовая инструкция вместо ручных копий в worker.py, которые
# разъезжались (правило «сначала сделай SEARCH» оказывалось то в одной,
# то в другой копии). Кейс journalctl: модель
# потратила 5609 токенов размышлений на простой запрос, «оправдываясь»,
# почему для локальной задачи в терминале ей не нужен поиск в интернете,
# а потом — вызывать ли инструмент повторно, видя «[Результат …]».

def test_text_instruction_syntax_and_flags():
    s = tp._build_text_tools_instruction(use_search=True, enable_terminal=True)
    # синтаксис вызовов — ровно тот, что разбирают парсеры
    assert "SEARCH: <запрос>" in s and "EXEC_CMD: <команда>" in s
    # SEARCH ограничен интернетом; локальные задачи выведены из-под правила
    assert "Локальные задачи" in s
    # ограничения терминала сохранены (страховка — кодом _execute_command_safe)
    assert "--no-pager" in s and "sudo" in s and "&&" in s
    # мостик псевдоним -> полное имя инструмента объяснён заранее
    assert "execute_terminal_command" in s
    assert "MEMORY_WRITE:" not in s and "READ_FILE:" not in s
    # без инструментов инструкция пустая — как у spark-строителя
    assert tp._build_text_tools_instruction() == ""


def test_text_instruction_per_flag_blocks():
    only_files = tp._build_text_tools_instruction(enable_files=True)
    assert "READ_FILE:" in only_files
    assert "SEARCH:" not in only_files and "EXEC_CMD:" not in only_files
    only_mem = tp._build_text_tools_instruction(enable_memory=True)
    assert "MEMORY_WRITE:" in only_mem and "READ_FILE:" not in only_mem
    only_write = tp._build_text_tools_instruction(enable_write=True)
    assert "write_text_file" in only_write and "SEARCH:" not in only_write


def test_tool_result_note():
    # подсказка привязывает результат к вызову и запрещает повторный вызов
    assert "результат твоего вызова" in tp._TOOL_RESULT_NOTE
    assert "не вызывай инструмент повторно" in tp._TOOL_RESULT_NOTE


def test_exec_cmd_json_call_known_name():
    t = ('Проверю.\n{"name": "execute_terminal_command", '
         '"arguments": {"command": "echo hi"}}')
    assert calls(tp._parse_text_tool_calls(t)) == [
        ("execute_terminal_command", {"command": "echo hi"})]


# ── Зачистка эха вызовов в питон-стиле (_strip_bracketed_pythonic_calls) ────
# Кейс из практики: LFM2 в финальном ответе эхом переписывает вызов строкой
# [execute_terminal_command(command='uname -a', timeout=10)] — раньше это
# оставалось и в чате, и в истории.


def test_strip_bracketed_echo_removed():
    t = ("[execute_terminal_command(command='uname -a', timeout=10)]"
         "В вашей системе установлено ядро 7.3.3.")
    out = tp._strip_text_tool_call(t)
    assert "execute_terminal_command" not in out
    assert "ядро 7.3.3" in out


def test_strip_bracketed_echo_with_parens_in_quotes():
    # Скобки и $() внутри кавычек не ломают баланс
    t = ("[execute_terminal_command(command='ps aux | grep \"$(uname)\"', "
         "timeout=5)]Готово.")
    out = tp._strip_text_tool_call(t)
    assert "execute_terminal_command" not in out
    assert "Готово." in out


def test_strip_bracketed_keeps_unknown_and_prose():
    # Неизвестное имя и проза в скобках не трогаются
    t = "см. [my_func(x=1)] и [поиск по сайту](https://example.com)"
    assert tp._strip_text_tool_call(t) == t


def test_strip_bracketed_keeps_unbalanced():
    # Нет закрывающей ']' сразу после ')' — не вызов, не режем
    t = "[execute_terminal_command(command='ls') что-то ещё"
    assert "execute_terminal_command" in tp._strip_text_tool_call(t)


def test_strip_bracketed_alias_and_multiline():
    t = ("Текст до.\n[EXEC_CMD(uname -r)]\nТекст после.")
    # EXEC_CMD без kwargs — парсится только как имя(арг-строка)? нет:
    # без kwarg-синтаксиса это не вызов, оставляем как есть.
    out = tp._strip_text_tool_call(t)
    assert "Текст до." in out and "Текст после." in out


# ─────────────── Цитата формата ≠ вызов (диагностика 2026-11-17) ──────────
# Модель ответила «что ты умеешь?», процитировав JSON-пример из системной
# инструкции (content="..."); правило «имя известно → принимать» выполняло
# цитату как настоящий write_text_file: файл с «...», черновик-ответ
# выбрасывался, ответ писался заново. Дискриминатор _call_args_documentation:
# плейсхолдерные аргументы = документация, не вызов.
def test_json_echo_with_dots_content_is_not_call():
    t = ('Текст.\n{"name": "write_text_file", "arguments": '
         '{"suggested_name": "документ.md", "content": "...", "target_format": "md"}}')
    assert tp._parse_text_tool_calls(t) == []


def test_json_echo_with_placeholder_args_is_not_call():
    t = ('Текст.\n```json\n{"name": "write_text_file", "arguments": '
         '{"suggested_name": "<имя_файла.md>", "content": "<полный текст документа>", '
         '"target_format": "md"}}\n```')
    assert tp._parse_text_tool_calls(t) == []


def test_search_echo_placeholder_query_is_not_call():
    assert tp._parse_text_tool_calls(
        '{"name": "search", "arguments": {"query": "<ваш запрос>"}}') == []


def test_json_echo_documentation_stays_in_text():
    # Зеркальность: парсер цитату отверг → чистка её тоже сохраняет
    # (правило: распознанный вызов вычищается, документация остаётся).
    t = ('Текст.\n```json\n{"name": "write_text_file", "arguments": '
         '{"suggested_name": "<имя_файла.md>", "content": "...", "target_format": "md"}}\n```')
    assert "write_text_file" in tp._strip_text_tool_call(t)


def test_real_write_call_with_short_content_still_works():
    t = ('Сейчас сохраню.\n{"name": "write_text_file", "arguments": '
         '{"suggested_name": "todo.md", "content": "ok", "target_format": "md"}}')
    assert calls(tp._parse_text_tool_calls(t)) == [
        ("write_text_file", {"suggested_name": "todo.md", "content": "ok",
                             "target_format": "md"})]


def test_real_html_content_still_works():
    # Короткий реальный HTML в content — данные, не плейсхолдер
    t = '{"name": "write_text_file", "arguments": {"suggested_name": "x.html", "content": "<b>ok</b>", "target_format": "html"}}'
    assert calls(tp._parse_text_tool_calls(t)) == [
        ("write_text_file", {"suggested_name": "x.html", "content": "<b>ok</b>",
                             "target_format": "html"})]


def test_terminal_command_with_redirects_not_rejected():
    # «< file > out» в настоящей команде похож на плейсхолдер — command
    # дискриминатором не проверяется.
    t = ('Выполняю.\n{"name": "execute_terminal_command", "arguments": '
         '{"command": "wc -l < input.txt > out.txt"}}')
    assert calls(tp._parse_text_tool_calls(t)) == [
        ("execute_terminal_command", {"command": "wc -l < input.txt > out.txt"})]


def test_full_incident_round_text_yields_no_calls():
    # Точный сценарий инцидента: ответ-список возможностей с прозой
    # SEARCH:/READ_FILE:/EXEC_CMD:/SCRAPE: и ограждённой цитатой JSON.
    t = (
        "Я — ваш полезный ИИ-ассистент. Вот что я умею:\n"
        "Поиск информации в интернете:\nРабота с файлами:\n"
        "• Если нужны актуальные данные, начните с SEARCH: <ваш запрос>.\n"
        "• Для файла используйте READ_FILE: /путь/к/файлу.\n"
        "• Для команды напишите EXEC_CMD: <команда>.\n"
        "• Для сайта используйте SCRAPE: <url>.\n"
        "Чтобы сохранить готовый документ отдельным файлом, вызови:\n"
        '```json\n{"name": "write_text_file", "arguments": '
        '{"suggested_name": "документ.md", "content": "...", "target_format": "md"}}\n```'
    )
    # Цепочка разбора llama-воркера (text-режим), как в _parse_round_tools:
    assert tp._parse_simple_text_tools(t) is None
    assert tp._parse_xml_tag_tool_calls(t) == []
    assert tp._parse_argkv_tool_calls(t) == []
    assert tp._parse_text_tool_calls(t) == []


def test_argkv_write_echo_placeholder_not_call():
    t = ("Чтобы сохранить документ: write_text_file"
         "<arg_key>suggested_name</arg_key><arg_value>имя.md</arg_value>"
         "<arg_key>content</arg_key><arg_value>...</arg_value>")
    assert tp._parse_argkv_tool_calls(t) == []


def test_xml_tag_placeholder_not_call():
    assert tp._parse_xml_tag_tool_calls('<SCRAPE url="<url>"/>') == []
    assert calls(tp._parse_xml_tag_tool_calls('<SCRAPE url="https://a.ru"/>')) == [
        ("scrape_url", {"url": "https://a.ru"})]
