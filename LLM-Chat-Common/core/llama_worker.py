# core/worker.py — LlamaWorker для llama.cpp-бэкенда (/v1/chat/completions).
#
# Вся общая логика раундов генерации (сигналы, Stop через разрыв соединения,
# display_gate, парсинг и исполнение тулов, guard'ы пустого/фейкового
# ответа, переспрос, статистика) — в LLM-Chat-Common/core/generation_loop.py.
# Здесь только специфика llama.cpp: SSE-стрим (data:/[DONE]), delta с
# reasoning_content, профили tool_mode (text/lfm2/nanbeige/spark),
# stream_options.include_usage, max_tokens.
import json

from PyQt6.QtCore import pyqtSignal

from core.tool_parsing import (
    _parse_simple_text_tools, _parse_text_tool_calls,
    _parse_xml_tag_tool_calls, _parse_argkv_tool_calls,
    _build_spark_tools_instruction, _build_text_tools_instruction,
    _TOOL_RESULT_NOTE, _parse_lfm2_tool_calls,
    _build_lfm2_tools_block,
)
from core.model_profiles.nanbeige import build_nanbeige_tools_block, NANBEIGE_TOOLS_MARKER
from core.search import do_search           # модульная ссылка: тесты патчат W.do_search
from core.terminal import _execute_command_safe  # ре-экспорт: тесты зовут W._execute_command_safe
from core.generation_loop import GenerationWorkerBase, _dbg_write

__all__ = ["LlamaWorker", "_dbg_write", "do_search", "_execute_command_safe"]


