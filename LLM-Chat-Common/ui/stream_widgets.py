# ui/stream_widgets.py
import re

from PyQt6.QtWidgets import QWidget, QLabel, QVBoxLayout, QTextEdit, QSizePolicy
from PyQt6.QtCore import Qt, pyqtSignal, QTimer, QSize

from theme import get_palette as _P
from i18n import _t
from core.markdown import _escape, _render_markdown


class StreamLabel(QTextEdit):
    def __init__(self, parent=None):
        super().__init__(parent)
        self.setReadOnly(True)
        self.setFrameStyle(0)
        self.setVerticalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        self.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        self.setLineWrapMode(QTextEdit.LineWrapMode.WidgetWidth)
        # Небольшой (не нулевой!) отступ документа — при 0 Qt иногда обрезает
        # самые левые пиксели глифов, которые оказываются ровно на границе
        # viewport'а (визуально пропадает первая буква строки). 2px незаметны
        # глазу, но убирают обрезание.
        self.document().setDocumentMargin(2)
        # Высота строки пересчитывается сразу при изменении документа
        # (иначе при стриминге размер догонял текст с задержкой на тик)
        self.document().documentLayout().documentSizeChanged.connect(
            lambda *_: self.updateGeometry()
        )
        self.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Preferred)
        p = _P()
        self.setStyleSheet(
            f"QTextEdit {{ color:{p['TEXT']};background:transparent;"
            f"font-size:13px;border:none;padding:0;margin:0; }}"
        )
        self._text       = ""
        self._is_thought = False
        self._is_markdown = False
        self._plain_text  = ""

    def sizeHint(self):
        from PyQt6.QtCore import QSize
        doc_h = int(self.document().size().height()) + 15
        return QSize(200, max(doc_h, 20))
    def minimumSizeHint(self):
        from PyQt6.QtCore import QSize
        doc_h = int(self.document().size().height()) + 15
        return QSize(0, max(doc_h, 20))
    def setText(self, text: str): self.setPlainText(text)
    def text(self) -> str: return self.toPlainText()
    def append_text(self, chunk: str):
        self._text += chunk
        cursor = self.textCursor()
        cursor.movePosition(cursor.MoveOperation.End)
        cursor.insertText(chunk)
        self.setTextCursor(cursor)
        # follow-tail для бокса мыслей: текст дорисовывается внутри
        # ограниченного по высоте бокса — вьюпорт чата при этом НЕ двигается
        # (рост высоты строки был источником циклического дрожания при
        # стриминге; см. лог-тест /tmp/audit/test_heights_log.py)
        if getattr(self, "_follow_tail", False):
            sb = self.verticalScrollBar()
            sb.setValue(sb.maximum())
        self.updateGeometry()
    def get_text(self) -> str: return self._text
    def finalize(self, show_thoughts: bool = True):
        if self._is_thought: return
        text = self._text.replace('&lt;think&gt;', '<think>').replace('&lt;/think&gt;', '</think>')
        clean_text = re.sub(r'<think>[\s\S]*?</think>', '', text, flags=re.IGNORECASE).strip()
        clean_text = re.sub(r'\n{3,}', '\n', clean_text)
        self._plain_text = clean_text
        display_text = text if show_thoughts else clean_text
        self._is_markdown = True
        p = _P()
        html = _render_markdown(display_text, p)
        self.setStyleSheet(
            f"QTextEdit {{ color:{p['TEXT']};background:transparent;"
            f"font-size:13px;border:none;padding:0;margin:0; }}"
        )
        self.setHtml(f'<span style="white-space:pre-wrap;line-height:1.6;">{html}</span>')
        w = self.viewport().width() or self.width()
        if w > 0:
            self.document().setTextWidth(w)
        self.updateGeometry()
    def setWordWrap(self, _): pass
    def setTextFormat(self, _): pass
    def setOpenExternalLinks(self, enabled: bool): pass

