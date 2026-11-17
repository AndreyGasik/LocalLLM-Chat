# ui/main_window/server_mixin.py
#
# Тонкая UI-обвязка над core/llama_server.py::LlamaServerManager. Вся
# логика подъёма/остановки/health-check/лога вынесена туда (см.
# миграционный план, раздел про core/llama_server.py); здесь только
# сбор параметров из виджетов сайдбара и реакция на сигналы менеджера
# (starting/ready/stopping/stopped/error) — обновление кнопки/статус-бара,
# ровно то же самое, что раньше делали _toggle_server/_check_server_health/
# _stop_server_proc и т.д. напрямую.
from pathlib import Path

from PyQt6.QtWidgets import (
    QMessageBox, QVBoxLayout, QLabel, QFileDialog,
)

from theme import SolidDialog, GhostBtn, get_palette as _P, UI_MARGIN, UI_SPACING
from i18n import _t, get_lang
from ui.widgets import confirm
from core.model_profiles.nanbeige import is_nanbeige_model


class ServerMixin:
    def _choose_server_folder(self):
        folder = QFileDialog.getExistingDirectory(
            self,
            "Выберите папку сервера" if get_lang() == "ru" else "Choose server folder",
            self.server_dir or "",
        )
        if not folder:
            return
        self.server_dir = self._normalize_server_dir(folder)
        self.server_path_btn.setText(self._server_label())
        self.server_path_btn.setToolTip(str(self._server_exe_path()))
        self._save_settings_and_history()

    def _normalize_server_dir(self, raw: str) -> str:
        # Пользователь может выбрать как корневую папку варианта (Vulkan/Nanbeige),
        # так и саму bin/ (или, из старых настроек, полный путь к бинарнику) —
        # в любом случае приводим к корневой папке, чтобы label и exe-путь не расходились.
        if not raw:
            return ""
        p = Path(raw)
        if p.name in ("llama-server", "llama-server.exe"):
            p = p.parent
        if p.name.lower() == "bin":
            p = p.parent
        return str(p)

    def _server_label(self) -> str:
        # Показываем "<папка>/bin" (например "Vulkan/bin" / "Nanbeige/bin"), а не
        # просто имя папки — иначе не видно, какой именно билд сервера выбран.
        if not self.server_dir:
            return ""
        return f"{Path(self.server_dir).name}/bin"

    def _server_exe_path(self) -> str:
        # Имя бинарника всегда стандартное — llama-server внутри bin/ выбранной папки.
        if not self.server_dir:
            return ""
        return str(Path(self.server_dir) / "bin" / "llama-server")

    def _choose_models_folder(self):
        folder = QFileDialog.getExistingDirectory(
            self,
            "Выберите папку с моделями" if get_lang() == "ru" else "Choose models folder",
            self.model_dir or "",
        )
        if not folder:
            return
        self.model_dir = folder
        self.model_dir_btn.setText(Path(folder).name)
        self.model_dir_btn.setToolTip(folder)
        self._scan_models_folder()
        self._save_settings_and_history()

    def _scan_models_folder(self):
        folder = self.model_dir
        if not folder or not Path(folder).is_dir():
            QMessageBox.warning(self, _t("dlg_error_title"),
                                "Указана неверная директория моделей." if get_lang() == "ru"
                                else "Invalid models directory specified.")
            return
        models = list(Path(folder).glob("*.gguf"))
        self.model_combo.clear()
        for p in models:
            self.model_combo.addItem(p.name)
        self.status_bar.setText(
            f"Найдено {len(models)} GGUF моделей" if get_lang() == "ru"
            else f"Found {len(models)} GGUF models"
        )


    def _toggle_server(self):
        if self._server.is_running():
            self._server.stop()
            return

        # Nanbeige параметризует chat-template (enable_thinking,
        # preserve_thinking, tool_call_format) — без --jinja сервер
        # применяет запасной эвристический форматтер, который эти тонкости
        # не учитывает. Проставляем галочку сами, если пользователь выбрал
        # такую модель и забыл включить --jinja вручную (план, п.2.3).
        if is_nanbeige_model(self.model_combo.currentText()) and not self.mtp_jinja.isChecked():
            self.mtp_jinja.setChecked(True)
            self.status_bar.setText(
                "Nanbeige требует --jinja для родного chat-template — включил автоматически."
                if get_lang() == "ru" else
                "Nanbeige needs --jinja for its native chat template — enabled it automatically."
            )

        error = self._server.start(
            exe=self._server_exe_path(),
            model_dir=self.model_dir,
            model_file=self.model_combo.currentText(),
            port=self.server_port.value(),
            threads=self.server_threads.value(),
            ngl=self.server_ngl.value(),
            np_=self.server_np.value(),
            ctx=self.server_ctx.value(),
            jinja=self.mtp_jinja.isChecked(),
            mtp_enabled=self.mtp_enabled.isChecked(),
            mtp_draft_n=self.mtp_draft_n.value(),
            mtp_draft_model=self.mtp_draft_model.text().strip(),
        )

        if error and ("уже используется" in error or "already in use" in error):
            # Порт занят, а self._server.is_running() при этом False — значит,
            # это не наш процесс из текущей сессии, а осиротевший llama-server,
            # оставшийся висеть после краша приложения (start_new_session=True
            # даёт ему свою группу процессов, живущую независимо от нас).
            port = self.server_port.value()
            resp = confirm(
                self, _t("dlg_error_title"),
                (f"Порт {port} занят — похоже, старый процесс сервера остался "
                 f"висеть после сбоя приложения. Остановить его и запустить заново?"
                 if get_lang() == "ru" else
                 f"Port {port} is busy — looks like a leftover server process "
                 f"from a previous crash. Stop it and start again?"),
            )
            if resp:
                if self._server.kill_orphan_on_port(port):
                    error = self._server.start(
                        exe=self._server_exe_path(),
                        model_dir=self.model_dir,
                        model_file=self.model_combo.currentText(),
                        port=port,
                        threads=self.server_threads.value(),
                        ngl=self.server_ngl.value(),
                        np_=self.server_np.value(),
                        ctx=self.server_ctx.value(),
                        jinja=self.mtp_jinja.isChecked(),
                        mtp_enabled=self.mtp_enabled.isChecked(),
                        mtp_draft_n=self.mtp_draft_n.value(),
                        mtp_draft_model=self.mtp_draft_model.text().strip(),
                    )
                else:
                    error = ("Не удалось остановить процесс на порту — возможно, "
                              "не хватает прав. Останови его вручную, например: "
                              f"fuser -k {port}/tcp" if get_lang() == "ru" else
                              "Failed to stop the process on that port — possibly "
                              f"a permissions issue. Stop it manually, e.g.: fuser -k {port}/tcp")

        if error:
            # LlamaServerManager.start() отдаёт уже готовый текст ошибки
            # без различения уровня — здесь везде .critical.
            QMessageBox.critical(self, _t("dlg_error_title"), error)

    # ---------------------------------------------------- сигналы LlamaServerManager
    def _on_server_starting(self):
        self._update_web_link()
        self.status_bar.setText("Запуск сервера…" if get_lang() == "ru" else "Starting server…")
        self.srv_btn.setText("Загрузка" if get_lang() == "ru" else "Loading")
        self.srv_btn.kind, self.srv_btn.stop_icon = "accent", False
        self.srv_btn.setEnabled(False)

    def _on_server_ready(self):
        self._update_web_link()
        self.srv_btn.setText("Остановить сервер" if get_lang() == "ru" else "Stop server")
        self.srv_btn.kind, self.srv_btn.stop_icon = "danger", True
        self.srv_btn.setEnabled(True)
        self.status_bar.setText("Сервер готов" if get_lang() == "ru" else "Server ready")

    def _on_server_stopping(self):
        self.status_bar.setText("Остановка сервера…" if get_lang() == "ru" else "Stopping server…")
        self.srv_btn.setText("Остановка…" if get_lang() == "ru" else "Stopping…")
        self.srv_btn.kind, self.srv_btn.stop_icon = "accent", False
        self.srv_btn.setEnabled(False)

    def _on_server_stopped(self):
        self._update_web_link()
        self.srv_btn.setText("Запустить сервер" if get_lang() == "ru" else "Start server")
        self.srv_btn.kind, self.srv_btn.stop_icon = "success", False
        self.srv_btn.setEnabled(True)
        self.status_bar.setText("Сервер остановлен" if get_lang() == "ru" else "Server stopped")

    def _on_server_error(self, msg: str):
        # Заголовок диалога один — общий dlg_error_title, само
        # сообщение (с хвостом лога) уже
        # сформировано внутри LlamaServerManager.
        QMessageBox.critical(self, _t("dlg_error_title"), msg)

    def _update_web_link(self):
        """Показывает кликабельную ссылку 'web' на встроенный веб-интерфейс
        llama-server, когда сервер поднят и ответил на /health."""
        p = _P()
        if self._server.is_running() and self._server.ready_flag:
            url = f"http://127.0.0.1:{self._server.port}/"
            self.web_link_label.setText(
                f'<a href="{url}" style="color:{p["LINK"]}; text-decoration:none;">'
                f'{"веб" if get_lang() == "ru" else "web"}</a>'
            )
            self.web_link_label.setToolTip(url)
            self.web_link_label.setVisible(True)
        else:
            self.web_link_label.setText("")
            self.web_link_label.setVisible(False)

    def _show_server_settings(self):
        dlg = SolidDialog("Настройки сервера" if get_lang() == "ru" else "Server settings", size=(380 + 32, 640), parent=self)
        lay = dlg.body
        lay.setContentsMargins(UI_MARGIN + 4, 2, UI_MARGIN + 4, UI_MARGIN + 4)
        lay.setSpacing(UI_SPACING)

        def add_row(label_text, widget):
            lbl = QLabel(label_text)
            lbl.setObjectName("fieldLabel")
            row = QVBoxLayout()
            row.setContentsMargins(0, 0, 0, 0)
            row.setSpacing(3)
            row.addWidget(lbl)
            row.addWidget(widget)
            lay.addLayout(row)

        add_row("Порт сервера:" if get_lang() == "ru" else "Server port:", self._wrap_spin(self.server_port))
        add_row("Потоки CPU (-t):" if get_lang() == "ru" else "CPU threads (-t):", self._wrap_spin(self.server_threads))
        add_row("Слои GPU (-ngl):" if get_lang() == "ru" else "GPU layers (-ngl):", self._wrap_spin(self.server_ngl))
        add_row("Параллельные слоты (-np):" if get_lang() == "ru" else "Parallel slots (-np):", self._wrap_spin(self.server_np))
        add_row("Размер контекста (-c):" if get_lang() == "ru" else "Context size (-c):", self._wrap_spin(self.server_ctx))

        lay.addWidget(self._hline())
        lay.addWidget(self.mtp_jinja)

        lay.addWidget(self._hline())
        mtp_lbl = QLabel("MTP (Multi-Token Prediction)")
        mtp_lbl.setObjectName("fieldLabel")
        lay.addWidget(mtp_lbl)
        lay.addWidget(self.mtp_enabled)
        add_row("--spec-draft-n-max:", self._wrap_spin(self.mtp_draft_n))
        add_row("Путь к draft-модели (-md):" if get_lang() == "ru" else "Draft model path (-md):", self.mtp_draft_model)

        close_btn = GhostBtn("Закрыть" if get_lang() == "ru" else "Close")
        close_btn.clicked.connect(dlg.accept)
        lay.addWidget(close_btn)
        dlg.resize(380 + 32, dlg.sizeHint().height())

        dlg.exec()
        for w in (self.server_port, self.server_threads, self.server_ngl,
                  self.server_np, self.server_ctx, self.mtp_enabled, self.mtp_draft_n,
                  self.mtp_draft_model, self.mtp_jinja):
            w.setParent(None)

