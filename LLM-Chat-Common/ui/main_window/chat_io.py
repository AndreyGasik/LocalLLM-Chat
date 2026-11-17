# ui/main_window/chat_io.py
import time

from PyQt6.QtWidgets import QMessageBox, QApplication

from i18n import _t, get_lang
from theme import set_state
from core.worker import LlamaWorker
from core.api_messages import _build_api_messages
from core.memory_db import _wants_memory_tool
from core.tool_parsing import _is_lfm2_model, _is_spark_model
from core.model_profiles.nanbeige import is_nanbeige_model, nanbeige_payload_overrides
from core.model_profiles.spark import is_spark_model, spark_payload_overrides


class ChatIOMixin:
    def _send_message(self, override_text: str = None, override_files: list = None):
        msg   = override_text  if override_text  is not None else self.input_field.toPlainText().strip()
        files = override_files if override_files is not None else list(self._pending_files)

        if not msg and not files:
            return

        # Для llama.cpp: сервер должен быть запущен; для Ollama — сервис
        # работает независимо (проверка через /api/tags в _load_models).
        if getattr(self, "backend", "llama") == "llama":
            if not self._server.is_running():
                QMessageBox.warning(self, _t("server_not_running"),
                    "Сначала запустите llama-server." if get_lang() == "ru"
                    else "Please start llama-server first.")
                return
        if not (self.model_combo.currentText() or "").strip():
            return

        user_idx = len(self.conversation_history)
        self.conversation_history.append({"role": "user", "content": msg, "files": files})
        self.chat_area.append_user(msg, user_idx, files)

        if override_text is None:
            self.input_field.clear()
            self._clear_file_chips()

        self._update_context_label()

        if getattr(self, "loop_toggle", None) is not None and self.loop_toggle.isChecked():
            self._start_loop(msg)
        else:
            self._start_worker(memory_intent=_wants_memory_tool(msg))

    def _start_worker(self, override_messages=None, force_search=False,
                       badge_override=None, extra_system=None, memory_intent=False):
        """Общий запуск LlamaWorker. Раньше это было тело _send_message —
        вынесено в отдельный метод (по образцу _start_worker_with_cache в
        эталоне), чтобы им же могли пользоваться разовая проверка ответа
        (ActionsMixin._on_verify_answer) и цикл "решить-проверить-повторить"
        (LoopMixin), не дублируя сборку payload/подключение сигналов."""
        if self.worker and self.worker.isRunning():
            return

        self._backend = getattr(self, "backend", "llama")
        if self._backend == "llama":
            # Порт берём у самого LlamaServerManager (реально запущенного
            # процесса), а не у self.server_port.value() — если пользователь
            # покрутил спинбокс порта уже ПОСЛЕ запуска сервера, но ДО его
            # перезапуска, значение в виджете и реальный порт сервера разойдутся.
            api_url = f"http://127.0.0.1:{self._server.port}/v1/chat/completions"
            if not self._server.is_running():
                QMessageBox.warning(self, _t("server_not_running"),
                    "Сначала запустите llama-server." if get_lang() == "ru"
                    else "Please start llama-server first.")
                return
        else:
            api_url = ""   # Ollama Worker строит URL из config

        use_search = force_search or self.search_toggle.isChecked()

        base_sys = self.system_prompt.toPlainText().strip() or (
            "Ты полезный ИИ-ассистент." if get_lang() == "ru" else "You are a helpful AI assistant."
        )
        full_sys = f"{base_sys}\n\n{extra_system}" if extra_system else base_sys

        # override_messages используется только разовой проверкой ответа и
        # циклом — это НЕ полная история чата, а отдельный служебный запрос
        # (система+вопрос+предыдущий ответ на проверку, либо система+условие
        # задачи со skill-инструкцией). self._override_active сигнализирует
        # _on_finished, что результат нужно ДОБАВИТЬ отдельным сообщением
        # бота, а не подменять им всю conversation_history.
        if override_messages is not None:
            msgs = override_messages
            self._override_active = True
        else:
            msgs = _build_api_messages(
                self.conversation_history, self.ctx_limit.value(), full_sys,
                read_files_directly=not use_search
            )
            self._override_active = False

        payload = {
            "messages":    msgs,
            "temperature": self.temperature.value(),
            "top_p":       self.top_p.value(),
            "stream":      True,
        }

        bot_msg_index = len(self.conversation_history)
        self.chat_area.set_show_thoughts(self.show_thoughts.isChecked())
        self.chat_area.start_bot_response(
            self.model_combo.currentText() or "llama",
            use_search,
            bot_msg_index,
            badge_override
        )
        self._token_count = 0
        self._start_time  = time.time()
        self._set_busy()

        model_name = self.model_combo.currentText() or "llama"
        if _is_lfm2_model(model_name):
            tool_mode = "lfm2"
        elif is_nanbeige_model(model_name):
            tool_mode = "nanbeige"
            # Пресеты из карточки модели (temperature/top_p/top_k/max_tokens),
            # разные для агентных сценариев (когда включены тулы) и для
            # чистого рассуждения — см. core/model_profiles/nanbeige.py.
            # Подменяют значения из слайдеров UI только для этой модели.
            payload.update(nanbeige_payload_overrides(use_search))
        elif is_spark_model(model_name):
            # Текстовый режим, но инструкция — в родном для Spark формате
            # <tool_call>имя<arg_key>..</arg_key><arg_value>..</arg_value></tool_call>
            # (см. core/model_profiles/spark.py). repeat_penalty=1.0 — по
            # карточке модели, иначе портятся закрывающие теги вызова.
            tool_mode = "spark"
            payload.update(spark_payload_overrides())
        else:
            tool_mode = "text"

        self._backend = getattr(self, "backend", "llama")
        if self._backend == "ollama":
            # ── Ollama Worker ───────────────────────────────────────────
            if override_messages is None:
                msgs = _build_api_messages(
                    self.conversation_history, self.ctx_limit.value(), full_sys,
                    read_files_directly=not use_search, native_tool_messages=True
                )
            self._connect_ollama_worker(msgs, use_search, memory_intent)
            return

        # ── llama.cpp Worker ────────────────────────────────────────────
        self.worker = LlamaWorker(
            api_url        = api_url,
            payload        = payload,
            search_enabled = use_search,
            num_res        = self.num_results.value(),
            scraper        = self.scraper,
            max_tokens_val = self.max_tokens.value(),
            memory         = self.memory,
            tool_mode      = tool_mode,
            memory_intent  = memory_intent,
            enable_file_tools   = self.files_tool_toggle.isChecked(),
            enable_memory_tools = self.memory_tool_toggle.isChecked(),
            enable_write_tools  = self.write_tool_toggle.isChecked(),
            enable_terminal_tool = self.terminal_tool_toggle.isChecked(),
        )
        self.worker.new_chunk.connect(self._on_chunk)
        self.worker.thought_chunk.connect(self.chat_area.append_thought_chunk)
        self.worker.first_token.connect(lambda t: setattr(self, "_ttft", t))
        self.worker.round_start.connect(self.chat_area.mark_round_start)
        self.worker.tool_called.connect(self.chat_area.append_tool_call)
        self.worker.tool_result.connect(self.chat_area.append_tool_result)
        self.worker.file_ready.connect(self.chat_area.append_result_file)
        self.worker.usage.connect(self._on_usage)
        self.worker.clear_stream.connect(self.chat_area.trim_stream_to_round)
        self.worker.finished.connect(self._on_finished)
        self.worker.error.connect(self._on_error)
        self.worker.start()

    def _on_chunk(self, chunk: str):
        self._token_count += 1
        elapsed = time.time() - self._start_time
        speed   = self._token_count / elapsed if elapsed > 0 else 0
        self.rt_status.setText(f"⚡ {self._token_count} tk • {speed:.1f} tok/s")
        self.chat_area.append_chunk(chunk)

    def _on_usage(self, prompt_tokens: int, completion_tokens: int):
        ctx  = self._server.ctx
        lim  = str(ctx) if ctx else "?"
        used = prompt_tokens + completion_tokens
        self.token_usage_label.setText(_t("token_usage_label", n=used, lim=lim))
        if ctx and used >= ctx * 0.9:
            set_state(self.token_usage_label, "bad")
        else:
            set_state(self.token_usage_label, None)

    def _on_finished(self, text: str, elapsed: float, tokens: int, ttft: float, full_messages: list):
        if getattr(self, "_override_active", False):
            # Разовая проверка / раунд цикла: full_messages — это служебный
            # мини-диалог (system+user[+assistant]), а не вся история чата,
            # поэтому conversation_history НЕ подменяем целиком — добавляем
            # только финальный ответ модели отдельным сообщением бота.
            self.conversation_history.append({"role": "assistant", "content": text})
        else:
            self.conversation_history = [
                m for m in full_messages if m.get("role") != "system"
            ]
        speed = tokens / elapsed if elapsed > 0 else 0
        self.chat_area.finish_response(elapsed, tokens, speed, ttft)
        self._update_context_label()
        self._set_idle(_t("status_done", t=elapsed, tok=tokens, spd=speed))
        self.rt_status.setText("")
        self._save_settings_and_history()
        self._maybe_generate_title()
        self._refresh_chat_list()
        self.input_field.setFocus()
        self.worker = None
        if getattr(self, "_loop_active", False):
            self._loop_after_finished(text)

    def _on_error(self, err: str):
        self.chat_area._flush_buffers()
        self.chat_area.finish_response(0, 0, 0, 0)
        self.chat_area.append_error(err)
        self._set_idle(_t("status_err", e=err))
        self.worker = None
        self._override_active = False
        if getattr(self, "_loop_active", False) and getattr(self, "loop_toggle", None) is not None:
            self.loop_toggle.setEnabled(True)
        self._loop_active = False

    def _stop_generation(self):
        """Просит воркер остановиться. Раньше здесь безусловно делалось
        self.worker = None сразу после wait(500) — если поток не успевал
        завершиться за эти 500мс (например, сеть подвисла на чтении
        стрима), Python терял последнюю ссылку на ещё РЕАЛЬНО работающий
        QThread. PyQt в такой ситуации может грохнуть приложение с
        "QThread: Destroyed while thread is still running". Теперь, если
        поток не остановился вовремя, self.worker НЕ обнуляется здесь —
        обнуление произойдёт естественным путём в _on_finished/_on_error,
        когда поток реально пришлёт сигнал finished/error."""
        if self.worker and self.worker.isRunning():
            self.worker.stop()
            if self.worker.wait(2000):
                self.worker = None
        self._override_active = False
        if getattr(self, "_loop_active", False):
            self._loop_active = False
            if getattr(self, "loop_toggle", None) is not None:
                self.loop_toggle.setEnabled(True)
        self._set_idle(_t("status_stopped"))

    def _set_busy(self):
        self.send_btn.setEnabled(False)
        self.file_btn.setEnabled(False)
        self.stop_btn.setEnabled(True)
        self.input_field.setEnabled(False)
        self.status_bar.setText(_t("status_thinking"))

    def _set_idle(self, status: str = None):
        self.send_btn.setEnabled(True)
        self.file_btn.setEnabled(True)
        self.stop_btn.setEnabled(False)
        self.input_field.setEnabled(True)
        self.status_bar.setText(status if status is not None else _t("status_ready"))

    def _on_copy(self, text: str):
        QApplication.instance().clipboard().setText(text)
        self.status_bar.setText(_t("status_copied"))

    def _on_regen(self, msg_index: int):
        if self.worker and self.worker.isRunning():
            return
        self.conversation_history = self.conversation_history[:msg_index]
        self.chat_area.remove_from_index(msg_index)
        self._update_context_label()
        if self.conversation_history:
            last = self.conversation_history[-1]
            if last.get("role") == "user":
                msg = last.get("content", "")
                files = last.get("files", [])
                self.conversation_history = self.conversation_history[:-1]
                self.chat_area.remove_from_index(msg_index - 1)
                self._send_message(override_text=msg, override_files=files)

    def _on_edit(self, msg_index: int, text: str):
        if self.worker and self.worker.isRunning(): return
        self.conversation_history = self.conversation_history[:msg_index]
        self.chat_area.remove_from_index(msg_index)
        self._update_context_label()
        self.input_field.setPlainText(text)
        self.input_field.setFocus()
        cursor = self.input_field.textCursor()
        cursor.movePosition(cursor.MoveOperation.End)
        self.input_field.setTextCursor(cursor)
        self.status_bar.setText(_t("status_editing"))

    def _on_resend(self, msg_index: int):
        if self.worker and self.worker.isRunning(): return
        if msg_index >= len(self.conversation_history): return
        msg   = self.conversation_history[msg_index].get("content", "")
        files = self.conversation_history[msg_index].get("files", [])
        self.conversation_history = self.conversation_history[:msg_index]
        self.chat_area.remove_from_index(msg_index)
        self._update_context_label()
        self._send_message(override_text=msg, override_files=files)

    def _connect_ollama_worker(self, msgs, use_search, memory_intent):
        """Запуск Ollama Worker (нативные tool-сообщения, tool_check).

        Вызывается ИЗ _start_worker, который УЖЕ показал бабл ответа
        (start_bot_response), сбросил счётчики и включил busy — здесь это
        повторять нельзя: раньше дубль приводил к ДВУМ бабблам «Думаю…»
        на каждый Ollama-запрос (см. скриншот пользователя 2026-11-16)."""
        from core.worker import Worker as OllamaWorker
        model = self.model_combo.currentText() or "llama"
        enable_files = self.files_tool_toggle.isChecked()
        enable_memory = self.memory_tool_toggle.isChecked()
        enable_write = self.write_tool_toggle.isChecked()
        enable_terminal = self.terminal_tool_toggle.isChecked()

        self._worker_initial_msg_len = len(msgs)

        if getattr(self, "use_model_defaults", None) is not None and self.use_model_defaults.isChecked():
            temp = None
            top_p_val = None
        else:
            temp = self.temperature.value()
            top_p_val = self.top_p.value()

        self.worker = OllamaWorker(
            model=model, messages=msgs, temperature=temp, top_p=top_p_val,
            num_ctx=getattr(self, "num_ctx", None),
            use_search=use_search, scraper=self.scraper,
            native_tools_allowed=True, num_results=self.num_results.value(),
            default_time_range="week", memory=self.memory,
            tool_mode=("lfm2" if _is_lfm2_model(model) else
                       "spark" if _is_spark_model(model) else "text"),
            enable_file_tools=enable_files, enable_memory_tools=enable_memory,
            enable_write_tools=enable_write,
            enable_terminal_tool=enable_terminal, memory_intent=memory_intent,
        )
        qt = __import__("PyQt6.QtCore", fromlist=["Qt"]).Qt
        CT = qt.ConnectionType.QueuedConnection
        self.worker.new_chunk.connect(self._on_chunk, CT)
        self.worker.thought_chunk.connect(self.chat_area.append_thought_chunk, CT)
        self.worker.round_start.connect(self.chat_area.mark_round_start, CT)
        self.worker.clear_stream.connect(self.chat_area.trim_stream_to_round, CT)
        self.worker.first_token.connect(lambda t: setattr(self, "_ttft", t), CT)
        self.worker.usage.connect(self._on_usage, CT)
        self.worker.tool_called.connect(self.chat_area.append_tool_call, CT)
        self.worker.tool_result.connect(self.chat_area.append_tool_result, CT)
        self.worker.file_ready.connect(self.chat_area.append_result_file, CT)
        self.worker.finished.connect(self._on_finished_ollama, CT)
        self.worker.error.connect(self._on_error, CT)
        self.worker.start()

    def _on_finished_ollama(self, text: str, elapsed: float, tokens: int, ttft: float):
        """Финал для Ollama: история расширяется из worker.messages
        (общая семантика с unified base — оба бэкенда хранят её в .messages)."""
        speed = tokens / elapsed if elapsed > 0 else 0
        self.chat_area.finish_response(elapsed, tokens, speed, ttft)
        if self.worker:
            new_msgs = self.worker.messages[getattr(self, "_worker_initial_msg_len", 0):]
            self.conversation_history.extend(new_msgs)
            self._update_context_label()
            self._set_idle(_t("status_done", t=elapsed, tok=tokens, spd=speed))
            self.rt_status.setText("")
            self._save_settings_and_history()
            self._maybe_generate_title()
            self._refresh_chat_list()
            self.input_field.setFocus()
            self.worker = None
            if getattr(self, "_loop_active", False):
                self._loop_after_finished(text)
