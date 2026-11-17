# ui/main_window/layout_builder.py
from PyQt6.QtWidgets import (
    QWidget, QVBoxLayout, QHBoxLayout, QLabel, QSplitter,
    QScrollArea, QLineEdit, QSpinBox, QDoubleSpinBox, QCheckBox, QTextEdit,
    QToolButton, QMenu, QListWidget, QSizePolicy, QAbstractSpinBox, QFrame,
)
from PyQt6.QtCore import Qt

from theme import (
    A, get_palette as _P, UI_ROW_H, UI_MARGIN, UI_SPACING,
    GhostBtn, PrimaryBtn, GlyphButton, RowPillDelegate, strip_emoji,
)
from i18n import _t, get_lang
from config import (
    DEFAULT_SERVER_PORT, DEFAULT_SERVER_THREADS, DEFAULT_SERVER_NGL,
    DEFAULT_SERVER_NP, DEFAULT_CTX, DEFAULT_MTP_DRAFT_N, MAX_LOOP_ITER,
    SIDEBAR_WIDTH,
)
from ui.widgets import CollapsibleSection, ModelPicker, NoWheelComboBox, _SpinEditFixer
from ui.chat_area import ChatArea


class UIBuilderMixin:
    def _wrap_spin(self, spin: QAbstractSpinBox) -> QWidget:
        """Спинбокс Aurora: [−] поле [+]. Кнопки шага — нарисованные пером, число
        строго по центру поля. Спинбокс растягивается на всю ширину ряда."""
        spin.setButtonSymbols(QAbstractSpinBox.ButtonSymbols.NoButtons)
        spin.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Fixed)
        spin.setFixedHeight(UI_ROW_H)

        # Колесо мыши не меняет значение: панель узкая, и при прокрутке сайдбара
        # курсор почти всегда над каким-нибудь спинбоксом. Событие «проваливается»
        # к скролл-контейнеру сайдбара.
        spin.wheelEvent = lambda event: event.ignore()
        spin.setFocusPolicy(Qt.FocusPolicy.StrongFocus)

        wrapper = QWidget()
        wrapper.setFixedHeight(UI_ROW_H)
        row = QHBoxLayout(wrapper)
        row.setContentsMargins(0, 0, 0, 0)
        row.setSpacing(4)

        # Внутреннее поле ввода спинбокса — без рамки и отступов, чтобы текст не обрезался
        # (правило с селектором-идентификатором: общее правило QLineEdit его не заденет).
        le = spin.lineEdit()
        if le is not None:
            le.setObjectName("spinEdit")
            le.setTextMargins(0, 0, 0, 0)
            le.setAlignment(Qt.AlignmentFlag.AlignCenter)
        spin._edit_fixer = _SpinEditFixer(spin, left=6, right=6)

        minus = GlyphButton("minus", UI_ROW_H, tile=True)
        plus = GlyphButton("plus", UI_ROW_H, tile=True)
        minus.clicked.connect(spin.stepDown)
        plus.clicked.connect(spin.stepUp)
        row.addWidget(minus)
        row.addWidget(spin, 1)
        row.addWidget(plus)

        self._spin_arrow_buttons.extend([minus, plus])
        return wrapper

    def _refresh_spin_arrow_colors(self, *buttons):
        """Кнопки шага рисуются по токенам текущей темы — достаточно перерисовать."""
        targets = list(buttons) if buttons else list(self._spin_arrow_buttons)
        alive = []
        for btn in targets:
            try:
                btn.update()
                alive.append(btn)
            except RuntimeError:
                continue      # кнопка принадлежала уже закрытому диалогу
        if not buttons:
            self._spin_arrow_buttons = alive

    def _init_ui(self):
        self.setMinimumSize(600 + 32, 400 + 32)
        self.move(100, 100)

        main_widget = QWidget()
        self.body.addWidget(main_widget)
        layout = QHBoxLayout(main_widget)
        layout.setContentsMargins(0, 0, 0, 0)

        splitter = QSplitter(Qt.Orientation.Horizontal)
        splitter.setChildrenCollapsible(False)
        splitter.setHandleWidth(1)
        layout.addWidget(splitter)

        sidebar_scroll = QScrollArea()
        sidebar_scroll.setWidgetResizable(True)
        sidebar_scroll.setFrameShape(QFrame.Shape.NoFrame)
        sidebar_scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        # Видимая вертикальная полоса отъедала часть ширины вьюпорта при
        # раскрытии CollapsibleSection ("Параметры" и т.п.) — сайдбар
        # заметно сужался и деформировался. Прокрутка колесом мыши
        # по-прежнему работает и без видимого бегунка (см. тот же приём
        # в эталонной ollama-версии, ui/main_window/layout_builder.py).
        sidebar_scroll.setVerticalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        sidebar_scroll.setObjectName("sidebarScroll")
        sidebar_scroll.viewport().setAutoFillBackground(False)
        # Ширина сайдбара ЖЁСТКО фиксирована (по запросу: интерфейс левой
        # панели не должен меняться в размере). Раньше здесь был диапазон
        # 200..440 и пользователь мог тянуть сплиттер; кроме того, при
        # длинном имени модели ModelPicker раздувал минимальную ширину
        # содержимого (см. комментарий в ui/widgets.py::ModelPicker), и
        # внутренний виджет QScrollArea рисовался шире вьюпорта — правый
        # край панели (кнопки, системный промпт) уходил за край окна.
        # Фиксированная ширина делает невозможным и то, и другое: у сплиттера
        # становится нечего тянуть (min == max у первого сегмента).
        sidebar_scroll.setFixedWidth(SIDEBAR_WIDTH)

        sidebar   = QWidget()
        sidebar.setObjectName("sidebarInner")
        sb_lay    = QVBoxLayout(sidebar)
        sb_lay.setContentsMargins(UI_MARGIN, UI_MARGIN, UI_MARGIN, UI_MARGIN)
        sb_lay.setSpacing(10)

        # Название — в заголовке окна (Aurora), кнопки темы и языка — тоже туда
        self.theme_btn = GlyphButton("theme", 28)
        self.theme_btn.setToolTip(_t("theme_tooltip"))
        self.theme_btn.clicked.connect(self._toggle_theme)
        self.add_title_widget(self.theme_btn)

        other_lang = "EN" if get_lang() == "ru" else "RU"
        self.lang_btn = GhostBtn(other_lang)
        self.lang_btn.setFixedSize(38, 26)
        self.lang_btn.setToolTip(_t("lang_tooltip"))
        self.lang_btn.clicked.connect(self._toggle_lang)
        self.add_title_widget(self.lang_btn)

        # ── Переключатель бэкенда ──────────────────────────────────────
        self.backend = getattr(self, "backend", "llama")
        self._backend_buttons = {}
        bk_row = QHBoxLayout()
        bk_row.setSpacing(4)
        for label, key in (("llama.cpp", "llama"), ("Ollama", "ollama")):
            b = GhostBtn(label)
            b.setFixedHeight(UI_ROW_H)
            b.setCheckable(True)
            b.setChecked(key == self.backend)
            b.clicked.connect(lambda checked, k=key: self._switch_backend(k))
            bk_row.addWidget(b, stretch=1)
            self._backend_buttons[key] = b
        sb_lay.addLayout(bk_row)

        # ── Общая модель (один combo для обоих бэкендов) ────────────────
        model_lbl = QLabel(("Модель:" if get_lang() == "ru" else "Model:"))
        model_lbl.setObjectName("fieldLabel")
        sb_lay.addWidget(model_lbl)
        self.model_combo = ModelPicker()
        self.model_combo.setObjectName("modelPicker")
        self.model_combo.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Fixed)
        self.model_combo.setFixedHeight(UI_ROW_H)
        sb_lay.addWidget(self.model_combo)



        sec_model = CollapsibleSection(("Модель и Сервер" if get_lang() == "ru" else "Model & Server"), expanded=True)
        self._sec_model = sec_model

        # Папка сервера выбирается диалогом (см. server_mixin.py::_choose_server_folder);
        # реальный путь к бинарнику собирается автоматически как <папка>/bin/llama-server —
        # имя бинарника всегда стандартное, меняется только сама папка.
        self.server_dir = ""
        self.server_path_btn = GhostBtn(
            "Выбрать папку сервера…" if get_lang() == "ru" else "Choose server folder…"
        )
        self.server_path_btn.setFixedHeight(UI_ROW_H)
        self.server_path_btn.clicked.connect(self._choose_server_folder)
        sec_model.add_row("Сервер:" if get_lang() == "ru" else "Server:", self.server_path_btn)

        # Папка с моделями — тем же паттерном, что и папка сервера
        # (см. server_mixin.py::_choose_server_folder): диалог выбора
        # директории вместо ручного ввода пути текстом.
        self.model_dir = ""
        self.model_dir_btn = GhostBtn(
            "Выбрать папку с моделями…" if get_lang() == "ru" else "Choose models folder…"
        )
        self.model_dir_btn.setFixedHeight(UI_ROW_H)
        self.model_dir_btn.clicked.connect(self._choose_models_folder)
        sec_model.add_row("Модели GGUF:" if get_lang() == "ru" else "GGUF models:", self.model_dir_btn)

        scan_btn = GhostBtn(("Обновить список" if get_lang() == "ru" else "Refresh list"))
        scan_btn.setFixedHeight(UI_ROW_H)
        scan_btn.clicked.connect(self._scan_models_folder)
        sec_model.add_widget(scan_btn)


        self.server_port = QSpinBox()
        self.server_port.setRange(1024, 65535)
        self.server_port.setValue(DEFAULT_SERVER_PORT)

        self.server_threads = QSpinBox()
        self.server_threads.setRange(1, 64)
        self.server_threads.setValue(DEFAULT_SERVER_THREADS)

        self.server_ngl = QSpinBox()
        self.server_ngl.setRange(0, 256)
        self.server_ngl.setValue(DEFAULT_SERVER_NGL)

        self.server_np = QSpinBox()
        self.server_np.setRange(1, 16)
        self.server_np.setValue(DEFAULT_SERVER_NP)
        self.server_np.setToolTip(
            "-np / --parallel\n"
            "Число параллельных слотов контекста. llama-server без этого флага "
            "сам выбирает 'auto' (часто 4), из-за чего реальный KV-кэш = -c × auto, "
            "что на GPU с малым объёмом свободной памяти (iGPU/shared) приводит к OOM "
            "ещё до открытия HTTP-порта. По умолчанию здесь стоит 1."
        )

        self.server_ctx = QSpinBox()
        self.server_ctx.setRange(512, 131072)
        self.server_ctx.setSingleStep(1024)
        self.server_ctx.setValue(DEFAULT_CTX)
        self.server_ctx.setButtonSymbols(QAbstractSpinBox.ButtonSymbols.NoButtons)

        self.mtp_enabled = QCheckBox("Включить MTP" if get_lang() == "ru" else "Enable MTP")
        self.mtp_enabled.setToolTip(
            "--spec-type draft-mtp\n"
            "Multi-Token Prediction — ускоренное предсказание для поддерживаемых моделей.\n"
            "Требует GGUF, собранный с MTP-головой (Unsloth MTP / Qwen3.6 MTP / Gemma-4 MTP)."
        )

        self.mtp_draft_n = QSpinBox()
        self.mtp_draft_n.setRange(1, 16)
        self.mtp_draft_n.setValue(DEFAULT_MTP_DRAFT_N)
        self.mtp_draft_n.setToolTip(
            "--spec-draft-n-max — число черновых токенов за шаг.\n"
            "Рекомендуемая стартовая точка: 2. Оптимум зависит от железа."
        )

        self.mtp_draft_model = QLineEdit()
        self.mtp_draft_model.setFixedHeight(UI_ROW_H)
        self.mtp_draft_model.setPlaceholderText(
            "(опционально) путь к отдельной MTP-draft GGUF — для моделей типа Gemma-4 MTP"
        )
        self.mtp_draft_model.setToolTip(
            "Некоторые модели (например Gemma-4 MTP) хранят MTP-голову в отдельном файле\n"
            "и требуют параметр -md <путь>. Qwen3.6 MTP GGUF несут голову внутри основного\n"
            "файла — оставьте пустым."
        )

        self.mtp_jinja = QCheckBox("Использовать --jinja (шаблон чата)" if get_lang() == "ru" else "Use --jinja (chat template)")
        self.mtp_jinja.setToolTip(
            "Включает обработку chat-шаблона через Jinja на стороне llama-server.\n"
            "Требуется для:\n"
            "  • корректного вывода рассуждений (reasoning_content) у моделей\n"
            "    типа Qwen3 / DeepSeek-R1-distill / GPT-OSS;\n"
            "  • многих MTP-сборок (спекулятивное декодирование).\n"
            "Не зависит от включения MTP."
        )

        srv_row = QHBoxLayout()
        srv_row.setSpacing(6)
        self.srv_btn = PrimaryBtn("Запустить сервер" if get_lang() == "ru" else "Start server", kind="primary")
        self.srv_btn.setFixedHeight(UI_ROW_H)
        self.srv_btn.clicked.connect(self._toggle_server)
        srv_row.addWidget(self.srv_btn, stretch=1)

        srv_settings_btn = GlyphButton("gear", UI_ROW_H, tile=True)
        srv_settings_btn.setToolTip("Настройки сервера и MTP" if get_lang() == "ru" else "Server & MTP settings")
        srv_settings_btn.clicked.connect(self._show_server_settings)
        srv_row.addWidget(srv_settings_btn)
        sec_model.add_layout(srv_row)

        sb_lay.addWidget(sec_model)
        self._hline_model = self._hline()
        self._hline_model.setVisible(self.backend == "llama")
        sb_lay.addWidget(self._hline_model)

        sec_gen = CollapsibleSection(("Поиск и Генерация" if get_lang() == "ru" else "Search & Generation"), expanded=False)
        self._sec_gen = sec_gen

        search_col = QVBoxLayout()
        search_col.setContentsMargins(0, 0, 0, 0)
        search_col.setSpacing(2)
        self.search_toggle = QCheckBox("Включить веб-поиск (SearXNG)" if get_lang() == "ru" else "Enable web search (SearXNG)")
        search_col.addWidget(self.search_toggle)
        self.searxng_label = QLabel(_t("searxng_checking"))
        self.searxng_label.setObjectName("dim10")
        self.searxng_label.setContentsMargins(26, 0, 0, 0)
        search_col.addWidget(self.searxng_label)
        sec_gen.add_layout(search_col)

        # Каждая группа инструментов включается своим отдельным переключателем —
        # раньше всё было завязано на один тумблер поиска (self.search_toggle),
        # и файлы/память/запись становились недоступны модели, стоило выключить
        # поиск, хотя логически это никак не связано (см. core/worker.py::run()
        # и комментарий там же — фича и формулировка взяты из эталона LLM-Chat).
        tool_btn_row = QHBoxLayout()
        tool_btn_row.setSpacing(6)
        self.files_tool_toggle = GhostBtn(_t("files_tool_btn"))
        self.files_tool_toggle.setObjectName("toolToggleBtn")
        self.files_tool_toggle.setCheckable(True)
        self.files_tool_toggle.setChecked(True)
        self.files_tool_toggle.setToolTip(_t("files_tool_tooltip"))
        tool_btn_row.addWidget(self.files_tool_toggle)

        self.memory_tool_toggle = GhostBtn(_t("memory_tool_btn"))
        self.memory_tool_toggle.setObjectName("toolToggleBtn")
        self.memory_tool_toggle.setCheckable(True)
        self.memory_tool_toggle.setChecked(True)
        self.memory_tool_toggle.setToolTip(_t("memory_tool_tooltip"))
        tool_btn_row.addWidget(self.memory_tool_toggle)

        self.write_tool_toggle = GhostBtn(_t("write_tool_btn"))
        self.write_tool_toggle.setObjectName("toolToggleBtn")
        self.write_tool_toggle.setCheckable(True)
        self.write_tool_toggle.setChecked(True)
        self.write_tool_toggle.setToolTip(_t("write_tool_tooltip"))
        tool_btn_row.addWidget(self.write_tool_toggle)
        sec_gen.add_layout(tool_btn_row)

        # Терминал — на ОТДЕЛЬНОЙ строке: в ряд с Файлы/Память/Запись четвёртая
        # кнопка не влезает в фиксированную ширину сайдбара (SIDEBAR_WIDTH) —
        # QLayout начал бы обрезать текст кнопок (как в эталоне LLM-Chat).
        tool_btn_row2 = QHBoxLayout()
        self.terminal_tool_toggle = GhostBtn(_t("terminal_tool_btn"))
        self.terminal_tool_toggle.setObjectName("toolToggleBtn")
        self.terminal_tool_toggle.setCheckable(True)
        self.terminal_tool_toggle.setChecked(True)
        self.terminal_tool_toggle.setToolTip(_t("terminal_tool_tooltip"))
        tool_btn_row2.addWidget(self.terminal_tool_toggle)
        tool_btn_row2.addStretch()
        sec_gen.add_layout(tool_btn_row2)

        self.num_results = QSpinBox()
        self.num_results.setRange(1, 10)
        self.num_results.setValue(5)
        sec_gen.add_row("Кол-во результатов:" if get_lang() == "ru" else "Result count:", self._wrap_spin(self.num_results))

        self.temperature = QDoubleSpinBox()
        self.temperature.setRange(0.0, 2.0)
        self.temperature.setValue(0.7)
        self.temperature.setSingleStep(0.05)
        self.temperature.setDecimals(2)
        sec_gen.add_row(_t("temperature_label"), self._wrap_spin(self.temperature))

        self.top_p = QDoubleSpinBox()
        self.top_p.setRange(0.0, 1.0)
        self.top_p.setValue(0.9)
        self.top_p.setSingleStep(0.05)
        self.top_p.setDecimals(2)
        sec_gen.add_row("Top P:", self._wrap_spin(self.top_p))

        # ── Контролы Ollama-бэкенда ─────────────────────────────────────
        # Потеряны при слиянии: в эталонной Ollama-версии в параметрах были
        # «По умолчанию модели» (не подменять temperature/top_p модели) и
        # выбор размера контекста (num_ctx) — chat_io.py их уже ждёт
        # (getattr с запасным значением). Для llama.cpp контекст задаётся
        # серверу флагом -c («Настройки сервера»), поэтому на этой вкладке
        # блок скрыт: на вкладке ollama в нём нет полей.
        ollama_gen = QWidget()
        ol_lay = QVBoxLayout(ollama_gen)
        ol_lay.setContentsMargins(0, 0, 0, 0)
        ol_lay.setSpacing(UI_SPACING)
        self.use_model_defaults = QCheckBox(_t("model_defaults"))
        ol_lay.addWidget(self.use_model_defaults)
        ol_lbl = QLabel(_t("num_ctx_label"))
        ol_lbl.setObjectName("fieldLabel")
        ol_lay.addWidget(ol_lbl)
        self.num_ctx_combo = NoWheelComboBox()
        self.num_ctx_combo.addItem(_t("num_ctx_default"), None)
        for v in (2048, 4096, 8192, 16384, 32768, 65536, 131072):
            self.num_ctx_combo.addItem(str(v), v)
        self.num_ctx_combo.setCurrentIndex(3)
        self.num_ctx_combo.currentIndexChanged.connect(self._sync_num_ctx)
        ol_lay.addWidget(self.num_ctx_combo)
        sec_gen.add_widget(ollama_gen)
        self._ollama_gen_box = ollama_gen
        ollama_gen.setVisible(getattr(self, "backend", "llama") == "ollama")

        self.max_tokens = QSpinBox()
        self.max_tokens.setRange(-1, 32768)
        self.max_tokens.setValue(-1)
        self.max_tokens.setButtonSymbols(QAbstractSpinBox.ButtonSymbols.NoButtons)
        sec_gen.add_row("Макс. токенов (-1 = ∞):" if get_lang() == "ru" else "Max tokens (-1 = ∞):", self._wrap_spin(self.max_tokens))

        self.ctx_limit = QSpinBox()
        self.ctx_limit.setRange(2, 500)
        self.ctx_limit.setValue(40)
        sec_gen.add_row("Лимит сообщений:" if get_lang() == "ru" else "Message limit:", self._wrap_spin(self.ctx_limit))

        self.show_thoughts = QCheckBox("Показывать мысли (<think>)" if get_lang() == "ru" else "Show thoughts (<think>)")
        self.show_thoughts.setChecked(True)
        self.show_thoughts.stateChanged.connect(
            lambda s: self.chat_area.set_show_thoughts(s == Qt.CheckState.Checked.value)
        )
        sec_gen.add_widget(self.show_thoughts)

        self.loop_toggle = QCheckBox(_t("loop_toggle"))
        self.loop_toggle.setChecked(False)
        self.loop_toggle.setToolTip(_t("loop_toggle_tooltip"))
        sec_gen.add_widget(self.loop_toggle)

        self.loop_max_iter = QSpinBox()
        self.loop_max_iter.setRange(1, 10)
        self.loop_max_iter.setValue(MAX_LOOP_ITER)
        sec_gen.add_row(_t("loop_max_label"), self._wrap_spin(self.loop_max_iter))

        sb_lay.addWidget(sec_gen)
        sb_lay.addWidget(self._hline())

        sys_lbl = QLabel(_t("system_prompt_label"))
        sys_lbl.setObjectName("fieldLabel")
        sys_lbl.setContentsMargins(2, 6, 0, 0)
        sb_lay.addWidget(sys_lbl)
        self.system_prompt = QTextEdit()
        self.system_prompt.setPlaceholderText(_t("system_prompt_ph"))
        self.system_prompt.setMinimumHeight(60)
        sb_lay.addWidget(self.system_prompt, 1)

        self.memory_btn = GhostBtn(_t("memory_btn"))
        self.memory_btn.setFixedHeight(UI_ROW_H)
        self.memory_btn.setToolTip(_t("memory_tooltip"))
        self.memory_btn.clicked.connect(self._show_memory)
        sb_lay.addWidget(self.memory_btn)

        sb_lay.addStretch()
        sb_lay.addWidget(self._hline())

        bottom_row = QHBoxLayout()
        bottom_row.setContentsMargins(0, 0, 0, 0)
        bottom_row.setSpacing(8)

        self.context_label = QLabel(_t("context_label", n=0, lim=40))
        self.context_label.setObjectName("dim10")
        self.context_label.setFont(A.font_mono(10))
        bottom_row.addWidget(self.context_label, stretch=1)

        self.token_usage_label = QLabel(_t("token_usage_label", n=0, lim="—"))
        self.token_usage_label.setObjectName("dim10")
        self.token_usage_label.setFont(A.font_mono(10))
        bottom_row.addWidget(self.token_usage_label, stretch=1)

        self.web_link_label = QLabel("")
        self.web_link_label.setStyleSheet("font-size:10px;")
        self.web_link_label.setTextFormat(Qt.TextFormat.RichText)
        self.web_link_label.setTextInteractionFlags(Qt.TextInteractionFlag.TextBrowserInteraction)
        self.web_link_label.setOpenExternalLinks(True)
        self.web_link_label.setCursor(Qt.CursorShape.PointingHandCursor)
        self.web_link_label.setVisible(False)
        bottom_row.addWidget(self.web_link_label)

        sb_lay.addLayout(bottom_row)

        sidebar_scroll.setWidget(sidebar)
        sidebar.setAutoFillBackground(False)   # setWidget включает заливку — закрасила бы стекло окна
        splitter.addWidget(sidebar_scroll)

        chat_pane = QWidget()
        chat_lay  = QVBoxLayout(chat_pane)
        chat_lay.setContentsMargins(0, 0, 12, 0)     # поле справа — внутри скруглённой рамки окна
        chat_lay.setSpacing(0)

        top_bar = QWidget()
        top_bar.setFixedHeight(45)
        top_lay = QHBoxLayout(top_bar)
        top_lay.setContentsMargins(10, 0, 10, 0)

        new_chat_btn = GhostBtn(_t("new_chat_btn"))
        new_chat_btn.setFixedHeight(32)
        new_chat_btn.clicked.connect(self._new_chat)
        top_lay.addWidget(new_chat_btn)

        self.history_btn = GhostBtn("История" if get_lang() == "ru" else "History")
        self.history_btn.setFixedHeight(32)
        self.history_btn.setCheckable(True)
        self.history_btn.clicked.connect(self._toggle_history_panel)
        top_lay.addWidget(self.history_btn)

        top_lay.addStretch()

        self.actions_btn = QToolButton()
        self.actions_btn.setObjectName("menuBtn")
        self.actions_btn.setFixedHeight(32)
        self.actions_btn.setText(strip_emoji(_t("menu_btn")))
        self.actions_btn.setPopupMode(QToolButton.ToolButtonPopupMode.InstantPopup)
        self.act_menu = QMenu(self)
        self._rebuild_menu()
        self.actions_btn.setMenu(self.act_menu)
        top_lay.addWidget(self.actions_btn)

        chat_lay.addWidget(top_bar)

        self.history_list = QListWidget()
        self.history_list.setObjectName("historyList")
        self.history_list.setFrameShape(QFrame.Shape.NoFrame)
        self.history_list.setMouseTracking(True)
        self.history_list.viewport().setAutoFillBackground(False)
        self.history_list.setItemDelegate(RowPillDelegate(self.history_list))
        self.history_list.setMaximumHeight(160)
        self.history_list.itemClicked.connect(self._on_history_item_clicked)
        self.history_list.setVisible(False)
        chat_lay.addWidget(self.history_list)

        self.delete_chat_row = QWidget()
        del_row_lay = QHBoxLayout(self.delete_chat_row)
        del_row_lay.setContentsMargins(10, 2, 10, 2)
        self.delete_chat_btn = GhostBtn(_t("delete_chat_btn"))
        self.delete_chat_btn.setFixedHeight(30)
        self.delete_chat_btn.clicked.connect(self._delete_selected_chat)
        del_row_lay.addWidget(self.delete_chat_btn)
        del_row_lay.addStretch()
        self.delete_chat_row.setVisible(False)
        chat_lay.addWidget(self.delete_chat_row)

        self.chat_area = ChatArea()
        self.chat_area.set_model_name(self.model_combo.currentText())
        self.model_combo.currentTextChanged.connect(self.chat_area.set_model_name)
        self.chat_area.copy_requested.connect(self._on_copy)
        self.chat_area.regen_requested.connect(self._on_regen)
        self.chat_area.edit_requested.connect(self._on_edit)
        self.chat_area.resend_requested.connect(self._on_resend)
        self.chat_area.verify_requested.connect(self._on_verify_answer)
        chat_lay.addWidget(self.chat_area, stretch=1)

        inp_container = QWidget()
        inp_main      = QVBoxLayout(inp_container)
        inp_main.setContentsMargins(16, 8, 16, 8)
        inp_main.setSpacing(2)

        self.chips_panel = QWidget()
        self.chips_layout = QHBoxLayout(self.chips_panel)
        self.chips_layout.setContentsMargins(0, 0, 0, 0)
        self.chips_layout.setSpacing(8)
        self.chips_layout.setAlignment(Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignVCenter)
        self.chips_panel.setVisible(False)
        inp_main.addWidget(self.chips_panel)

        inp_lay       = QHBoxLayout()
        inp_lay.setContentsMargins(0, 0, 0, 0)
        inp_lay.setSpacing(8)
        inp_main.addLayout(inp_lay)

        self.file_btn = GlyphButton("attach", 40, tile=True)
        self.file_btn.setToolTip(_t("file_tooltip"))
        self.file_btn.clicked.connect(self._attach_file)
        inp_lay.addWidget(self.file_btn)

        self.input_field = QTextEdit()
        self.input_field.setMaximumHeight(110)
        self.input_field.setMinimumHeight(48)
        self.input_field.setPlaceholderText(_t("input_placeholder"))
        self.input_field.installEventFilter(self)
        inp_lay.addWidget(self.input_field, stretch=1)

        btn_wrap = QWidget()
        bc       = QVBoxLayout(btn_wrap)
        bc.setContentsMargins(0, 0, 0, 0)
        bc.setSpacing(8)

        self.send_btn = PrimaryBtn(_t("send_btn"), kind="accent")
        self.send_btn.setFixedHeight(40)
        self.send_btn.setMinimumWidth(100)
        self.send_btn.clicked.connect(lambda: self._send_message())
        bc.addWidget(self.send_btn)

        self.stop_btn = PrimaryBtn(_t("stop_btn"), kind="danger", stop_icon=True)
        self.stop_btn.setFixedHeight(40)
        self.stop_btn.setEnabled(False)
        self.stop_btn.clicked.connect(self._stop_generation)
        bc.addWidget(self.stop_btn)

        inp_lay.addWidget(btn_wrap)
        chat_lay.addWidget(inp_container)

        status_row = QHBoxLayout()
        status_row.setContentsMargins(10, 2, 10, 10)
        self.status_bar = QLabel(_t("status_ready"))
        self.status_bar.setObjectName("dim11")
        status_row.addWidget(self.status_bar, stretch=1)
        self.rt_status = QLabel("")
        self.rt_status.setObjectName("dim11")
        status_row.addWidget(self.rt_status)
        chat_lay.addLayout(status_row)

        splitter.addWidget(chat_pane)
        splitter.setSizes([340, 940])
        splitter.setStretchFactor(0, 0)
        splitter.setStretchFactor(1, 1)

        self._apply_theme_styles(_P())

    def _hline(self):
        f = QFrame()
        f.setObjectName("hline")
        f.setFixedHeight(1)
        return f

    def _sync_num_ctx(self, idx: int):
        """base.py держит self.num_ctx для chat_io.py (worker Ollama)."""
        self.num_ctx = self.num_ctx_combo.itemData(idx)

    def eventFilter(self, obj, event):
        if obj is self.input_field and event.type() == event.Type.KeyPress:
            if (event.key() in (Qt.Key.Key_Return, Qt.Key.Key_Enter)
                    and not (event.modifiers() & Qt.KeyboardModifier.ShiftModifier)):
                self._send_message()
                return True
        return super().eventFilter(obj, event)

    def _toggle_history_panel(self, checked: bool):
        self.history_list.setVisible(checked)
        self.delete_chat_row.setVisible(checked)
        self.history_btn.setText("История ^" if checked else "История")
        # i18n wrapper
        self.history_btn.setText(("История ^" if get_lang() == "ru" else "History ^")
                                 if checked else ("История" if get_lang() == "ru" else "History"))
        if checked:
            self._refresh_chat_list()

    def _switch_backend(self, key: str):
        """Переключение бэкенда: меняет видимость секций и сохраняет выбор."""
        if key == self.backend:
            for bk, b in self._backend_buttons.items():
                b.setChecked(bk == self.backend)
            return
        self.backend = key
        for bk, b in self._backend_buttons.items():
            b.setChecked(bk == self.backend)
        # меню «Действия» содержит пункты, зависящие от бэкенда
        # («Выгрузить модель» — только Ollama) — пересобрать
        self._rebuild_menu()
        self._sec_model.setVisible(key == "llama")
        self._hline_model.setVisible(key == "llama")
        self._ollama_gen_box.setVisible(key == "ollama")
        # _sec_gen (тумблеры + параметры) — общая для обоих бэкендов,
        # НЕ скрывается при переключении
        # Новый чат при смене бэкенда: история对话 не переносится между
        # системами (у каждой модели свой контекст и свой формат истории)
        self._new_chat()
        # Перезагрузить модели: Ollama → /api/tags, llama.cpp → GGUF скан
        if key == "ollama":
            self._load_models()
        elif hasattr(self, "model_dir") and self.model_dir:
            self._scan_models_folder()
        else:
            # Папка GGUF не выбрана: список моделей llama пуст — иначе в
            # панели llama остаются модели, загруженные с Ollama-вкладки
            self.model_combo.clear()
