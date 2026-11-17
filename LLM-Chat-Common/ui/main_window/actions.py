# ui/main_window/actions.py
from pathlib import Path

from PyQt6.QtWidgets import QFileDialog, QMessageBox
from PyQt6.QtCore import Qt

from i18n import _t, get_lang
from theme import set_state
from ui.widgets import FileChip
from ui.dialogs.memory_dialog import MemoryDialog
from core.background_threads import SearxngCheckThread, ModelLoaderThread
from core.skills import load_skill


class ActionsMixin:
    def _attach_file(self):
        path, _ = QFileDialog.getOpenFileName(
            self, _t("dlg_attach_title"), "",
            "All files (*);;"
            "PDF (*.pdf);;"
            "Text / Code (*.txt *.py *.sh *.fish *.md *.json *.yaml *.toml "
            "*.js *.ts *.cpp *.c *.h);;"
        )
        if not path or path in self._pending_files: return
        self._pending_files.append(path)
        chip = FileChip(path)
        chip.removed.connect(self._remove_file_chip)
        self.chips_layout.addWidget(chip)
        self.chips_panel.setVisible(True)

    def _remove_file_chip(self, path: str):
        if path in self._pending_files:
            self._pending_files.remove(path)
        for i in range(self.chips_layout.count()):
            item = self.chips_layout.itemAt(i)
            if item and item.widget() and isinstance(item.widget(), FileChip):
                if item.widget().path == path:
                    self.chips_layout.takeAt(i).widget().deleteLater()
                    break
        self.chips_panel.setVisible(bool(self._pending_files))

    def _clear_file_chips(self):
        self._pending_files = []
        for i in reversed(range(self.chips_layout.count())):
            item = self.chips_layout.takeAt(i)
            if item and item.widget():
                item.widget().deleteLater()
        self.chips_panel.setVisible(False)

    def _export_txt(self):
        path, _ = QFileDialog.getSaveFileName(
            self, _t("dlg_export_title"),
            str(Path.home() / "chat_export.txt"), _t("dlg_export_filter")
        )
        if not path:
            return
        try:
            Path(path).write_text(self.chat_area.toPlainText(), encoding="utf-8")
            self.status_bar.setText(_t("status_export", path=path))
        except Exception as e:
            QMessageBox.warning(self, _t("dlg_error_title"), str(e))


    def _show_memory(self):
        # Диалог памяти вынесен в отдельный класс
        # ui/dialogs/memory_dialog.py::MemoryDialog.
        dlg = MemoryDialog(self.memory, parent=self)
        dlg.exec()
    def _check_searxng(self):
        self.searxng_label.setText(_t("searxng_checking"))
        set_state(self.searxng_label, None)
        self._searxng_checker = SearxngCheckThread()
        self._searxng_checker.result.connect(self._on_searxng_result, Qt.ConnectionType.QueuedConnection)
        self._searxng_checker.finished.connect(self._searxng_checker.deleteLater)
        self._searxng_checker.start()

    def _on_searxng_result(self, ok):
        if ok:
            self.searxng_label.setText(_t("searxng_ok"))
            set_state(self.searxng_label, "ok")
        else:
            self.searxng_label.setText(_t("searxng_fail"))
            set_state(self.searxng_label, "bad")
            self.search_toggle.setChecked(False)

    def _on_verify_answer(self, msg_index: int, answer_text: str):
        # Разовая проверка одного конкретного ответа: ничего не удаляет и
        # не переписывает — результат добавляется отдельным новым
        # сообщением бота, как обычный ответ. Никакого автотриггера и
        # каскадных "проверок проверки": функция вызывается только по
        # явному клику на кнопку 🔍 у конкретного баббла.
        #
        # В отличие от эталона, здесь нет self.tool_support_cache/
        # ToolCheckThread — Llama не определяет "нативную" поддержку тулов
        # у модели (это Ollama-специфичная проверка), поэтому запускаем
        # _start_worker сразу, без промежуточного асинхронного шага.
        #
        # Текст ответа приходит напрямую от баббла (self._plain_text), тем
        # же путём, что и у ✏️ edit / 📋 copy — а не через
        # conversation_history[msg_index], где при наличии вызовов
        # инструментов (search и т.п.) на этом индексе может лежать
        # пустой промежуточный assistant-фрагмент, а не финальный текст.
        if self.worker and self.worker.isRunning():
            return
        if msg_index < 0 or msg_index >= len(self.conversation_history):
            return

        answer_text = (answer_text or "").strip()
        if not answer_text:
            self.status_bar.setText(_t("status_nothing_to_verify"))
            return

        question_text = ""
        for i in range(msg_index - 1, -1, -1):
            entry = self.conversation_history[i]
            if entry.get("role") == "user":
                question_text = entry.get("content", "")
                break

        skill_text = load_skill("verify_answer")
        base_sys = self.system_prompt.toPlainText().strip() or (
            "Ты полезный ИИ-ассистент." if get_lang() == "ru" else "You are a helpful AI assistant."
        )
        verify_sys = f"{base_sys}\n\n{skill_text}" if skill_text else base_sys

        verify_messages = [
            {"role": "system", "content": verify_sys},
            {"role": "user", "content": (
                f"Вопрос пользователя:\n{question_text}\n\n"
                f"Твой предыдущий ответ на него:\n{answer_text}\n\n"
                f"Перепроверь этот ответ согласно инструкции выше."
            )}
        ]

        self._start_worker(
            override_messages=verify_messages,
            force_search=True,
            badge_override="проверка",
        )

    def _load_models(self):
        """Загрузка списка моделей из Ollama /api/tags (только для ollama)."""
        if getattr(self, "backend", "llama") != "ollama":
            return
        self.status_bar.setText(_t("status_loading_models"))
        self._model_loader = ModelLoaderThread()
        self._model_loader.models_loaded.connect(
            self._on_models_loaded, __import__("PyQt6.QtCore", fromlist=["Qt"]).Qt.ConnectionType.QueuedConnection)
        self._model_loader.error_occurred.connect(
            self._on_models_error, __import__("PyQt6.QtCore", fromlist=["Qt"]).Qt.ConnectionType.QueuedConnection)
        self._model_loader.finished.connect(self._model_loader.deleteLater)
        self._model_loader.start()

    def _on_models_loaded(self, models):
        prev = self.model_combo.currentText()
        self.model_combo.blockSignals(True)
        self.model_combo.clear()
        for m in models:
            self.model_combo.addItem(m["name"])
        self.model_combo.blockSignals(False)
        idx = self.model_combo.findText(prev)
        if idx >= 0:
            self.model_combo.setCurrentIndex(idx)
        self.status_bar.setText(_t("status_models_loaded", n=len(models)))

    def _on_models_error(self, err):
        self.status_bar.setText(_t("models_load_error", e=err))

    def _unload_model(self):
        """Выгрузка модели из памяти Ollama — пункт меню «Действия».
        Потерян при слиянии (i18n-ключи остались, вызов из меню — нет);
        восстановлен по запросу пользователя 2026-11-16."""
        if getattr(self, "backend", "llama") != "ollama":
            return
        model = self.model_combo.currentText()
        if not model:
            return
        if self.worker and self.worker.isRunning():
            self.status_bar.setText(_t("status_unload_busy", model=model))
            return
        self.status_bar.setText(_t("status_unloading", model=model))
        from core.background_threads import UnloadThread
        self._unload_thread = UnloadThread(model)
        self._unload_thread.done.connect(self._on_unload_done, Qt.ConnectionType.QueuedConnection)
        self._unload_thread.finished.connect(self._unload_thread.deleteLater)
        self._unload_thread.start()

    def _on_unload_done(self, ok: bool, info: str = ""):
        model = self.model_combo.currentText()
        if ok:
            self.status_bar.setText(_t("status_unloaded", model=model))
        else:
            self.status_bar.setText(_t("status_unload_busy", model=model))
