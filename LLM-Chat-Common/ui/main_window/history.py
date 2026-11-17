# ui/main_window/history.py
import json
from datetime import datetime
from pathlib import Path

from PyQt6.QtCore import Qt
from PyQt6.QtWidgets import QMessageBox, QListWidgetItem

from theme import get_palette as _P, get_theme, switch_theme, set_state
from i18n import _t, get_lang
from ui.widgets import confirm
from core.chat_store import ChatStore
from core.background_threads import TitleGenThread
from config import MAX_LOOP_ITER


class HistoryMixin:
    @staticmethod
    def _default_chat_title() -> str:
        """Безымянные «Новый чат» в списке неразличимы:
        дефолтный заголовок всегда несёт дату и время создания. Автозаголовок
        от модели (llama) его заменяет, как и раньше."""
        from datetime import datetime
        return f"{_t('default_chat_title')} · {datetime.now().strftime('%d.%m %H:%M')}"

    def _reset_token_usage(self):
        self.token_usage_label.setText(_t("token_usage_label", n=0, lim="—"))
        set_state(self.token_usage_label, None)

    def _new_chat(self):
        if self.conversation_history and not confirm(
            self, _t("dlg_new_chat_title"), _t("dlg_new_chat_body")
        ):
            return
        self._stop_generation()
        self._save_settings_and_history()
        self.current_chat_id = ChatStore.new_id()
        self.chat_title = self._default_chat_title()
        self.conversation_history = []
        self.chat_area.clear_chat()
        self._update_context_label()
        self._reset_token_usage()
        self._save_settings_and_history()
        self._refresh_chat_list()
        self.status_bar.setText(_t("status_new_chat"))

    def _update_context_label(self):
        n = len(self.conversation_history)
        self.context_label.setText(_t("context_label", n=n, lim=self.ctx_limit.value()))

    def _save_chat_to_store(self):
        if not self.conversation_history:
            return
        now = datetime.now().isoformat()
        chat_data = ChatStore.load_chat(self.current_chat_id)
        created = chat_data.get("created", now)
        ChatStore.save_chat(self.current_chat_id, {
            "id":                   self.current_chat_id,
            "title":                self.chat_title,
            "created":              created,
            "updated":              now,
            "conversation_history": self.conversation_history,
            "selected_model":       self.model_combo.currentText() or "",
        })
        chats = ChatStore.load_index()
        for c in chats:
            if c.get("id") == self.current_chat_id:
                c["title"] = self.chat_title
                c["updated"] = now
                break
        else:
            chats.append({
                "id": self.current_chat_id, "title": self.chat_title,
                "created": created, "updated": now,
            })
        chats.sort(key=lambda c: c.get("updated", ""), reverse=True)
        ChatStore.save_index(chats)

    def _refresh_chat_list(self):
        chats = ChatStore.load_index()
        self.history_list.clear()
        current_item = None
        for c in chats:
            title = c.get("title", _t("default_chat_title"))
            # старые безымянные чаты: показываем дату создания, чтобы
            # было понятно, что удалять, а что оставлять
            if title == _t("default_chat_title"):
                created = (c.get("created") or "").replace("T", " ")[:16]
                if created:
                    title = f"{title} · {created}"
            item = QListWidgetItem(title)
            item.setData(Qt.ItemDataRole.UserRole, c.get("id"))
            if c.get("id") == self.current_chat_id:
                f = item.font(); f.setBold(True); item.setFont(f)
                current_item = item
            self.history_list.addItem(item)
        # currentItem должен быть валиден ВСЕГДА: clear() его сбрасывал, и
        # «Удалить чат» молча умирал, пока пользователь не кликнул по
        # элементу повторно. Выделяем текущий чат.
        if current_item is not None:
            self.history_list.setCurrentItem(current_item)

    def _on_history_item_clicked(self, item):
        chat_id = item.data(Qt.ItemDataRole.UserRole)
        if not chat_id or chat_id == self.current_chat_id:
            return
        if self.worker and self.worker.isRunning():
            QMessageBox.information(self, _t("dlg_busy_title"), _t("dlg_busy_body"))
            return
        self._save_settings_and_history()
        self._load_chat_by_id(chat_id)

    def _load_chat_by_id(self, chat_id: str):
        chat_data = ChatStore.load_chat(chat_id)
        if not chat_data:
            self.status_bar.setText(_t("status_load_fail"))
            return
        self.current_chat_id = chat_id
        self.chat_title = chat_data.get("title", _t("default_chat_title"))
        self.conversation_history = chat_data.get("conversation_history", [])

        saved_model = chat_data.get("selected_model", "")
        if saved_model:
            idx = self.model_combo.findText(saved_model)
            if idx >= 0:
                self.model_combo.setCurrentIndex(idx)

        model_name = saved_model or self.model_combo.currentText() or "llama"
        self.chat_area.clear_chat()
        for idx, msg in enumerate(self.conversation_history):
            role    = msg.get("role")
            content = msg.get("content", "")
            files   = msg.get("files", [])
            if role == "user":
                self.chat_area.append_user(content, idx, files=files)
            elif role == "assistant":
                if content.strip().startswith((
                    "SEARCH:", "SCRAPE:", "READ_FILE:", "READ_PDF:",
                    "LINKS:", "META:", "SEARCHPAGE:", "SCRAPEMULTI:",
                    "MEMORY_WRITE:", "MEMORY_READ:", "MEMORY_DELETE:"
                )):
                    continue
                self.chat_area.append_assistant_message(content, model_name, idx)

        self._update_context_label()
        self._reset_token_usage()
        self.chat_area._do_scroll()
        self._refresh_chat_list()
        self.status_bar.setText(_t("status_chat_loaded", title=self.chat_title))

    def _delete_selected_chat(self):
        item = self.history_list.currentItem()
        if not item:
            self.status_bar.setText(_t("status_chat_not_selected"))
            return
        chat_id = item.data(Qt.ItemDataRole.UserRole)
        if not chat_id:
            return
        if not confirm(
            self, _t("dlg_delete_title"), _t("dlg_delete_body", name=item.text())
        ):
            return
        ChatStore.delete_chat(chat_id)
        chats = [c for c in ChatStore.load_index() if c.get("id") != chat_id]
        ChatStore.save_index(chats)
        if chat_id == self.current_chat_id:
            self.current_chat_id = ChatStore.new_id()
            self.chat_title = _t("default_chat_title")
            self.conversation_history = []
            self.chat_area.clear_chat()
            self._update_context_label()
            self._reset_token_usage()
        self._refresh_chat_list()
        self.status_bar.setText(_t("status_chat_deleted"))

    def _maybe_generate_title(self):
        # дефолтный заголовок теперь датированный («Новый чат · 16.11 20:30») —
        # проверяем ПРЕФИКС, а не точное равенство, иначе автозаголовок от
        # модели не сработал бы никогда
        if not self.chat_title.startswith(_t("default_chat_title")) or self._title_generating:
            return
        if not self.conversation_history:
            return
        first_user_msg = next(
            (m.get("content", "") for m in self.conversation_history
             if m.get("role") == "user" and m.get("content", "").strip()),
            ""
        )
        model_name = self.model_combo.currentText()
        if not first_user_msg or not model_name:
            return
        api_url = f"http://127.0.0.1:{self._server.port}/v1/chat/completions"
        self._title_generating = True
        self._title_gen = TitleGenThread(api_url, model_name, first_user_msg)
        self._title_gen.result.connect(self._on_title_generated, Qt.ConnectionType.QueuedConnection)
        self._title_gen.finished.connect(self._title_gen.deleteLater)
        self._title_gen.start()

    def _on_title_generated(self, title: str):
        self._title_generating = False
        self.chat_title = title or self._default_chat_title()
        self._save_chat_to_store()
        self._refresh_chat_list()

    def _clear_history(self):
        if confirm(self, _t("dlg_clear_title"), _t("dlg_clear_body")):
            self._stop_generation()
            old_id = self.current_chat_id
            self.chat_area.clear_chat()
            self.conversation_history = []
            self.chat_title = self._default_chat_title()
            self.current_chat_id = ChatStore.new_id()
            self._update_context_label()
            self._reset_token_usage()
            ChatStore.delete_chat(old_id)
            chats = [c for c in ChatStore.load_index() if c.get("id") != old_id]
            ChatStore.save_index(chats)
            self._save_settings_and_history()
            self._refresh_chat_list()
            self.status_bar.setText(_t("status_cleared"))

    def _save_settings_and_history(self, lang: str = None):
        # Preserve any pending lang override; default to current active lang
        if lang is None:
            if self.history_file.exists():
                try:
                    lang = json.loads(self.history_file.read_text(encoding="utf-8")).get("settings", {}).get("lang", get_lang())
                except Exception:
                    lang = get_lang()
            else:
                lang = get_lang()
        data = {
            "server_path":      self.server_dir,
            "model_dir":        self.model_dir,
            "selected_model":   self.model_combo.currentText(),
            "server_port":      self.server_port.value(),
            "server_threads":   self.server_threads.value(),
            "server_ngl":       self.server_ngl.value(),
            "server_np":        self.server_np.value(),
            "mtp_enabled":      self.mtp_enabled.isChecked(),
            "mtp_draft_n":      self.mtp_draft_n.value(),
            "mtp_draft_model":  self.mtp_draft_model.text(),
            "mtp_jinja":        self.mtp_jinja.isChecked(),
            "server_ctx":       self.server_ctx.value(),
            "max_tokens":       self.max_tokens.value(),
            "search_toggle":    self.search_toggle.isChecked(),
            "num_results":      self.num_results.value(),
            "show_thoughts":    self.show_thoughts.isChecked(),
            "loop_toggle":      self.loop_toggle.isChecked(),
            "loop_max_iter":    self.loop_max_iter.value(),
            "files_tool_toggle":  self.files_tool_toggle.isChecked(),
            "memory_tool_toggle": self.memory_tool_toggle.isChecked(),
            "write_tool_toggle":  self.write_tool_toggle.isChecked(),
            "terminal_tool_toggle": self.terminal_tool_toggle.isChecked(),
            "temperature":      self.temperature.value(),
            "top_p":            self.top_p.value(),
            "use_model_defaults": self.use_model_defaults.isChecked(),
            "num_ctx":            self.num_ctx_combo.currentData(),
            "ctx_limit":        self.ctx_limit.value(),
            "system_prompt":    self.system_prompt.toPlainText(),
            "theme":            get_theme(),
            "backend":          getattr(self, "backend", "llama"),
            "current_chat_id":  self.current_chat_id,
            "last_saved":       datetime.now().isoformat(),
            "settings":         {"lang": lang},
        }
        try:
            self.history_file.write_text(
                json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8"
            )
        except Exception as e:
            self.status_bar.setText(_t("status_save_error", e=e))
        self._save_chat_to_store()

    def _save_settings_and_history_with_lang(self, lang: str):
        self._save_settings_and_history(lang=lang)

    def _save_history_manual(self):
        self._save_settings_and_history()
        self.status_bar.setText(_t("status_history_saved"))

    def _restore_settings_and_history(self):
        if not self.history_file.exists():
            self.current_chat_id = ChatStore.new_id()
            return
        try:
            data = json.loads(self.history_file.read_text(encoding="utf-8"))

            self.server_dir = self._normalize_server_dir(data.get("server_path", ""))
            if self.server_dir:
                self.server_path_btn.setText(self._server_label())
                self.server_path_btn.setToolTip(self._server_exe_path())
            self.model_dir = data.get("model_dir", "")
            if self.model_dir:
                self.model_dir_btn.setText(Path(self.model_dir).name)
                self.model_dir_btn.setToolTip(self.model_dir)
                self._scan_models_folder()
            idx = self.model_combo.findText(data.get("selected_model", ""))
            if idx >= 0:
                self.model_combo.setCurrentIndex(idx)

            self.server_port.setValue(data.get("server_port", 8089))
            self.server_threads.setValue(data.get("server_threads", 4))
            self.server_ngl.setValue(data.get("server_ngl", 99))
            self.server_np.setValue(data.get("server_np", 1))
            self.mtp_enabled.setChecked(data.get("mtp_enabled", False))
            self.mtp_draft_n.setValue(data.get("mtp_draft_n", 2))
            self.mtp_draft_model.setText(data.get("mtp_draft_model", ""))
            self.mtp_jinja.setChecked(data.get("mtp_jinja", False))
            self.server_ctx.setValue(data.get("server_ctx", 4096))
            self.max_tokens.setValue(data.get("max_tokens", -1))
            self.search_toggle.setChecked(data.get("search_toggle", True))
            self.num_results.setValue(data.get("num_results", 5))
            self.show_thoughts.setChecked(data.get("show_thoughts", True))
            self.loop_toggle.setChecked(data.get("loop_toggle", False))
            self.loop_max_iter.setValue(data.get("loop_max_iter", MAX_LOOP_ITER))
            self.files_tool_toggle.setChecked(data.get("files_tool_toggle", True))
            self.memory_tool_toggle.setChecked(data.get("memory_tool_toggle", True))
            self.write_tool_toggle.setChecked(data.get("write_tool_toggle", True))
            # Дефолт True — как у остальных тумблеров тулов; состояние
            # сохраняется между сессиями (особенность этого проекта: в эталоне
            # LLM-Chat тумблеры не персистятся, здесь — персистятся все).
            self.terminal_tool_toggle.setChecked(data.get("terminal_tool_toggle", True))
            self.temperature.setValue(data.get("temperature", 0.7))
            self.top_p.setValue(data.get("top_p", 0.9))
            self.use_model_defaults.setChecked(data.get("use_model_defaults", False))
            saved_num_ctx = data.get("num_ctx", 16384)
            _nc_idx = self.num_ctx_combo.findData(saved_num_ctx)
            self.num_ctx_combo.setCurrentIndex(_nc_idx if _nc_idx >= 0 else 3)
            self.ctx_limit.setValue(data.get("ctx_limit", 40))
            self.system_prompt.setText(data.get("system_prompt", ""))

            switch_theme(data.get("theme", "dark"))
            self.retheme()          # фон окна и заголовок под сохранённую тему
            self._apply_theme_styles(_P())

            legacy_history  = data.get("conversation_history")
            stored_chat_id  = data.get("current_chat_id")

            if stored_chat_id:
                self.current_chat_id = stored_chat_id
                self._load_chat_by_id(stored_chat_id)
            elif legacy_history:
                self.current_chat_id = ChatStore.new_id()
                self.chat_title = self._default_chat_title()
                self.conversation_history = legacy_history
                self._save_chat_to_store()
                self._load_chat_by_id(self.current_chat_id)
                data["current_chat_id"] = self.current_chat_id
                data.pop("conversation_history", None)
                try:
                    self.history_file.write_text(
                        json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8"
                    )
                except Exception:
                    pass
            else:
                self.current_chat_id = ChatStore.new_id()
                data["current_chat_id"] = self.current_chat_id
                try:
                    self.history_file.write_text(
                        json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8"
                    )
                except Exception:
                    pass

        except Exception as e:
            print(f"Restore error: {e}")
            if not self.current_chat_id:
                self.current_chat_id = ChatStore.new_id()

