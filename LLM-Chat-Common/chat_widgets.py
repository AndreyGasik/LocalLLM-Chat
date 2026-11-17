# LLM-Chat-Common/chat_widgets.py
"""Виджеты чата единого приложения LLM Chat.

Правки вносятся ТОЛЬКО здесь — единый источник для обоих бэкендов.
"""
from __future__ import annotations

from html import escape

from PyQt6.QtWidgets import QToolButton, QMenu, QWidget, QHBoxLayout, QLabel
from PyQt6.QtCore import pyqtSignal, Qt, QSize, QPointF
from PyQt6.QtGui import QAction, QPainter, QPen, QPolygonF, QColor


def style_menu(menu: QMenu) -> None:
    """Popup-меню со скруглёнными углами: окно меню прозрачное, фон рисует QSS
    (правила QMenu живут в Aurora FORM_QSS на уровне окна/приложения)."""
    menu.setWindowFlags(menu.windowFlags()
                        | Qt.WindowType.FramelessWindowHint
                        | Qt.WindowType.NoDropShadowWindowHint)
    menu.setAttribute(Qt.WidgetAttribute.WA_TranslucentBackground)


class ModelMenuButton(QToolButton):
    """Кнопка выбора модели с выпадающим QMenu — единая для обеих версий
    (в Ollama была QPushButton-версия ModelSelector, в Llama — ModelPicker).

    QMenu вместо нативного попапа QComboBox: попап QMenu умеет скруглять
    углы, а стандартный попап QComboBox рисуется системным style-engine и
    оставляет чёрные квадратные углы поверх скруглённого фона окна.

    Минимальный API QComboBox, которым пользуется остальной код:
    clear / addItem / currentText / findText / setCurrentIndex /
    currentTextChanged. Ширина — константы, НЕ производные от текста:
    длинное имя модели не должно раздувать минимальную ширину сайдбара
    (реальную ширину даёт layout, текст подгоняется в _refresh_text).
    """

    currentTextChanged = pyqtSignal(str)

    # Горизонтальный резерв под оформление кнопки (QSS #modelPicker:
    # padding 4px 28px 4px 12px = 40px + рамка 2px) — нарисованную пером
    # стрелку рисуем сами, menu-indicator выключен в QSS.
    _CHROME_RESERVE = 46
    _HINT_WIDTH = 240
    _MIN_WIDTH = 80

    def __init__(self, parent=None):
        super().__init__(parent)
        self._items: list[str] = []
        self._current: str = ""
        self.setObjectName("modelPicker")
        self.setPopupMode(QToolButton.ToolButtonPopupMode.InstantPopup)
        self.setToolButtonStyle(Qt.ToolButtonStyle.ToolButtonTextOnly)
        self._menu = QMenu(self)
        style_menu(self._menu)
        self.setMenu(self._menu)
        self._refresh_text()

    # ── размеры не зависят от текста ──
    def sizeHint(self):
        return QSize(self._HINT_WIDTH, max(28, self.fontMetrics().height() + 14))

    def minimumSizeHint(self):
        return QSize(self._MIN_WIDTH, max(28, self.fontMetrics().height() + 14))

    # ── минимальный API QComboBox ──
    def clear(self):
        self._items = []
        self._current = ""
        self._menu.clear()
        self._refresh_text()

    def addItem(self, text: str):
        self._items.append(text)
        action = QAction(text, self._menu)
        action.triggered.connect(lambda checked=False, t=text: self._select(t))
        self._menu.addAction(action)
        if not self._current:
            self._current = text
            self._refresh_text()
            self.currentTextChanged.emit(text)

    def _select(self, text: str):
        self._current = text
        self._refresh_text()
        self.currentTextChanged.emit(text)

    def currentText(self) -> str:
        return self._current

    def findText(self, text: str) -> int:
        try:
            return self._items.index(text)
        except ValueError:
            return -1

    def setCurrentIndex(self, idx: int):
        if 0 <= idx < len(self._items):
            self._current = self._items[idx]
            self._refresh_text()
            self.currentTextChanged.emit(self._current)

    def apply_theme(self):
        """Совместимость с вызывающим кодом: цвета меню приходят по каскаду
        из Aurora FORM_QSS (окно/приложение) — достаточно флагов попапа."""
        style_menu(self._menu)
        self._menu.setStyleSheet("")

    # ── текст и стрелка ──
    def _refresh_text(self):
        label = self._current or "…"
        metrics = self.fontMetrics()
        elided = metrics.elidedText(
            label, Qt.TextElideMode.ElideMiddle,
            max(self.width() - self._CHROME_RESERVE, 60)
        )
        self.setText(elided)
        self.setToolTip(self._current)
        self.update()

    def resizeEvent(self, event):
        super().resizeEvent(event)
        self._refresh_text()

    def paintEvent(self, event):
        super().paintEvent(event)
        p = QPainter(self)
        p.setRenderHint(QPainter.RenderHint.Antialiasing)
        pen = QPen(QColor(140, 140, 148), 1.6)
        pen.setCapStyle(Qt.PenCapStyle.RoundCap)
        pen.setJoinStyle(Qt.PenJoinStyle.RoundJoin)
        p.setPen(pen)
        cx, cy = self.width() - 16, self.height() / 2
        p.drawPolyline(QPolygonF([QPointF(cx - 3.5, cy - 1.8), QPointF(cx, cy + 1.8),
                                  QPointF(cx + 3.5, cy - 1.8)]))
        p.end()


class ErrorRow(QWidget):
    """Строка ошибки в чат-ленте (обе версии). Отдельный класс вместо
    duck-typing `container.recolor = ...`: apply_theme находит метод
    recolor у всех элементов ленты через isinstance/hasattr одинаково."""

    def __init__(self, err: str, parent=None):
        super().__init__(parent)
        lay = QHBoxLayout(self)
        lay.setContentsMargins(0, 0, 0, 0)
        self._lbl = QLabel(escape(err))
        self._lbl.setWordWrap(True)
        self._lbl.setTextFormat(Qt.TextFormat.RichText)
        lay.addWidget(self._lbl)

    def recolor(self, p: dict):
        self._lbl.setStyleSheet(
            f"color:{p['ERROR']};font-size:12px;"
            f"background:{p['BOT_BG']};border-left:3px solid {p['ERROR']};"
            f"padding:8px 12px;border-radius:8px;margin:4px 10px;"
        )