class LlamaWorker(GenerationWorkerBase):
    """Worker llama.cpp-бэкенда: OpenAI-совместимый SSE-стрим."""

    # Арность finished — (текст, elapsed, токены, ttft, полная история):
    # chat_io сохраняет conversation_history из этого списка.
    finished = pyqtSignal(str, float, int, float, list)
    _debug_prefix = "llmchat_llama"

    def __init__(self, api_url, payload, search_enabled, num_res, scraper,
                 max_tokens_val, memory=None, tool_mode="text",
                 memory_intent=False, enable_file_tools=True,
                 enable_memory_tools=True, enable_write_tools=True,
                 enable_terminal_tool=False):
        super().__init__(
            history=payload.get("messages", []), use_search=search_enabled,
            scraper=scraper, num_results=num_res, default_time_range="none",
            memory=memory, tool_mode=tool_mode, memory_intent=memory_intent,
            enable_file_tools=enable_file_tools,
            enable_memory_tools=enable_memory_tools,
            enable_write_tools=enable_write_tools,
            enable_terminal_tool=enable_terminal_tool,
        )
        self.api_url = api_url
        self.payload = payload
        self.max_tokens_val = max_tokens_val
        # payload["messages"] — ТА ЖЕ живая история, что в self.messages:
        # каждый раунд _prepare_request перезаякоривает её заново.
        self.payload["messages"] = self.messages
        self.payload.setdefault("stream_options", {"include_usage": True})

    def _active_tools(self) -> list:
        from core.tool_definitions import (
            SEARCH_TOOL, FETCH_TOOLS, FILE_TOOLS,
            MEMORY_WRITE_TOOL, MEMORY_READ_TOOL, MEMORY_DELETE_TOOL,
            TERMINAL_TOOL,
        )
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
                self.search_enabled, self.enable_file_tools,
                self.enable_memory_tools and self.memory_intent,
                self.enable_write_tools,
                enable_terminal=self.enable_terminal_tool,
                after_result=after_result,
            )
        if self.tool_mode == "nanbeige" and active_tools:
            return "\n" + build_nanbeige_tools_block(active_tools) + "\n"
        if active_tools:
            return _build_text_tools_instruction(
                use_search=self.search_enabled,
                enable_files=self.enable_file_tools,
                enable_memory=(self.enable_memory_tools and self.memory_intent),
                enable_write=self.enable_write_tools,
                enable_terminal=self.enable_terminal_tool,
            )
        return ""

    def _prepare_request(self, instr: str):
        if self.tool_mode == "spark":
            # Spark: инструкция зависит от раунда (after_result) и меняется
            # после результата — поэтому она добавляется в КОПИЮ сообщений
            # только для этого запроса, а self.messages остаётся чистым
            # (иначе в истории накапливались повторные инструкции).
            req_msgs = list(self.messages)
            if req_msgs and req_msgs[0].get("role") == "system":
                sys_copy = dict(req_msgs[0])
                sys_copy["content"] = sys_copy["content"] + instr
                req_msgs[0] = sys_copy
            else:
                req_msgs.insert(0, {"role": "system",
                                    "content": "Ты полезный ИИ-ассистент." + instr})
            request_payload = dict(self.payload)
            request_payload["messages"] = req_msgs
        else:
            # Текстовый/lfm2/nanbeige: инструкция добавляется в системное
            # сообщение ОДИН раз (защита по маркерам — иначе на каждом
            # раунде инструкция дублировалась и раздувала промпт).
            if instr:
                msgs = self.messages
                if msgs and msgs[0].get("role") == "system":
                    sys0 = str(msgs[0].get("content", ""))
                    if ("READ_FILE:" not in sys0
                            and "tool_call_start" not in sys0
                            and NANBEIGE_TOOLS_MARKER not in sys0):
                        msgs[0] = {**msgs[0], "content": sys0 + instr}
                else:
                    msgs.insert(0, {"role": "system",
                                    "content": "Ты полезный ИИ-ассистент." + instr})
            self.payload["messages"] = self.messages
            if self.max_tokens_val > 0:
                self.payload["max_tokens"] = self.max_tokens_val
            return self.api_url, self.payload
        if self.max_tokens_val > 0:
            request_payload["max_tokens"] = self.max_tokens_val
        return self.api_url, request_payload

    def _post(self, url: str, payload: dict):
        import requests
        return requests.post(url, json=payload, stream=True, timeout=(5, 180))

    def _parse_stream_line(self, line) -> dict | None:
        raw = line.decode("utf-8", "replace") if isinstance(line, bytes) else str(line)
        raw = raw.strip()
        if not raw.startswith("data: "):
            return None
        raw = raw[6:]
        if raw == "[DONE]":
            return None
        try:
            data = json.loads(raw)
        except Exception:
            return None
        u = data.get("usage")
        usage = (u.get("prompt_tokens", 0), u.get("completion_tokens", 0)) if u else None
        choices = data.get("choices") or [{}]
        delta = choices[0].get("delta", {})
        return {
            "text": delta.get("content", ""),
            "reasoning": delta.get("thinking", "") or delta.get("reasoning_content", ""),
            "tool_calls": delta.get("tool_calls"),
            "usage": usage,
            "done": False,
        }

    def _parse_round_tools(self, text: str, native_calls: list) -> list:
        if native_calls:
            return native_calls
        if self.tool_mode == "lfm2" and text.strip():
            calls = _parse_lfm2_tool_calls(text)
            if calls:
                return calls
        if text.strip():
            simple = _parse_simple_text_tools(text)
            if simple:
                return simple
            # Формат в стиле GLM/Spark:
            # SEARCH<arg_key>query</arg_key><arg_value>...</arg_value>
            xml_tag = (_parse_xml_tag_tool_calls(text)
                       or _parse_argkv_tool_calls(text))
            if xml_tag:
                return xml_tag
            return _parse_text_tool_calls(text)
        return []

    def _drop_round_draft(self) -> bool:
        # text/spark: черновик раунда с вызовом выбрасывается целиком;
        # lfm2/nanbeige оставляют вычищенный черновик частью итога.
        return self.tool_mode in ("text", "spark")

    def _append_tool_result_msg(self, name: str, content: str, args: dict):
        # Нативного tool-режима у llama.cpp-версии нет — результат всегда
        # user-сообщение с пометкой вызова (иначе модель не связывает
        # результат со своим вызовом и повторяет его).
        call_note = json.dumps(args, ensure_ascii=False)[:200]
        hdr = f"[Результат {name} ← {call_note}]"
        self.messages.append({
            "role": "user",
            "content": f"{hdr}:\n{content}{_TOOL_RESULT_NOTE}",
        })

    def _emit_finished(self, full_text: str, elapsed: float,
                       token_count: int, ttft: float):
        self.finished.emit(full_text, elapsed, token_count, ttft, self.messages)
