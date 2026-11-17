# ui/bubble.py
"""Пузыри ленты чата.

Структура ответа бота (после перестройки 2026-11-16): мысли и вызовы
инструментов — СТРОКИ ВНЕ РАМКИ баббла, «встроенные в подложку» ленты;
рамка-баббл обёрнута только вокруг текста ответа. Разворачивание /
сворачивание такой строки меняет высоту ТОЛЬКО самой строки — рамка и
содержимое текстовых бабблов не пересчитываются и не сдвигаются внутри
себя (требование «бабл стабилен как скала» при кликах по блокам).

Схема — как у Claude.ai / ChatGPT:

    имя модели · бейдж          ← строка без рамки
    ▼ Мысли · 214 сл.           ← строка вне рамки (подложка ленты)
    ┌──────────────────┐
    │ текст раунда 1     │      ← TextBubble: рамка только вокруг текста
    └──────────────────┘
    ▶ SEARCH: …                ← строка вне рамки
    ✓ результат: …             ← строка вне рамки
    ┌──────────────────┐
    │ текст раунда 2     │      ← новый TextBubble после инструментов
    └──────────────────┘
    статистика · [копия][реген]  ← футер
"""
from PyQt6.QtWidgets import (
    QWidget, QLabel, QHBoxLayout, QVBoxLayout, QToolButton,
    QFrame, QSizePolicy, QGraphicsOpacityEffect,
)
from PyQt6.QtCore import Qt, pyqtSignal, QPropertyAnimation

from theme import get_palette as _P
from i18n import get_lang, _t
from aurora import GlyphButton, font_mono, strip_emoji

from core.markdown import _escape, _render_markdown
from ui.widgets import FileCard, ThemedLabel
from ui.stream_widgets import (
    StreamLabel, _CollapsibleThoughtWidget, _CollapsibleToolWidget,
    ThinkingIndicator,
)


