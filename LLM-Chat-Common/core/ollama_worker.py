# core/worker.py — Worker для Ollama-бэкенда.
#
# Вся общая логика раундов генерации (сигналы, Stop через разрыв соединения,
# display_gate, парсинг и исполнение тулов, guard'ы пустого/фейкового ответа,
# переспрос, статистика) — в LLM-Chat-Common/core/generation_loop.py.
# Здесь только специфика протокола Ollama: /api/chat (NDJSON),
# message.thinking/content/tool_calls, keep_alive, opts (num_ctx/temperature/
# top_p/repeat_penalty для Spark), нативный tool_mode == "native".
import json

from PyQt6.QtCore import pyqtSignal

from config import OLLAMA_API
from http_client import _HTTP, _NO_PROXY
from core.tool_definitions import (
    SEARCH_TOOL, FETCH_TOOLS, FILE_TOOLS,
    MEMORY_WRITE_TOOL, MEMORY_READ_TOOL, MEMORY_DELETE_TOOL,
    TERMINAL_TOOL,
)
from core.tool_parsing import (
    _parse_simple_text_tools, _parse_text_tool_calls,
    _parse_xml_tag_tool_calls, _parse_argkv_tool_calls,
    _build_spark_tools_instruction, _build_text_tools_instruction,
    _TOOL_RESULT_NOTE, _parse_lfm2_tool_calls,
    _build_lfm2_tools_block,
)
from core.search import do_search           # модульная ссылка: тесты патчат W.do_search
from core.terminal import _execute_command_safe  # ре-экспорт: тесты зовут W._execute_command_safe
from core.generation_loop import GenerationWorkerBase, _dbg_write

__all__ = ["Worker", "_dbg_write", "do_search", "_execute_command_safe"]