class _ToolDetailBox(QTextEdit):
    """Поле для содержимого tool call/result. Раньше это был QLabel:
    он всегда растягивался под весь текст целиком и не умел
    прокручиваться в принципе, а TextSelectableByKeyboard тихо забирал
    фокус клавиатуры себе, никак не позволяя им перемещаться по тексту —
    из-за этого над зелёными полями не работали ни колесо мыши, ни
    стрелки. QTextEdit с ограниченной высотой даёт настоящую прокрутку:
    видимую полосу, работающую колёсиком, и обычную навигацию стрелками/
    Page Up/Page Down, как только пользователь кликнул в поле."""
    _MAX_H = 260

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setReadOnly(True)
        self.setFrameStyle(0)
        self.setLineWrapMode(QTextEdit.LineWrapMode.WidgetWidth)
        self.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        self.setVerticalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAsNeeded)
        self.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Fixed)
        self.document().setDocumentMargin(0)

    def set_content(self, text: str):
        self.setPlainText(text)
        self._resize_to_content()

    def _resize_to_content(self):
        w = self.viewport().width() or self.width()
        if w > 0:
            self.document().setTextWidth(w)
        doc_h = int(self.document().size().height()) + 14
        self.setFixedHeight(min(max(doc_h, 20), self._MAX_H))

    def resizeEvent(self, event):
        super().resizeEvent(event)
        self._resize_to_content()

class _CollapsibleToolWidget(QWidget):
    toggled = pyqtSignal()
    def __init__(self, header: str, detail: str, role: str = "call", parent=None):
        super().__init__(parent)
        self._detail = detail
        self._expanded = False
        self._role = role
        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(0)
        self._header_lbl = QLabel(f"▶ {_escape(header)}")
        self._header_lbl.setWordWrap(True)
        self._header_lbl.setTextFormat(Qt.TextFormat.RichText)
        self._header_lbl.setCursor(Qt.CursorShape.PointingHandCursor)
        self._detail_lbl = _ToolDetailBox()
        self._detail_lbl.setVisible(False)
        layout.addWidget(self._header_lbl)
        layout.addWidget(self._detail_lbl)
        self.recolor(_P())
    def recolor(self, p: dict):
        if self._role == "call":
            color_fg = p["TOOL_CALL"]
            color_bg = p["TOOL_CALL_BG"]
            color_br = p["TOOL_CALL_BR"]
        else:
            color_fg = p["TOOL_RES"]
            color_bg = p["TOOL_RES_BG"]
            color_br = p["TOOL_RES_BR"]
        self._header_lbl.setStyleSheet(
            f"color:{color_fg};font-size:11px;"
            f"background:{color_bg};border-left:2px solid {color_br};"
            f"padding:4px 8px;border-radius:0 6px 6px 0;margin:2px 0;"
        )
        self._detail_lbl.setStyleSheet(
            f"QTextEdit {{ color:{p['DIM']};font-size:10px;font-family:'DejaVu Sans Mono', monospace;"
            f"background:{color_bg};border:none;border-left:2px solid {color_br};"
            f"padding:6px 8px;border-radius:0 0 6px 6px;margin:0 0 2px 0; }}"
        )
    def mousePressEvent(self, event):
        if self._detail_lbl.isVisible() and self._detail_lbl.geometry().contains(event.pos()):
            super().mousePressEvent(event)
            return
        self._expanded = not self._expanded
        prefix = "▼ " if self._expanded else "▶ "
        raw = self._header_lbl.text()
        raw = re.sub(r'^[▶▼] ', '', raw)
        self._header_lbl.setText(prefix + raw)
        if self._expanded:
            self._detail_lbl.set_content(self._detail)
            self._detail_lbl.setVisible(True)
        else:
            self._detail_lbl.setVisible(False)
        super().mousePressEvent(event)
        self.toggled.emit()

THOUGHTS_MAX_H = 460   # максимальная высота развёрнутого блока мыслей