class BubbleWidget(QWidget):
    """Пузырь сообщения ПОЛЬЗОВАТЕЛЯ: имя, файл-карточки, текст и футер с
    кнопками — всё внутри одной рамки USER_BG. Сообщения пользователя
    статичны после создания (не стримятся блоками), поэтому им новая
    секционная структура не нужна.

    Ответы бота собирает BotReplyWidget ниже."""
    edit_clicked   = pyqtSignal(int, str)
    resend_clicked = pyqtSignal(int)

    def __init__(self, msg_index: int = -1, parent=None):
        super().__init__(parent)
        self.msg_index = msg_index
        self._plain_text = ""
        self._radius = 12
        self.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Preferred)

        outer = QVBoxLayout(self)
        outer.setContentsMargins(10, 4, 10, 2)
        outer.setSpacing(2)

        self._bubble = QWidget()
        self._bubble.setObjectName("bubble")
        self._bubble.setSizePolicy(QSizePolicy.Policy.Preferred, QSizePolicy.Policy.Preferred)
        self._inner = QVBoxLayout(self._bubble)
        self._inner.setContentsMargins(16, 12, 16, 12)
        self._inner.setSpacing(4)

        row = QHBoxLayout()
        row.setContentsMargins(0, 0, 0, 0)
        row.setSpacing(0)
        # Баббл пользователя прижимается к правому краю и получает ширину
        # по содержимому (stretch=0 не участвует в распределении лишнего
        # места); фиксированный отступ справа гарантирует видимый зазор от
        # края viewport'а независимо от скроллбара.
        row.addStretch(1)
        row.addWidget(self._bubble, 0)
        row.addSpacing(14)
        outer.addLayout(row)

        # Кнопки живут ВНУТРИ баббла (в _inner), в одной строке со
        # статистикой — они часть той же геометрии, что и текст.
        self._footer_widget = self._build_footer()
        self._footer_added = False

        self.recolor(_P())
        self._fade_effect = None
        self._fade_anim = None

    def resizeEvent(self, event):
        super().resizeEvent(event)
        # Пропорции по скриншоту Claude.ai: пузырь длинного сообщения
        # занимает ~86% ширины колонки; минимум для коротких — оценка.
        cap = max(220, int(self.width() * 0.86))
        min_w = min(int(self.width() * 0.38), cap)
        self._bubble.setMaximumWidth(cap)
        self._bubble.setMinimumWidth(min_w)

    # Кнопки действий: GlyphButton из Aurora (геометрия фиксирована классом)
    def _mk_act_btn(self, kind: str, tooltip: str) -> QToolButton:
        btn = GlyphButton(kind, 26)
        btn.setToolTip(tooltip)
        return btn

    def _build_footer(self) -> QWidget:
        """Строка-«подвал»: справа кнопки «Изменить»/«Переслать» в лёгкой
        рамке; иконки центрированы по вертикали (рамка растягивается по
        кнопкам 26px + симметричные поля)."""
        p = _P()
        container = QWidget()
        container.setObjectName("bubble_footer")
        lay = QHBoxLayout(container)
        lay.setContentsMargins(0, 4, 0, 0)
        lay.setSpacing(6)

        # Левая часть пустая (статистика — только у бота), рамка справа.
        spacer = QLabel("")
        lay.addWidget(spacer, 1)

        self._action_frame = QFrame()
        self._action_frame.setObjectName("action_frame")
        act_lay = QHBoxLayout(self._action_frame)
        act_lay.setContentsMargins(6, 2, 6, 2)
        act_lay.setSpacing(4)
        self.btn_edit = self._mk_act_btn("edit", "Изменить" if get_lang() == "ru" else "Edit")
        self.btn_edit.clicked.connect(self._on_edit)
        self.btn_resend = self._mk_act_btn("resend", "Переслать" if get_lang() == "ru" else "Resend")
        self.btn_resend.clicked.connect(self._on_resend)
        act_lay.addWidget(self.btn_edit)
        act_lay.addWidget(self.btn_resend)
        self._style_action_frame()
        lay.addWidget(self._action_frame, 0, Qt.AlignmentFlag.AlignRight)

        container.setStyleSheet(
            f"QWidget#bubble_footer {{ background: transparent; border: none; "
            f"border-top: 1px solid {p['BORDER']}; }}"
        )
        container._is_footer = True
        return container

    def _style_action_frame(self):
        p = _P()
        self._action_frame.setStyleSheet(f"""
            QFrame#action_frame {{
                background: transparent;
                border: 1px solid {p['BORDER']};
                border-radius: 9px;
            }}
        """)

    def _finalize_footer(self):
        """Добавляет строку с кнопками в конец баббла (после текста)."""
        if self._footer_added:
            return
        self._inner.addWidget(self._footer_widget)
        self._footer_added = True

    def set_plain_text(self, text: str):
        self._plain_text = text

    def _on_edit(self): self.edit_clicked.emit(self.msg_index, self._plain_text)
    def _on_resend(self): self.resend_clicked.emit(self.msg_index)

    def add_name(self, name: str):
        p = _P()
        color = p["USER_NAME"]
        lbl = ThemedLabel(_escape(strip_emoji(name)))
        lbl.setTextFormat(Qt.TextFormat.RichText)
        lbl.setStyleSheet(
            f"color:{color};font-size:11px;font-weight:500;"
            f"background:transparent;border:none;"
        )
        self._inner.addWidget(lbl)

    def add_text(self, text: str):
        lbl = ThemedLabel()
        lbl.setWordWrap(True)
        lbl.setTextFormat(Qt.TextFormat.RichText)
        lbl.setOpenExternalLinks(True)
        lbl.setTextInteractionFlags(
            Qt.TextInteractionFlag.TextSelectableByMouse |
            Qt.TextInteractionFlag.TextSelectableByKeyboard |
            Qt.TextInteractionFlag.LinksAccessibleByMouse
        )
        p = _P()
        html = _render_markdown(text, p)
        lbl.setStyleSheet(
            f"color:{p['USER_TEXT']};background:transparent;font-size:13px;line-height:1.6;border:none;"
        )
        lbl.setText(f'<span style="white-space:pre-wrap;">{html}</span>')
        lbl._plain_text = text
        lbl._is_markdown = True
        self._inner.addWidget(lbl)

    def add_file_card(self, path: str):
        card = FileCard(path)
        self._inner.addWidget(card)

    def recolor(self, p: dict):
        self._bubble.setStyleSheet(f"""
            QWidget#bubble {{
                background-color: {p['USER_BG']};
                border: 1px solid {p['USER_BR']};
                border-radius: {self._radius}px;
            }}
        """)
        for i in range(self._inner.count()):
            item = self._inner.itemAt(i)
            if not (item and item.widget()):
                continue
            w = item.widget()
            if isinstance(w, FileCard):
                w.recolor()
            elif isinstance(w, QLabel):
                if getattr(w, "_is_markdown", False) and hasattr(w, "_plain_text"):
                    w.setStyleSheet(
                        f"color:{p['USER_TEXT']};background:transparent;font-size:13px;"
                        f"line-height:1.6;border:none;"
                    )
                    html = _render_markdown(w._plain_text, p)
                    w.setText(f'<span style="white-space:pre-wrap;">{html}</span>')
                elif not getattr(w, "_is_footer", False):
                    w.setStyleSheet(
                        f"color:{p['USER_NAME']};font-size:11px;font-weight:500;"
                        f"background:transparent;border:none;"
                    )
        self._footer_widget.setStyleSheet(
            f"QWidget#bubble_footer {{ background: transparent; border: none; "
            f"border-top: 1px solid {p['BORDER']}; }}"
        )
        self._style_action_frame()

    def animate_in(self):
        if self._fade_effect is None:
            self._fade_effect = QGraphicsOpacityEffect(self)
            self.setGraphicsEffect(self._fade_effect)
            self._fade_effect.setOpacity(0.0)
            self.show()
            self._fade_anim = QPropertyAnimation(self._fade_effect, b"opacity")
            self._fade_anim.setDuration(180)
            self._fade_anim.setStartValue(0.0)
            self._fade_anim.setEndValue(1.0)
            self._fade_anim.start()