class Worker(GenerationWorkerBase):
    """Worker Ollama-бэкенда: /api/chat, NDJSON-стрим."""

    finished = pyqtSignal(str, float, int, float)  # (текст, elapsed, токены, ttft)
    _debug_prefix = "llmchat"

    def __init__(self, model, messages, temperature, top_p,
                 use_search, scraper, native_tools_allowed=True,
                 num_results=10, default_time_range="month", memory=None,
                 tool_mode="auto", num_ctx=16384,
                 enable_file_tools=True, enable_memory_tools=True,
                 enable_write_tools=True, enable_terminal_tool=False,
                 memory_intent=False):
        super().__init__(
            history=messages, use_search=use_search, scraper=scraper,
            num_results=num_results, default_time_range=default_time_range,
            memory=memory, tool_mode=tool_mode, memory_intent=memory_intent,
            enable_file_tools=enable_file_tools,
            enable_memory_tools=enable_memory_tools,
            enable_write_tools=enable_write_tools,
            enable_terminal_tool=enable_terminal_tool,
        )
        self.model = model
        self.temperature = temperature
        self.top_p = top_p
        self.num_ctx = num_ctx
        self.native_tools_allowed = native_tools_allowed
        self._use_native_tools = False

    def _active_tools(self) -> list:
        # Каждая группа инструментов включается своим отдельным тумблером —
        # раньше всё было завязано на use_search, и файлы/память/запись
        # становились недоступны, стоило выключить поиск.
        # Локальный импорт — как в llama_worker._active_tools: модульный
        # импорт забыт при слиянии, и каждый Ollama-запрос с включённым
        # тумблером «Запись» падал с NameError: WRITE_TOOLS.
        from core.write_tool_definitions import WRITE_TOOLS
        tools = []
        if self.use_search:
            tools += [SEARCH_TOOL] + FETCH_TOOLS
        if self.enable_file_tools:
            tools += FILE_TOOLS
        if self.enable_memory_tools and self.memory_intent:
            tools += [MEMORY_WRITE_TOOL, MEMORY_READ_TOOL, MEMORY_DELETE_TOOL]
        if self.enable_write_tools:
            tools += WRITE_TOOLS
        if self.enable_terminal_tool:
            tools.append(TERMINAL_TOOL)
        return tools

    def _do_search(self, query: str, num_results: int, time_range: str):
        # Читаем МОДУЛЬНУЮ ссылку в момент вызова — monkeypatch.setattr(W,
        # "do_search", fake) в тестах подменяет именно её.
        return do_search(query, num_results, time_range)

    def _round_instruction(self) -> str:
        active_tools = self._active_tools()
        # Нативный tool-calling (payload["tools"] с полными JSON-схемами) не
        # включается автоматически — он раздувает промпт в разы по сравнению
        # с компактной текстовой инструкцией. Осознанный выбор через
        # tool_mode == "native".
        self._use_native_tools = (
            bool(active_tools) and self.native_tools_allowed
            and self.tool_mode == "native"
        )
        if self._use_native_tools:
            return ""
        if self.tool_mode == "lfm2" and active_tools:
            tools_block = _build_lfm2_tools_block(active_tools)
            return (
                "\n=== Доступные инструменты "
                "(используй через <|tool_call_start|>...<|tool_call_end|>) ===\n"
                f"{tools_block}"
            )
        if self.tool_mode == "spark" and active_tools:
            # Если последнее сообщение — результат инструмента, вместо
            # «сначала вызови search» просим не искать заново (иначе правило
            # про обязательный поиск срабатывало в КАЖДОМ раунде).
            _last = self.messages[-1] if self.messages else {}
            after_result = (
                _last.get("role") == "user"
                and str(_last.get("content", "")).startswith("[Результат ")
            )
            return _build_spark_tools_instruction(
                self.use_search, self.enable_file_tools,
                self.enable_memory_tools and self.memory_intent,
                self.enable_write_tools,
                enable_terminal=self.enable_terminal_tool,
                after_result=after_result,
            )
        if active_tools:
            return _build_text_tools_instruction(
                use_search=self.use_search,
                enable_files=self.enable_file_tools,
                enable_memory=(self.enable_memory_tools and self.memory_intent),
                enable_write=self.enable_write_tools,
                enable_terminal=self.enable_terminal_tool,
            )
        return ""

    def _prepare_request(self, instr: str):
        opts = {}
        if self.num_ctx is not None:
            opts["num_ctx"] = self.num_ctx
        if self.temperature is not None:
            opts["temperature"] = self.temperature
        if self.top_p is not None:
            opts["top_p"] = self.top_p
        if self.tool_mode == "spark":
            # Карточка Spark-X2.6 рекомендует repetition_penalty = 1; у Ollama
            # по умолчанию штраф за повторы включён (1.1), что портит теги
            # вызова (</arg_value>) и русские окончания.
            opts["repeat_penalty"] = 1.0

        payload = {
            "model": self.model,
            "messages": self.messages,
            "stream": True,
            "keep_alive": "10m",
            "options": opts,
        }
        if self._use_native_tools:
            payload["tools"] = self._active_tools()
        if instr:
            # Инструкция живёт ТОЛЬКО в копии сообщений этого запроса —
            # история (self.messages) остаётся чистой, иначе модель на
            # следующем раунде видит «свою» инструкцию и пересказывает её.
            msgs = list(self.messages)
            if msgs and msgs[0].get("role") == "system":
                sys_copy = dict(msgs[0])
                sys_copy["content"] = sys_copy["content"] + instr
                msgs[0] = sys_copy
            else:
                msgs.insert(0, {"role": "system",
                                "content": "Ты полезный ИИ-ассистент." + instr})
            payload["messages"] = msgs
        return OLLAMA_API, payload

    def _post(self, url: str, payload: dict):
        return _HTTP.post(url, json=payload, stream=True, timeout=180,
                          proxies=_NO_PROXY)

    def _parse_stream_line(self, line) -> dict | None:
        try:
            data = json.loads(line)
        except Exception:
            return None
        msg = data.get("message", {})
        usage = None
        if data.get("done"):
            # Ollama присылает реальные счётчики только в финальном чанке —
            # это реальный размер промпта и ответа именно этого запроса.
            usage = (data.get("prompt_eval_count", 0),
                     data.get("eval_count", 0))
        return {
            "text": msg.get("content", ""),
            "reasoning": msg.get("thinking", ""),
            "tool_calls": msg.get("tool_calls"),
            "usage": usage,
            "done": data.get("done", False),
        }

    def _parse_round_tools(self, text: str, native_calls: list) -> list:
        if native_calls:
            return native_calls
        if self.tool_mode == "lfm2" and text.strip():
            calls = _parse_lfm2_tool_calls(text)
            if calls:
                return calls
        if text.strip() and not self._use_native_tools \
                and self.tool_mode != "lfm2":
            simple = _parse_simple_text_tools(text)
            if simple:
                return simple
            # Модель иногда вместо построчного "SCRAPE: url" придумывает
            # свой XML-тег <SCRAPE, url="...">...</SCRAPE> — или GLM-формат
            # SEARCH<arg_key>…</arg_key><arg_value>…</arg_value> (Spark).
            xml_tag = (_parse_xml_tag_tool_calls(text)
                       or _parse_argkv_tool_calls(text))
            if xml_tag:
                return xml_tag
            return _parse_text_tool_calls(text)
        return []

    def _drop_round_draft(self) -> bool:
        # Текстовые режимы: черновик раунда с вызовом выбрасывается целиком;
        # lfm2/nanbeige оставляют вычищенный черновик частью итога.
        return (not self._use_native_tools
                and self.tool_mode not in ("lfm2", "nanbeige"))

    def _append_tool_result_msg(self, name: str, content: str, args: dict):
        if self._use_native_tools:
            # role:"tool" — часть нативного протокола Ollama: рендерится
            # шаблоном модели только в паре с assistant-сообщением, у
            # которого есть поле tool_calls (оно добавлено в историю выше).
            self.messages.append({"role": "tool", "name": name, "content": content})
        else:
            # В текстовых режимах «осиротевшее» tool-сообщение шаблон либо не
            # рендерит, либо рендерит некорректно — результат отдаём как
            # обычное user-сообщение с пометкой вызова (иначе модель не
            # связывает результат со своим вызовом и повторяет его).
            call_note = json.dumps(args, ensure_ascii=False)[:200]
            hdr = f"[Результат {name} ← {call_note}]"
            self.messages.append({
                "role": "user",
                "content": f"{hdr}:\n{content}{_TOOL_RESULT_NOTE}",
            })

    def _emit_finished(self, full_text: str, elapsed: float,
                       token_count: int, ttft: float):
        self.finished.emit(full_text, elapsed, token_count, ttft)