class _CollapsibleThoughtWidget(QWidget):
    toggled = pyqtSignal()
    def __init__(self, parent=None):
        super().__init__(parent)
        self._expanded = True
        self._resize_timer = QTimer(self)
        self._resize_timer.setSingleShot(True)
        self._resize_timer.setInterval(0)
        self._resize_timer.timeout.connect(self._do_resize)
        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 2, 0, 2)
        layout.setSpacing(0)
        self._header = QLabel("▼ " + _t("thoughts_header"))
        self._header.setCursor(Qt.CursorShape.PointingHandCursor)
        self._header.setWordWrap(False)
        layout.addWidget(self._header)
        self._stream = StreamLabel()
        self._stream._is_thought = True
        # ОГРАНИЧЕНИЕ ВЫСОТЫ бокса мыслей (по образцу _ToolDetailBox):
        # 2000px мысль при разворачивании давала большой прыжок вьюпорта,
        # а построчный рост при стриминге — циклическое дрожание (документ
        # QTextEdit досчитывает высоту асинхронно, виджет/строка всегда
        # отстают на одну строку). Бокс ≤ THOUGHTS_MAX_H с внутренним
        # скроллом и follow-tail: после cap высота строки КОНСТАНТНА.
        self._stream._follow_tail = True
        self._stream.setMaximumHeight(THOUGHTS_MAX_H)
        self._stream.setVerticalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAsNeeded)
        self._stream.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        layout.addWidget(self._stream)
        self.recolor(_P())
    @property
    def stream_label(self) -> "StreamLabel": return self._stream
    def request_resize(self):
        if not self._resize_timer.isActive() and self.isVisible():
            self._resize_timer.start()
    def _do_resize(self):
        if not self.isVisible(): return
        self._stream.updateGeometry()
        self.updateGeometry()
    def finalize(self):
        self._resize_timer.stop()
        text = self._stream.toPlainText()
        word_count = len(text.split())
        prefix = "▼" if self._expanded else "▶"
        self._header.setText(f"{prefix} " + _t("thoughts_words", n=word_count))
        # Блок мыслей НЕ сворачивается принудительно по завершении ответа:
        # оставляем его в том состоянии, в котором он был —
        # разворачивание/сворачивание после этого
        # (пользователем) не должно приводить к неожиданному прыжку бабла.
    def recolor(self, p: dict):
        # Мысли — тихий второстепенный текст: без курсива, без акцентных рамок.
        self._header.setStyleSheet(
            f"color:{p['THOUGHT_FG']};font-size:11px;"
            f"background:{p['THOUGHT_BG']};border-left:2px solid {p['THOUGHT_BR']};"
            f"padding:3px 8px;border-radius:0 6px 6px 0;margin:0;"
        )
        self._stream.setStyleSheet(
            f"QTextEdit {{ color:{p['THOUGHT_FG']};font-size:11px;"
            f"background:{p['THOUGHT_BG']};border-left:2px solid {p['THOUGHT_BR']};"
            f"border-top:none;padding:4px 8px;border:none; }}"
            f"QScrollBar:vertical {{ background: transparent; width: 6px; margin: 2px 1px; }}"
            f"QScrollBar::handle:vertical {{ background: {p['THOUGHT_BR']}; border-radius: 3px; min-height: 24px; }}"
            f"QScrollBar::add-line:vertical, QScrollBar::sub-line:vertical {{ height: 0; }}"
            f"QScrollBar::add-page:vertical, QScrollBar::sub-page:vertical {{ background: transparent; }}"
        )
    def _toggle(self):
        # ВАЖНО: только видимое изменение (скрыть/показать поток) и сигнал.
        # Никаких layout().invalidate()/activate()/updateGeometry() здесь:
        # активация СВОЕГО layout на устаревшей (досверточной) высоте виджета
        # растягивала заголовок на освободившиеся ~200px и сдвигала соседей —
        # обработчик toggled в ChatArea замерял якорь по этому промежуточному
        # состоянию и компенсировал мусорную дельту (контент «подпрыгивал»
        # на кадр при сворачивании). Всю усадку делает _sync_layout ленты.
        self._expanded = not self._expanded
        self._stream.setVisible(self._expanded)
        raw = self._header.text()
        raw = re.sub(r'^[▶▼] ', '', raw)
        self._header.setText(("▼ " if self._expanded else "▶ ") + raw)
        self.toggled.emit()
    def mousePressEvent(self, event):
        header_rect = self._header.geometry()
        if header_rect.contains(event.pos()):
            self._toggle()
        super().mousePressEvent(event)

class ThinkingIndicator(QLabel):
    _FRAMES = "⠋⠙⠹⠸⠼⠴⠦⠧⠇⠏"

    def __init__(self, text: str = "Думаю", parent=None):
        super().__init__(parent)
        self._base_text = text
        self._frame_idx = 0
        self.recolor(_P())
        self._timer = QTimer(self)
        self._timer.setInterval(120)
        self._timer.timeout.connect(self._next_frame)
        self._update_text()

    def start(self):
        self._timer.start()

    def stop(self):
        self._timer.stop()

    def _next_frame(self):
        self._frame_idx = (self._frame_idx + 1) % len(self._FRAMES)
        self._update_text()

    def _update_text(self):
        frame = self._FRAMES[self._frame_idx]
        self.setText(f"{frame} {self._base_text}…")

    def recolor(self, p: dict):
        self.setStyleSheet(
            f"color:{p['STATS_FG']};font-size:12px;background:transparent;border:none;"
        )