class TextBubble(QFrame):
    """Рамка-баббл вокруг текста ОДНОГО раунда ответа бота. Внутри —
    StreamLabel. Создаётся лениво при первом куске текста раунда и после
    «запечатывания» (seal_text_round) больше не меняется: следующие раунды
    получают свой баббл. Поэтому рамка и содержимое уже показанного раунда
    физически не пересчитываются, что бы ни раскрывалось выше/ниже."""

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setObjectName("bubble")
        self.setSizePolicy(QSizePolicy.Policy.Preferred, QSizePolicy.Policy.Preferred)
        lay = QVBoxLayout(self)
        lay.setContentsMargins(16, 12, 16, 12)
        lay.setSpacing(0)
        self.label = StreamLabel(self)
        lay.addWidget(self.label)
        self.recolor(_P())

    def recolor(self, p: dict):
        self.setStyleSheet(f"""
            QFrame#bubble {{
                background-color: {p['BOT_BG']};
                border: 1px solid {p['BOT_BR']};
                border-radius: 12px;
            }}
        """)


class BotReplyWidget(QWidget):
    """Один ответ бота в ленте: секционная структура (см. модуль вверху).

    Мысли, вызовы и результаты инструментов добавляются строками ВНЕ рамки
    (поверх подложки ленты), текст — в TextBubble с рамкой. Всё живёт в
    одном QVBoxLayout и добавляется в конец: порядок добавления = порядок
    показа. Разворачивание блока меняет высоту только его строки."""
    copy_clicked   = pyqtSignal(str)
    regen_clicked  = pyqtSignal(int)
    verify_clicked = pyqtSignal(int, str)

    def __init__(self, model_name: str, badge: str = "", msg_index: int = -1,
                 parent=None):
        super().__init__(parent)
        self.msg_index = msg_index
        self._plain_text = ""
        self.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Preferred)

        self._lay = QVBoxLayout(self)
        self._lay.setContentsMargins(10, 4, 10, 2)
        self._lay.setSpacing(4)

        self._name_lbl: ThemedLabel | None = None
        self._indicator: ThinkingIndicator | None = None
        self._thought: _CollapsibleThoughtWidget | None = None
        self._bubbles: list[TextBubble] = []
        self._tool_rows: list[_CollapsibleToolWidget] = []
        self._cards: list = []
        self._active: TextBubble | None = None    # баббл текущего (незапечатанного) раунда
        self._footer: QWidget | None = None
        self._stats_lbl: QLabel | None = None
        self._action_frame: QFrame | None = None

        if model_name:
            self.add_name(model_name, badge)

        self._fade_effect = None
        self._fade_anim = None

    # ── ширина текстовых бабблов (рамка не шире 86% колонки) ──
    def resizeEvent(self, event):
        super().resizeEvent(event)
        cap = max(220, int(self.width() * 0.86))
        for b in self._bubbles:
            b.setMaximumWidth(cap)

    def add_name(self, name: str, badge: str = ""):
        p = _P()
        color = p["BOT_NAME"]
        txt = _escape(strip_emoji(name))
        if badge:
            txt += f' <span style="color:{p["OK"]};font-size:9px;">{_escape(badge)}</span>'
        lbl = ThemedLabel(txt)
        lbl.setTextFormat(Qt.TextFormat.RichText)
        # имя модели — метка прибора: моно
        lbl.setStyleSheet(
            f"color:{color};font-size:11px;font-weight:500;"
            f"font-family:'DejaVu Sans Mono','JetBrains Mono',monospace;"
            f"background:transparent;border:none;"
        )
        self._lay.addWidget(lbl)
        self._name_lbl = lbl

    # ── индикатор «Думаю…» ──
    def show_thinking(self):
        if self._indicator is None:
            self._indicator = ThinkingIndicator(_t("status_thinking").rstrip("…"), self)
            self._lay.addWidget(self._indicator)
            self._indicator.start()

    def hide_thinking(self):
        if self._indicator is not None:
            self._indicator.stop()
            self._lay.removeWidget(self._indicator)
            self._indicator.hide()
            self._indicator.deleteLater()
            self._indicator = None

    # ── блок мыслей (строка вне рамки) ──
    def ensure_thought(self) -> _CollapsibleThoughtWidget:
        if self._thought is None:
            self.hide_thinking()
            self._thought = _CollapsibleThoughtWidget(self)
            # Мысли всегда идут СРАЗУ ПОСЛЕ ИМЕНИ: reasoning предшествует
            # тексту раунда, поэтому на момент создания блока ниже ещё
            # ничего нет (индикатор скрывается строкой выше).
            idx = 1 if self._name_lbl is not None else 0
            self._lay.insertWidget(idx, self._thought)
        return self._thought

    # ── текстовые раунды (рамка) ──
    def stream_label(self) -> StreamLabel:
        """Лейбл текущего раунда; создаёт баббл лениво при первом тексте —
        до первого токена ответа рамки в ленте нет (как у Claude.ai)."""
        if self._active is None:
            self.hide_thinking()
            b = TextBubble(self)
            self._lay.addWidget(b)
            self._bubbles.append(b)
            self._active = b
        return self._active.label

    @property
    def current_bubble(self) -> TextBubble | None:
        return self._active

    def seal_text_round(self):
        """Закрывает текущий раунд: следующий текст пойдёт в НОВЫЙ баббл.
        Пустой (черновой) баббл убирается совсем — рамка вокруг пустоты
        не нужна."""
        if self._active is not None and not self._active.label._text.strip():
            self._remove_bubble(self._active)
        self._active = None

    def _remove_bubble(self, b: TextBubble):
        self._lay.removeWidget(b)
        b.hide()            # до deleteLater — иначе рисуется по старой геометрии
        b.deleteLater()
        if b in self._bubbles:
            self._bubbles.remove(b)
        if self._active is b:
            self._active = None

    def replace_round_text(self, text: str):
        """Замена текста ТЕКУЩЕГО раунда очищенной версией (trim_stream).
        Пустой текст — раунд был черновиком, баббл убираем."""
        b = self._active
        if b is None:
            return
        if text.strip():
            b.label.setText(text)
            b.label._text = text
        else:
            self._remove_bubble(b)

    def reclaim_round_text(self) -> str:
        """Забирает ВЕСЬ текст текущего раунда (например, при обнаружении
        одинокого </think>: показанное «рассуждение» переносится в мысли).
        Баббл опустошается; если текста не было — вернёт ''."""
        b = self._active
        if b is None:
            return ""
        text = b.label._text
        b.label.setText("")
        b.label._text = ""
        return text

    # ── строки вне рамки ──
    def append_tool_row(self, w: _CollapsibleToolWidget):
        self.seal_text_round()
        self._lay.addWidget(w)
        self._tool_rows.append(w)

    def append_file_card(self, card):
        self.seal_text_round()
        self._lay.addWidget(card)
        self._cards.append(card)

    # ── готовый текст (восстановление истории) ──
    def add_final_text(self, text: str):
        if text.strip():
            lbl = self.stream_label()
            lbl.append_text(text)
            lbl.finalize(False)
            self._active = None
            self._plain_text = lbl._plain_text
        # Футер с кнопками нужен и у восстановленных сообщений (пустая
        # статистика слева, кнопки копировать/повторить/проверить справа).
        self.add_stats("")

    # ── завершение ответа ──
    def finalize(self, stats: str, show_thoughts: bool):
        self.hide_thinking()
        for b in list(self._bubbles):
            if not b.label._text.strip():
                self._remove_bubble(b)
        for b in self._bubbles:
            b.label.finalize(show_thoughts)
        if self._thought is not None:
            self._thought.finalize()
        self._active = None
        self._plain_text = "\n\n".join(
            b.label._plain_text for b in self._bubbles
            if getattr(b.label, "_plain_text", "").strip()
        )
        self.add_stats(stats)

    def set_plain_text(self, text: str):
        self._plain_text = text

    def add_stats(self, text: str):
        if self._footer is None:
            self._footer = self._build_footer()
            self._lay.addWidget(self._footer)
        self._stats_lbl.setText(text)

    def _mk_act_btn(self, kind: str, tooltip: str) -> QToolButton:
        btn = GlyphButton(kind, 26)
        btn.setToolTip(tooltip)
        return btn

    def _build_footer(self) -> QWidget:
        """Футер ответа: слева статистика, справа кнопки в лёгкой рамке
        (иконки центрированы по вертикали — рамка растягивается по кнопкам
        26px + симметричные поля)."""
        p = _P()
        container = QWidget()
        container.setObjectName("bubble_footer")
        lay = QHBoxLayout(container)
        lay.setContentsMargins(0, 4, 0, 0)
        lay.setSpacing(6)

        self._stats_lbl = QLabel("")
        self._stats_lbl.setTextFormat(Qt.TextFormat.RichText)
        self._stats_lbl.setFixedHeight(24)
        self._stats_lbl.setStyleSheet(
            f"color:{p['STATS_FG']};font-size:10px;background:transparent;border:none;"
        )
        self._stats_lbl.setFont(font_mono(10))
        lay.addWidget(self._stats_lbl, 1)

        self._action_frame = QFrame()
        self._action_frame.setObjectName("action_frame")
        act_lay = QHBoxLayout(self._action_frame)
        act_lay.setContentsMargins(6, 2, 6, 2)
        act_lay.setSpacing(4)
        self.btn_copy = self._mk_act_btn("copy", "Копировать" if get_lang() == "ru" else "Copy")
        self.btn_copy.clicked.connect(self._on_copy)
        self.btn_regen = self._mk_act_btn("regen", "Повторить" if get_lang() == "ru" else "Regenerate")
        self.btn_regen.clicked.connect(self._on_regen)
        self.btn_verify = self._mk_act_btn("verify", "Перепроверить" if get_lang() == "ru" else "Verify")
        self.btn_verify.clicked.connect(self._on_verify)
        act_lay.addWidget(self.btn_copy)
        act_lay.addWidget(self.btn_regen)
        act_lay.addWidget(self.btn_verify)
        self._style_action_frame()
        lay.addWidget(self._action_frame, 0, Qt.AlignmentFlag.AlignRight)

        container.setStyleSheet(
            f"QWidget#bubble_footer {{ background: transparent; border: none; "
            f"border-top: 1px solid {p['BORDER']}; }}"
        )
        return container

    def _style_action_frame(self):
        p = _P()
        self._action_frame.setStyleSheet(f"""
            QFrame#action_frame {{
                background: transparent;
                border: 1px solid {p['BORDER']};
                border-radius: 9px;
            }}
        """)

    def _on_copy(self): self.copy_clicked.emit(self._plain_text)
    def _on_regen(self): self.regen_clicked.emit(self.msg_index)
    def _on_verify(self): self.verify_clicked.emit(self.msg_index, self._plain_text)

    # ── тема ──
    def recolor(self, p: dict):
        if self._name_lbl is not None:
            self._name_lbl.setStyleSheet(
                f"color:{p['BOT_NAME']};font-size:11px;font-weight:500;"
                f"font-family:'DejaVu Sans Mono','JetBrains Mono',monospace;"
                f"background:transparent;border:none;"
            )
        for b in self._bubbles:
            b.recolor(p)
            lbl = b.label
            lbl.setStyleSheet(
                f"QTextEdit {{ color:{p['TEXT']};background:transparent;"
                f"font-size:13px;border:none;padding:0; }}"
            )
            if getattr(lbl, "_is_markdown", False) and lbl._plain_text:
                html = _render_markdown(lbl._plain_text, p)
                lbl.setHtml(
                    f'<span style="white-space:pre-wrap;line-height:1.6;">{html}</span>'
                )
                ww = lbl.viewport().width() or lbl.width()
                if ww > 0:
                    lbl.document().setTextWidth(ww)
        if self._thought is not None:
            self._thought.recolor(p)
        if self._indicator is not None:
            self._indicator.recolor(p)
        for w in self._tool_rows:
            w.recolor(p)
        for c in self._cards:
            c.recolor()
        if self._footer is not None:
            self._footer.setStyleSheet(
                f"QWidget#bubble_footer {{ background: transparent; border: none; "
                f"border-top: 1px solid {p['BORDER']}; }}"
            )
            self._stats_lbl.setStyleSheet(
                f"color:{p['STATS_FG']};font-size:10px;background:transparent;border:none;"
            )
            self._style_action_frame()

    def animate_in(self):
        if self._fade_effect is None:
            self._fade_effect = QGraphicsOpacityEffect(self)
            self.setGraphicsEffect(self._fade_effect)
            self._fade_effect.setOpacity(0.0)
            self.show()
            self._fade_anim = QPropertyAnimation(self._fade_effect, b"opacity")
            self._fade_anim.setDuration(180)
            self._fade_anim.setStartValue(0.0)
            self._fade_anim.setEndValue(1.0)
            self._fade_anim.start()
