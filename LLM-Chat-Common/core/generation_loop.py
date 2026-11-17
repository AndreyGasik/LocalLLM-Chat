# LLM-Chat-Common/core/generation_loop.py
#
# ЕДИНЫЙ цикл генерации с инструментами для обоих бэкендов.
# Guard'ы «пустого ответа»/фейковых результатов живут здесь,
# а не в worker'ах бэкендов.
#
# Приложение наследует GenerationWorkerBase и реализует ХУКИ бэкенда:
#   _round_instruction()            — инструкция инструментов этого раунда
#   _prepare_request(instr)         → (url, payload) с live-историей
#   _post(url, payload)             → resp (стрим)
#   _parse_stream_line(line)        → dict|None {text, reasoning, tool_calls,
#                                       usage:(p,c)|None, done:bool}
#   _parse_round_tools(text, native)→ list[dict] вызовов
#   _drop_round_draft()             → bool (черновик раунда с вызовом — в мусор)
#   _append_tool_result_msg(...)    — результат в историю (формат бэкенда)
#   _emit_finished(...)             — сигнал finished (арность у версий разная)
#   _debug_prefix                   — имя дампов LLMCHAT_DEBUG
#
# Общий каркас держит: сигналы, Stop через разрыв соединения, display_gate,
# парсинг/исполнение тулов (ToolExecutorMixin), guard'ы «пустого ответа» и
# «фейкового результата», переспрос, счётчики токенов и статистику.
import json
import os
import threading
import time

from PyQt6.QtCore import QThread, pyqtSignal

from config import MAX_TOOL_ITER
from core.tool_parsing import (
    _clean_for_history, _strip_orphan_think, _strip_text_tool_call,
    _FAKE_RESULT_LINE_RE, _FAKE_RESULT_NUDGE, _KNOWN_TOOL_NAMES,
    _detect_tool_echo, ToolSyntaxGate,
)
from core.tool_exec import ToolExecutorMixin


def _dbg_write(name: str, text: str):
    """Отладка: при LLMCHAT_DEBUG=1 дописывает в /tmp/<name> то, что реально
    ушло в бэкенд (payload) и что реально пришло (сырые строки стрима)."""
    try:
        with open(f"/tmp/{name}", "a", encoding="utf-8") as f:
            f.write(text)
    except Exception:
        pass


# Служебная подсказка для повторного запроса после «пустого» ответа модели.
_EMPTY_ANSWER_NUDGE = (
    "[Служебное] Твой предыдущий ответ не содержал ни текста для пользователя, "
    "ни распознанного вызова инструмента — скорее всего, вызов был в "
    "неподдерживаемом формате или внутри блока размышлений. "
    "Ответь текстом; если нужна команда — выведи вызов ВНЕ блока размышлений "
    "отдельной строкой, например:\nEXEC_CMD: uname -r"
)

_MAX_TOOL_RESULT = 12000


