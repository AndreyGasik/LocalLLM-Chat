# app/base.py — единое окно чата с двумя бэкендами (llama.cpp / Ollama).
#
# Сборка: Llama-shell (CollapsibleSection, чат-лента, ввод, статус) +
# Ollama-секция (скрыта по умолчанию) + переключатель бэкенда в сайдбаре.
# Вся общая логика раундов — в Common/core/generation_loop.py.
import json

from PyQt6.QtWidgets import QApplication, QWidget
from PyQt6.QtCore import QTimer, Qt

from ui.main_window.layout_builder import UIBuilderMixin
from ui.main_window.theming import ThemingMixin
from ui.main_window.chat_io import ChatIOMixin
from ui.main_window.history import HistoryMixin
from ui.main_window.actions import ActionsMixin
from ui.main_window.server_mixin import ServerMixin
from ui.main_window.loop_actions import LoopMixin

from core.scraper import MCPScraper
from core.memory_db import MemoryDB
from core.llama_server import LlamaServerManager
from config import HISTORY_FILE
from i18n import _t, set_lang
from theme import A, make_app_icon


class ChatMainWindow(
    UIBuilderMixin,
    ThemingMixin,
    ChatIOMixin,
    HistoryMixin,
    ActionsMixin,
    ServerMixin,
    LoopMixin,
    A.AuroraWindow,
):
    def __init__(self):
        super().__init__("LLM Chat", size=(1280 + 32, 800 + 32), tag="",
                         icon=make_app_icon(), on_top=False, resizable=True)
        self.setWindowIcon(make_app_icon())
        self.unsetCursor()
        QApplication.instance().aboutToQuit.connect(self._detach_title_filter)
        if self.title_tag is not None:
            self.title_layout.setAlignment(self.title_tag, Qt.AlignmentFlag.AlignVCenter)

        # ── llama.cpp процесс-менеджер (нужен только для llama-бэкенда) ──
        self._server = LlamaServerManager(self)
        self._server.starting.connect(self._on_server_starting)
        self._server.ready.connect(self._on_server_ready)
        self._server.stopping.connect(self._on_server_stopping)
        self._server.stopped.connect(self._on_server_stopped)
        self._server.error.connect(self._on_server_error)

        self.worker = None
        self.conversation_history = []
        self.scraper = MCPScraper()
        self.memory = MemoryDB()
        self._token_count = 0
        self._start_time = 0.0
        self._ttft = 0.0
        self._override_active = False
        self._loop_active = False
        self._loop_phase = None
        self._loop_round = 0
        self._loop_question = ""
        self.history_file = HISTORY_FILE
        self._pending_files = []
        self.current_chat_id = None
        self.chat_title = _t("default_chat_title")
        self._title_gen = None
        self._title_generating = False
        self.tool_support_cache = {}
        self._worker_initial_msg_len = 0
        self._spin_arrow_buttons = []
        self._spin_arrow_containers = []
        self.num_ctx = None  # задаётся из combo в _switch_backend

        # ── язык из настроек ──
        saved_settings = {}
        if HISTORY_FILE.exists():
            try:
                saved_settings = json.loads(HISTORY_FILE.read_text(encoding="utf-8"))
            except Exception:
                pass
        saved_lang = saved_settings.get("settings", {}).get("lang", "ru")
        if saved_lang in ("ru", "en"):
            set_lang(saved_lang)
        # Бэкенд из сохранённых настроек
        self.backend = saved_settings.get("backend", "llama")
        if self.backend not in ("llama", "ollama"):
            self.backend = "llama"

        self.chat_title = self._default_chat_title()
        self._init_ui()
        # Применяем backend ПОСЛЕ сборки UI (переключатель создан)
        self._backend = self.backend
        for k, b in self._backend_buttons.items():
            b.setChecked(k == self.backend)
        self._sec_model.setVisible(self.backend == "llama")
        self._hline_model.setVisible(self.backend == "llama")

        self._restore_settings_and_history()
        self._refresh_chat_list()
        self._check_searxng()
        if self.backend == "ollama":
            self._load_models()
        elif self.model_dir:
            self._scan_models_folder()

        self._copy_timer = QTimer(self)
        self._copy_timer.setSingleShot(True)
        self._copy_timer.setInterval(2000)
        self._copy_timer.timeout.connect(
            lambda: self.status_bar.setText(_t("status_ready")))

    def mouseMoveEvent(self, e):
        QWidget.mouseMoveEvent(self, e)

    def _detach_title_filter(self):
        flt = getattr(self, "_title_dbl", None)
        if flt is None:
            return
        try:
            self.title_bar.removeEventFilter(flt)
        except RuntimeError:
            pass

    def closeEvent(self, event):
        self._detach_title_filter()
        self._stop_generation()
        self._server.stop_blocking()
        self.scraper.close()
        if hasattr(self.chat_area, '_flush_timer') and self.chat_area._flush_timer.isActive():
            self.chat_area._flush_timer.stop()
        if hasattr(self.chat_area, '_scroll_timer') and self.chat_area._scroll_timer.isActive():
            self.chat_area._scroll_timer.stop()
        self._save_settings_and_history()
        event.accept()