class GenerationWorkerBase(QThread, ToolExecutorMixin):
    """Базовый worker: общий каркас раундов генерации с инструментами.
    Конкретный протокол (Ollama / llama.cpp) — в реализациях хуков."""

    new_chunk     = pyqtSignal(str)
    thought_chunk = pyqtSignal(str)
    round_start   = pyqtSignal()
    clear_stream  = pyqtSignal(str)
    tool_called   = pyqtSignal(str, str)
    tool_result   = pyqtSignal(str, str)
    file_ready    = pyqtSignal(str, str)
    first_token   = pyqtSignal(float)
    usage         = pyqtSignal(int, int)  # prompt_tokens, completion_tokens
    error         = pyqtSignal(str)
    # finished ОПРЕДЕЛЯЕТСЯ В ПОДКЛАССАХ: у Ollama арность (str,float,int,float),
    # у llama.cpp — (str,float,int,float,list) — chat_io обеих версий не трогаем.

    _debug_prefix = "llmchat"

    def __init__(self, *, history, use_search, scraper, num_results=5,
                 default_time_range="none", memory=None, tool_mode="text",
                 memory_intent=False, enable_file_tools=True,
                 enable_memory_tools=True, enable_write_tools=True,
                 enable_terminal_tool=False):
        super().__init__()
        # Живая история диалога: worker'ы мутируют её tool-раундами, а
        # chat_io читает после завершения (Ollama — через worker.messages).
        self.messages = list(history)
        self.use_search = use_search
        self.search_enabled = use_search          # алиас для смешанных обращений
        self.num_results = num_results
        self.num_res = num_results                # алиас (Llama-имя)
        self.default_time_range = default_time_range
        self.scraper = scraper
        self.memory = memory
        self.tool_mode = tool_mode
        self.memory_intent = memory_intent
        self.enable_file_tools = enable_file_tools
        self.enable_memory_tools = enable_memory_tools
        self.enable_write_tools = enable_write_tools
        # Дефолт False на уровне API: UI всегда передаёт значение тумблера
        # явно. Выполнение команд на машине — самый рискованный инструмент,
        # поэтому сознательное включение — на стороне вызывающего.
        self.enable_terminal_tool = enable_terminal_tool
        self._running = True
        self._resp = None
        self._resp_lock = threading.Lock()

    def stop(self):
        # Просто выставить флаг недостаточно: пока поток стоит внутри
        # блокирующего post()/iter_lines() (ждёт данные от бэкенда), флаг
        # никто не проверяет. Поэтому дополнительно рвём соединение — это
        # почти мгновенно поднимает исключение внутри заблокированного
        # чтения и разом останавливает и клиентский поток, и генерацию
        # на стороне сервера (сервер видит разрыв и прекращает досчитывать).
        self._running = False
        with self._resp_lock:
            resp = self._resp
        if resp is not None:
            try:
                resp.raw.close()
            except Exception:
                pass
            try:
                resp.close()
            except Exception:
                pass

    # ── Хуки бэкенда (реализуются в подклассах) ────────────────────────
    def _round_instruction(self) -> str:
        raise NotImplementedError

    def _prepare_request(self, instr: str):
        """→ (url, request_payload). Request_payload["messages"] должен
        ссылаться на self.messages (живая история)."""
        raise NotImplementedError

    def _post(self, url: str, payload: dict):
        raise NotImplementedError

    def _parse_stream_line(self, line) -> dict | None:
        raise NotImplementedError

    def _parse_round_tools(self, text: str, native_calls: list) -> list:
        raise NotImplementedError

    def _drop_round_draft(self) -> bool:
        """Черновик текста раунда с вызовом инструмента выбрасывается целиком
        (текстовый режим) — или сохраняется вычищенным (lfm2/nanbeige)."""
        raise NotImplementedError

    def _append_tool_result_msg(self, name: str, content: str, args: dict):
        raise NotImplementedError

    def _emit_finished(self, full_text: str, elapsed: float,
                       token_count: int, ttft: float):
        raise NotImplementedError

    # ── Общий каркас раундов ────────────────────────────────────────────
    def run(self):
        try:
            full_text    = ""
            session_start = time.time()   # время ВСЕЙ сессии (все раунды)
            token_count  = 0
            ttft         = 0.0
            prompt_tokens = 0
            completion_tokens = 0
            executed_calls: set = set()   # (имя, аргументы) выполненных вызовов
            # Однократный повторный запрос после «пустого»/фейкового ответа.
            empty_retry_done = False

            for _ in range(MAX_TOOL_ITER):
                if not self._running:
                    break
                self.round_start.emit()
                # ВАЖНО: start/first_token_sent обнуляются на КАЖДЫЙ раунд.
                # Раньше first_token_sent не сбрасывался между раундами —
                # TTFT последнего раунда накапливал время всех предыдущих
                # (тул-вызовы, повторные прогоны промпта) — см. Errors.txt.
                start = time.time()
                first_token_sent = False
                # Косметический фильтр live-стрима: не даёт мелькнуть в чате
                # сырым синтаксисом текстовых tool-call'ов (SEARCH:,
                # <tool_call>…</tool_call>) в момент, когда модель их
                # печатает — только показ, на разбор не влияет.
                display_gate = ToolSyntaxGate()
                accumulated = ""      # видимый контент раунда
                native_calls = []     # нативные tool_calls из стрима

                instr = self._round_instruction()
                url, request_payload = self._prepare_request(instr)

                dbg_lines = [] if os.environ.get("LLMCHAT_DEBUG") else None
                if dbg_lines is not None:
                    _dbg_write(f"{self._debug_prefix}_payload.json",
                               f"\n===== {time.strftime('%H:%M:%S')} =====\n"
                               + json.dumps(request_payload, ensure_ascii=False, indent=2))
                resp = self._post(url, request_payload)
                with self._resp_lock:
                    self._resp = resp
                if not self._running:
                    # stop() мог прийти между post() и этой строкой —
                    # соединение уже закрыто, просто выходим.
                    break
                resp.raise_for_status()

                done_flag = False
                for line in resp.iter_lines():
                    if not self._running:
                        break
                    if not line:
                        continue
                    if dbg_lines is not None:
                        dbg_lines.append(line.decode("utf-8", "replace")
                                         if isinstance(line, bytes) else str(line))
                    ev = self._parse_stream_line(line)
                    if not ev:
                        continue

                    tc = ev.get("tool_calls")
                    if tc:
                        native_calls.extend(tc)

                    thinking = ev.get("reasoning") or ""
                    if thinking:
                        # TTFT — время до ПЕРВОГО токена вообще (в т.ч. «мыслей»);
                        # у долго думающих моделей иначе TTFT включал размышление.
                        if not first_token_sent:
                            ttft = time.time() - start
                            self.first_token.emit(ttft)
                            first_token_sent = True
                        self.thought_chunk.emit(thinking)
                        # Токены «мыслей» тоже реально сгенерированы и занимают
                        # время — иначе tok/s завышался (см. Errors.txt).
                        token_count += 1

                    chunk = ev.get("text") or ""
                    if chunk:
                        if not first_token_sent:
                            ttft = time.time() - start
                            self.first_token.emit(ttft)
                            first_token_sent = True
                        token_count += 1
                        accumulated += chunk
                        visible = display_gate.feed(chunk)
                        if visible:
                            self.new_chunk.emit(visible)

                    usage = ev.get("usage")
                    if usage:
                        prompt_tokens, completion_tokens = usage

                    if ev.get("done"):
                        done_flag = True
                        break

                with self._resp_lock:
                    self._resp = None
                if dbg_lines is not None:
                    _dbg_write(f"{self._debug_prefix}_stream.jsonl",
                               f"\n===== {time.strftime('%H:%M:%S')} =====\n"
                               + "\n".join(dbg_lines))
                if not self._running:
                    break

                # Хвост display_gate: негнёвый кусок маркера, оставшийся в
                # буфере, — вывести, чтобы ничего не терялось молча.
                tail = display_gate.flush()
                if tail:
                    self.new_chunk.emit(tail)

                tool_calls = self._parse_round_tools(accumulated, native_calls)
                tool_calls = [tc for tc in tool_calls
                              if tc.get("function", {}).get("name") in _KNOWN_TOOL_NAMES]

                # ── Текст раунда: чистка, фейк-фильтр, история/видимость ──
                _fake_round = False
                if not tool_calls and accumulated.strip():
                    cleaned = _clean_for_history(_strip_text_tool_call(accumulated))
                    cleaned = _strip_orphan_think(cleaned)
                    _fake_round = bool(_FAKE_RESULT_LINE_RE.search(cleaned))
                    if _fake_round:
                        # Модель сама «получила результат», не вызывая
                        # инструмент — строку фейка в чат и в историю не пускаем.
                        cleaned = _FAKE_RESULT_LINE_RE.sub("", cleaned)
                    if cleaned != accumulated or display_gate.suppressed_any:
                        self.clear_stream.emit(cleaned)
                    self.messages.append({"role": "assistant", "content": cleaned})
                    full_text += cleaned
                elif tool_calls:
                    draft = self._drop_round_draft()
                    if not draft and accumulated.strip():
                        # lfm2/nanbeige: черновой текст раунда остаётся частью
                        # итога — но ВЫЧИЩЕННЫМ от синтаксиса вызова.
                        pre_tag = accumulated.replace('&lt;', '<').replace('&gt;', '>')
                        cleaned = _strip_text_tool_call(pre_tag)
                        cleaned = _clean_for_history(cleaned)
                        # Предохранитель: если чистка съела почти всё, а эха
                        # вызова в тексте не было — вероятно, зацепили часть
                        # настоящего ответа; откатываемся на сырой текст.
                        echo = _detect_tool_echo(pre_tag)
                        if (pre_tag and not echo
                                and len(cleaned) < 0.4 * len(pre_tag)):
                            cleaned = pre_tag
                        self.clear_stream.emit(cleaned)
                        self.messages.append({"role": "assistant", "content": cleaned})
                        full_text += cleaned
                    else:
                        # Текстовый режим: весь текст раунда с вызовом
                        # (часто неверный черновик ДО результата) не показываем
                        # и не сохраняем — иначе пользователь видит два
                        # противоречащих ответа подряд.
                        self.clear_stream.emit("")

                # ── Нет вызовов: guard'ы пустого/фейкового ответа ──────────
                if not tool_calls:
                    visible = accumulated.strip()
                    if ((not visible) or _fake_round) and not empty_retry_done \
                            and self._running:
                        empty_retry_done = True
                        # Один раз переспрашиваем с подсказкой, иначе
                        # пользователь видит пустое/выдуманное сообщение
                        # (вызов внутри блока размышлений, unsupported формат,
                        # самодельный «[Результат …]» — диагностика LFM3, ноябрь
                        # 2026: модель имитировала вывод date, не вызывая EXEC_CMD).
                        self.messages.append({"role": "user", "content": (
                            _FAKE_RESULT_NUDGE if _fake_round
                            else _EMPTY_ANSWER_NUDGE)})
                        continue
                    break

                # ── Исполнение вызовов (общий миксин) ──────────────────────
                for tc in tool_calls:
                    func = tc.get("function", {})
                    name = func.get("name", "")
                    args = func.get("arguments", {})
                    if isinstance(args, str):
                        try:
                            args = json.loads(args)
                        except Exception:
                            args = {}

                    # Предохранитель повторов: один и тот же вызов (имя +
                    # аргументы) за один ответ не выполняется дважды — слабые
                    # модели зацикливаются на поиске, хотя результат уже в
                    # диалоге. memory_read не считается повтором: между
                    # вызовами память могла измениться.
                    _sig = (name, json.dumps(args, sort_keys=True, ensure_ascii=False))
                    _is_repeat = (name != "memory_read" and _sig in executed_calls)
                    executed_calls.add(_sig)

                    if _is_repeat:
                        self.tool_called.emit(name, "(повтор)")
                        result = (
                            "Этот вызов уже выполнялся в этом ответе, его результат есть "
                            "выше в диалоге. Не повторяй его: используй уже полученные "
                            "данные и ответь пользователю."
                        )
                        self.tool_result.emit("Повторный вызов пропущен", result)
                    else:
                        result = self._exec_tool(name, args, executed_calls)

                    self._append_tool_result_msg(name, result, args)

                # Следующий раунд: результат уже в истории (каждый раунд
                # _prepare_request перезаякоривает payload["messages"]),
                # модель отвечает или вызывает следующий инструмент.

            # ── Страховка после цикла: даже после переспроса не осталось
            # ни текста, ни выполненных вызовов — объясняем, а не молчим.
            full_text = _FAKE_RESULT_LINE_RE.sub("", full_text)
            if self._running and not full_text.strip():
                full_text = (
                    "Модель не вернула текст ответа (её вызов инструмента не удалось "
                    "распознать — возможно, он был в блоке размышлений или в "
                    "неподдерживаемом формате). Попробуйте переформулировать запрос; "
                    "для диагностики запустите чат с переменной окружения "
                    f"LLMCHAT_DEBUG=1 — сырой вывод модели попадёт в "
                    f"/tmp/{self._debug_prefix}_stream.jsonl."
                )

            elapsed = time.time() - session_start
            if self._running:
                if prompt_tokens or completion_tokens:
                    self.usage.emit(prompt_tokens, completion_tokens)
                self._emit_finished(full_text, elapsed, token_count, ttft)
            else:
                self.error.emit("Остановлено пользователем")

        except Exception as e:
            self.error.emit(str(e))

