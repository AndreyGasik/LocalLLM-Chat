# LLM-Chat-Common/aurora.py
"""
Aurora UI — общая дизайн-система единого приложения LLM Chat.

Направление «приборный пульт» (unslop, 2026-11): нейтральный графит +
один тёплый янтарный акцент, плоские поверхности без градиентов и свечения,
перьевые глифы вместо эмодзи, моно-цифры метрик.

Единый источник правок: изменения дизайна вносятся ТОЛЬКО сюда;
потребитель — app/ (тонкая склейка app/theme.py).

Подключение в приложении:
    sys.path.insert(0, <путь к LLM-Chat-Common>)
    import aurora
    aurora.set_theme("dark")            # смена темы (окна — через retheme())
    window.setStyleSheet(aurora.FORM_QSS)
"""
from __future__ import annotations

import math
import os
import re
import tempfile

from PyQt6.QtWidgets import (
    QApplication, QWidget, QDialog, QPushButton, QAbstractButton, QHeaderView,
    QTableWidget, QAbstractItemView, QFrame, QVBoxLayout, QHBoxLayout, QLabel,
)
from PyQt6.QtCore import (
    Qt, QRectF, QPointF, QSize, QObject, QEvent, QRect, QPoint,
)
from PyQt6.QtGui import (
    QFont, QFontDatabase, QFontMetrics, QColor, QPixmap, QPainter, QPainterPath, QPen,
    QPolygonF, QIcon,
)

# ── 1. ТОКЕНЫ ─────────────────────────────────────────────────────
C_TEXT    = "#ededed"
C_DIM     = "#a1a1a6"
C_FAINT   = "#737373"
C_ACCENT  = "#eda23c"     # янтарь — единственный акцент
C_ACCENT2 = "#4cc38a"     # зелёный «живой» статус
C_WARN    = "#eda23c"
C_DANGER  = "#e5484d"
C_OK      = "#4cc38a"

# Плоские кнопки: пары (фон, текст) вычисляются по текущей теме в _kind_colors().


def kind_colors(kind: str):
    """(фон, текст) для PrimaryButton по текущей теме. Никаких градиентов.
    accent — янтарь бренда (текст контрастный под заливку);
    primary/success — off-white на тёмной теме, «чернила» на светлой."""
    if kind == "accent":
        return QColor(C_ACCENT), QColor(T("sel_text"))
    if kind == "danger":
        return QColor(C_DANGER), QColor("#ffffff")
    if theme_name() == "dark":
        return QColor("#ededed"), QColor("#171717")
    return QColor(24, 24, 27), QColor("#ffffff")

# ── 1b. ТЕМЫ ──────────────────────────────────────────────────────
# ink — цвет «чернил»: поверхности и рамки это ink с альфой (белый на тёмной, тёмный на светлой).
THEMES = {
    "dark": dict(
        ink=(255, 255, 255), text="#ededed", dim="#a1a1a6", faint="#737373",
        accent="#eda23c", accent2="#4cc38a", warn="#eda23c", danger="#e5484d", ok="#4cc38a",
        # приглушённый янтарь: заливка «да/нет»-констролов (чекбоксы, кнопка «Да»)
        # — полный акцент на таких площадях слепит
        accent_muted="#cf9136",
        frame_top=(20, 20, 21, 255), frame_bot=(20, 20, 21, 255), border_a=(26, 26), shadow_a=18, notch=(255, 255, 255, 30),
        popup="#1c1c1e", msg_bg="#19191b", win_glyph="#a1a1a6", badge_fg="#a1a1a6",
        sel_text="#201203"),
    "light": dict(
        ink=(24, 24, 27), text="#171717", dim="#525252", faint="#a1a1a6",
        accent="#b45309", accent2="#16a34a", warn="#b45309", danger="#dc2626", ok="#16a34a",
        accent_muted="#b45309",
        frame_top=(250, 250, 250, 255), frame_bot=(250, 250, 250, 255), border_a=(20, 20), shadow_a=12, notch=(24, 24, 27, 26),
        popup="#ffffff", msg_bg="#ffffff", win_glyph="#737373", badge_fg="#525252",
        sel_text="#ffffff"),
}
_theme_name = "dark"

SHADOW_M = 16      # поле вокруг окна под тень
BODY_R   = 16      # радиус скругления окна
ROW_R    = 8       # радиус строки списка/таблицы
ROW_H    = 54


# ── 2. БАЗОВЫЕ ХЕЛПЕРЫ ────────────────────────────────────────────
def font(px: float, weight=QFont.Weight.Normal, spacing: float = 0.0) -> QFont:
    """Шрифт приложения (Inter) нужного размера в пикселях. Табличные цифры включены."""
    f = QFont(QApplication.font())
    f.setPixelSize(int(px))
    f.setWeight(weight)
    if spacing:
        f.setLetterSpacing(QFont.SpacingType.AbsoluteSpacing, spacing)
    try:                                   # tnum: цифры одной ширины (Qt >= 6.7)
        f.setFeature(QFont.Tag("tnum"), 1)
    except Exception:
        pass
    return f


def font_mono(px: float, weight=QFont.Weight.Normal) -> QFont:
    """Моно-шрифт для цифр и метрик (сигнатура «приборного пульта»).
    JetBrains Mono → IBM Plex Mono → DejaVu Sans Mono (есть везде на Linux)."""
    fams = set(QFontDatabase.families())
    fam = next((c for c in ("JetBrains Mono", "IBM Plex Mono", "DejaVu Sans Mono")
                if c in fams), "DejaVu Sans Mono")
    f = QFont(fam)
    f.setPixelSize(int(px))
    f.setWeight(weight)
    f.setStyleHint(QFont.StyleHint.Monospace)
    try:
        f.setFeature(QFont.Tag("tnum"), 1)
    except Exception:
        pass
    return f


def qc(hex_or_color, alpha: int | None = None) -> QColor:
    c = QColor(hex_or_color)
    if alpha is not None:
        c.setAlpha(alpha)
    return c


def T(key: str):
    """Токен текущей темы: T("popup"), T("frame_top") …"""
    return THEMES[_theme_name][key]


def theme_name() -> str:
    return _theme_name


def ink(alpha: int) -> QColor:
    """Поверхность/рамка: «чернила» темы с альфой (тёмная: белый, светлая: тёмно-синий)."""
    r, g, b = T("ink")
    return QColor(r, g, b, alpha)


def ink_css(alpha: int) -> str:
    r, g, b = T("ink")
    return f"rgba({r},{g},{b},{alpha})"


def accent_css(alpha: int) -> str:
    c = QColor(C_ACCENT)
    return f"rgba({c.red()},{c.green()},{c.blue()},{alpha})"


def set_theme(name: str) -> None:
    """Переключает тему: пересчитывает C_* и QSS-константы. Окна пере-красьте через retheme()."""
    global _theme_name, C_TEXT, C_DIM, C_FAINT, C_ACCENT, C_ACCENT2, C_WARN, C_DANGER, C_OK
    global FORM_QSS, TABLE_QSS, LIST_QSS, LIST_INDICATOR_QSS
    if name not in THEMES:
        return
    _theme_name = name
    th = THEMES[name]
    C_TEXT, C_DIM, C_FAINT = th["text"], th["dim"], th["faint"]
    C_ACCENT, C_ACCENT2, C_WARN = th["accent"], th["accent2"], th["warn"]
    C_DANGER, C_OK = th["danger"], th["ok"]
    ensure_check_icon()          # цвет галочки чекбокса зависит от темы
    FORM_QSS, TABLE_QSS = form_qss(), table_qss()
    LIST_QSS, LIST_INDICATOR_QSS = list_qss(), list_indicator_qss()


def make_icon(bg_hex: str, draw) -> QIcon:
    """Иконка приложения: скруглённый квадрат (22 %) + любой глиф.
    draw(painter) рисует на холсте 128×128."""
    size = 128
    pix = QPixmap(size, size)
    pix.fill(Qt.GlobalColor.transparent)
    p = QPainter(pix)
    p.setRenderHint(QPainter.RenderHint.Antialiasing)
    path = QPainterPath()
    path.addRoundedRect(0, 0, size, size, size * 0.22, size * 0.22)
    p.setPen(Qt.PenStyle.NoPen)
    p.setBrush(QColor(bg_hex))
    p.drawPath(path)
    draw(p)
    p.end()
    return QIcon(pix)


def paint_row_pill(p: QPainter, rect: QRectF, col: int, ncols: int,
                   selected: bool, hovered: bool):
    """Фон строки списка/таблицы — одна «пилюля» на все колонки.
    Вызывать из QStyledItemDelegate.paint() для КАЖДОЙ ячейки.
    Трюк: рисуем скруглённый прямоугольник, выходящий за границы ячейки, и обрезаем
    клипом до ячейки — скругления остаются только на крайних колонках."""
    R = ROW_R
    row = QRectF(rect.left(), rect.top() + 2, rect.width(), rect.height() - 4)
    first, last = col == 0, col == ncols - 1
    ext = row.adjusted(0 if first else -R * 2, 0, 0 if last else R * 2, 0)
    p.setClipRect(rect)
    if selected:
        # Тихое выделение: шаг поверхности + волосяная акцентная рамка.
        p.setBrush(ink(14))
        p.setPen(QPen(qc(C_ACCENT, 120), 1))
        p.drawRoundedRect(ext.adjusted(0.5, 0.5, -0.5, -0.5), R, R)
    elif hovered:
        p.setPen(Qt.PenStyle.NoPen)
        p.setBrush(ink(8))
        p.drawRoundedRect(ext, R, R)


def paint_selection_marker(p: QPainter, rect: QRectF, cy: float):
    """Акцентная полоска слева у выбранной строки (в первой колонке)."""
    bar = QRectF(rect.left() + 5, cy - 10, 3, 20)
    p.setPen(Qt.PenStyle.NoPen)
    p.setBrush(QColor(C_ACCENT))
    p.drawRoundedRect(bar, 1.5, 1.5)


# ── 3. ОКНО ───────────────────────────────────────────────────────
class DragArea(QWidget):
    """Перетаскивание окна за заголовок (Wayland: startSystemMove)."""
    def __init__(self, parent):
        super().__init__(parent)
        self._p, self._start = parent, None

    def mousePressEvent(self, e):
        if e.button() == Qt.MouseButton.LeftButton:
            self._start = e.globalPosition().toPoint()
            wh = self.windowHandle()
            if wh and hasattr(wh, 'startSystemMove'):
                wh.startSystemMove()
            else:
                self._p._offset = e.globalPosition().toPoint() - self._p.pos()

    def mouseMoveEvent(self, e):
        if e.buttons() == Qt.MouseButton.LeftButton and self._start and getattr(self._p, '_offset', None):
            if (e.globalPosition().toPoint() - self._start).manhattanLength() > 5:
                self._p.move(e.globalPosition().toPoint() - self._p._offset)


class WinButton(QAbstractButton):
    """Кнопка окна 28×28: kind = 'min' | 'max' | 'close' (рисуется вручную)."""
    def __init__(self, kind: str, parent=None):
        super().__init__(parent)
        self.kind = kind
        self.setFixedSize(28, 28)
        self.setCursor(Qt.CursorShape.PointingHandCursor)
        self.setFocusPolicy(Qt.FocusPolicy.NoFocus)

    def enterEvent(self, e):
        self.update(); super().enterEvent(e)

    def leaveEvent(self, e):
        self.update(); super().leaveEvent(e)

    def paintEvent(self, _):
        p = QPainter(self)
        p.setRenderHint(QPainter.RenderHint.Antialiasing)
        hov, down, close = self.underMouse(), self.isDown(), self.kind == "close"
        if hov:
            bg = QColor(244, 63, 94, 190 if down else 235) if close else ink(34 if down else 22)
            p.setPen(Qt.PenStyle.NoPen)
            p.setBrush(bg)
            p.drawRoundedRect(QRectF(self.rect()).adjusted(2, 2, -2, -2), 8, 8)
        pen = QPen(QColor("#ffffff") if (hov and close) else QColor(T("win_glyph")), 1.5)
        pen.setCapStyle(Qt.PenCapStyle.RoundCap)
        pen.setJoinStyle(Qt.PenJoinStyle.RoundJoin)
        p.setPen(pen)
        c = QPointF(self.width() / 2, self.height() / 2)
        if close:
            d = 4.0
            p.drawLine(QPointF(c.x() - d, c.y() - d), QPointF(c.x() + d, c.y() + d))
            p.drawLine(QPointF(c.x() - d, c.y() + d), QPointF(c.x() + d, c.y() - d))
        elif self.kind == "max":
            p.setBrush(Qt.BrushStyle.NoBrush)
            if self.window().isMaximized():          # «восстановить»: два квадрата
                p.drawRoundedRect(QRectF(c.x() - 4.5, c.y() - 2.5, 7, 7), 1.5, 1.5)
                p.drawLine(QPointF(c.x() - 2.5, c.y() - 4.5), QPointF(c.x() + 4.5, c.y() - 4.5))
                p.drawLine(QPointF(c.x() + 4.5, c.y() - 4.5), QPointF(c.x() + 4.5, c.y() + 2.5))
            else:                                    # «развернуть»: один квадрат
                p.drawRoundedRect(QRectF(c.x() - 4.5, c.y() - 4.5, 9, 9), 2, 2)
        else:
            p.drawLine(QPointF(c.x() - 4.5, c.y() + 0.5), QPointF(c.x() + 4.5, c.y() + 0.5))
        p.end()


class _TitleDblClick(QObject):
    """Фильтр: двойной клик по заголовку = развернуть/восстановить; в развёрнутом виде
    заголовок не «тащит» окно."""
    def __init__(self, win):
        super().__init__(win)
        self._win = win

    def eventFilter(self, obj, e):
        t = e.type()
        try:
            if t == QEvent.Type.MouseButtonDblClick and e.button() == Qt.MouseButton.LeftButton:
                self._win.toggle_maximize()
                return True
            if t in (QEvent.Type.MouseButtonPress, QEvent.Type.MouseMove) and self._win.isMaximized():
                return True
        except RuntimeError:
            pass          # окно уже удалено (выход из приложения) — фильтр просто пропускает событие
        return False


class _AuroraFrame:
    """Общая рамка Aurora: тень, градиентный фон, свечение, рамка, заголовок.
    Подмешивается и в окно (AuroraWindow), и в модальный диалог (AuroraDialog).

        class MyApp(A.AuroraWindow):
            def __init__(self):
                super().__init__("Мой скрипт", size=(600, 740), tag="PRO", icon=my_icon)
                self.body.addWidget(...)      # содержимое — в self.body (QVBoxLayout)
    """
    def __init__(self, title: str, size=(600, 740), tag: str | None = None,
                 icon: QIcon | None = None, on_top: bool = True,
                 dialog: bool = False, parent=None, resizable: bool = False):
        super().__init__(parent)
        self._bg: QPixmap | None = None
        self._offset = None
        self._resizable = resizable and not dialog
        self.setWindowTitle(title)
        self.resize(*size)
        flags = Qt.WindowType.FramelessWindowHint
        if dialog:
            flags |= Qt.WindowType.Dialog
        if on_top:
            flags |= Qt.WindowType.WindowStaysOnTopHint
        self.setWindowFlags(flags)
        self.setAttribute(Qt.WidgetAttribute.WA_TranslucentBackground)

        root = QVBoxLayout(self)
        root.setContentsMargins(SHADOW_M, SHADOW_M, SHADOW_M, SHADOW_M)
        root.setSpacing(0)

        self.title_bar = DragArea(self)
        self.title_bar.setFixedHeight(52)
        self.title_layout = QHBoxLayout(self.title_bar)
        self.title_layout.setContentsMargins(18, 0, 12, 0)
        self.title_layout.setSpacing(10)
        if icon is not None:
            ico = QLabel()
            ico.setPixmap(icon.pixmap(QSize(24, 24)))
            ico.setFixedSize(24, 24)
            self.title_layout.addWidget(ico)
        lbl = QLabel(title)
        lbl.setFont(font(14, QFont.Weight.Medium))
        self.title_label = lbl
        self.title_layout.addWidget(lbl)
        self.title_tag = None
        if tag:
            t = QLabel(tag)
            t.setFont(font(10, QFont.Weight.Medium))
            self.title_tag = t
            self.title_layout.addWidget(t)
        self.title_layout.addStretch()
        self._ctrl_index = self.title_layout.count()      # сюда add_title_widget() вставляет свои кнопки
        b_close = WinButton("close")
        b_close.clicked.connect(self.close)
        self.btn_max = None
        if not dialog:                       # у диалога кнопок «свернуть/развернуть» нет
            b_min = WinButton("min")
            b_min.clicked.connect(self.showMinimized)
            self.title_layout.addWidget(b_min)
            if self._resizable:
                self.btn_max = WinButton("max")
                self.btn_max.clicked.connect(self.toggle_maximize)
                self.title_layout.addWidget(self.btn_max)
        self.title_layout.addWidget(b_close)
        root.addWidget(self.title_bar)
        self._apply_title_style()
        if self._resizable:
            self.setMouseTracking(True)
            self._title_dbl = _TitleDblClick(self)
            self.title_bar.installEventFilter(self._title_dbl)

        self.body = QVBoxLayout()          # сюда кладите всё содержимое
        self.body.setContentsMargins(0, 0, 0, 0)
        self.body.setSpacing(0)
        root.addLayout(self.body, 1)

    # ── тема и заголовок ───────────────────────────────────────────
    def _apply_title_style(self):
        self.title_label.setStyleSheet(f"color: {C_TEXT};")
        if self.title_tag is not None:
            # тихий бейдж-приложение: мутный текст на матовой плитке, без акцента
            self.title_tag.setStyleSheet(
                f"color: {C_DIM}; background-color: {ink_css(14)};"
                "border-radius: 6px; padding: 2px 7px;")

    def retheme(self):
        """Вызвать после A.set_theme(): перерисовывает фон окна, заголовок и кнопки заголовка."""
        self._apply_title_style()
        self._build_bg()
        self.update()
        for w in self.title_bar.findChildren(QAbstractButton):
            w.update()

    def add_title_widget(self, w: QWidget):
        """Добавляет виджет в заголовок слева от кнопок окна (тема, язык, меню …)."""
        self.title_layout.insertWidget(self._ctrl_index, w)
        self._ctrl_index += 1

    # ── развернуть / ресайз за края ────────────────────────────────
    def _is_max(self) -> bool:
        return self.isMaximized() or self.isFullScreen()

    def toggle_maximize(self):
        if self._is_max():
            self.showNormal()
        else:
            self.showMaximized()

    def changeEvent(self, e):
        super().changeEvent(e)
        if e.type() == QEvent.Type.WindowStateChange and self._resizable:
            m = 0 if self._is_max() else SHADOW_M
            self.layout().setContentsMargins(m, m, m, m)
            self._build_bg()
            self.update()
            if self.btn_max is not None:
                self.btn_max.update()

    def _edges_at(self, pos):
        if not self._resizable or self._is_max():
            return Qt.Edge(0)
        m, w, h = SHADOW_M, self.width(), self.height()
        edges = Qt.Edge(0)
        if pos.x() < m:
            edges |= Qt.Edge.LeftEdge
        elif pos.x() >= w - m:
            edges |= Qt.Edge.RightEdge
        if pos.y() < m:
            edges |= Qt.Edge.TopEdge
        elif pos.y() >= h - m:
            edges |= Qt.Edge.BottomEdge
        return edges

    def mousePressEvent(self, e):
        if self._resizable and e.button() == Qt.MouseButton.LeftButton:
            ed = self._edges_at(e.position().toPoint())
            wh = self.windowHandle()
            if ed and wh is not None:
                wh.startSystemResize(ed)
                e.accept()
                return
        super().mousePressEvent(e)

    # фон рисуется один раз на resize и кэшируется в QPixmap
    def _build_bg(self):
        w, h = self.width(), self.height()
        dpr = self.devicePixelRatioF()
        pix = QPixmap(max(1, int(w * dpr)), max(1, int(h * dpr)))
        pix.setDevicePixelRatio(dpr)
        pix.fill(Qt.GlobalColor.transparent)
        p = QPainter(pix)
        p.setRenderHint(QPainter.RenderHint.Antialiasing)
        full = self._resizable and self._is_max()
        M, R = (0, 0) if full else (SHADOW_M, BODY_R)
        body = QRectF(M, M, w - 2 * M, h - 2 * M)

        p.setPen(Qt.PenStyle.NoPen)
        for i in range(M):                                   # тень: мягкая, нейтральная
            a = int(T("shadow_a") * (1 - i / M) ** 2)
            if a > 0:
                p.setBrush(QColor(0, 0, 0, a))
                p.drawRoundedRect(body.adjusted(-i, -i, i, i).translated(0, 4), R + i, R + i)

        # плоский фон: одна поверхность, без градиента и без свечения
        p.setBrush(QColor(*T("frame_top")[:3], T("frame_top")[3]))
        p.drawRoundedRect(body, R, R)

        if not full:                                         # волосяная рамка
            p.setPen(QPen(ink(T("border_a")[0]), 1))
            p.setBrush(Qt.BrushStyle.NoBrush)
            p.drawRoundedRect(body.adjusted(0.5, 0.5, -0.5, -0.5), R, R)
        p.end()
        self._bg = pix

    def resizeEvent(self, e):
        super().resizeEvent(e)
        self._build_bg()

    def paintEvent(self, _):
        if self._bg is None:
            self._build_bg()
        p = QPainter(self)
        p.drawPixmap(0, 0, self._bg)
        p.end()


class AuroraWindow(_AuroraFrame, QWidget):
    """Окно: super().__init__("Заголовок", size=(W+32, H+32), tag=..., icon=...)."""


class AuroraDialog(_AuroraFrame, QDialog):
    """Модальный диалог в стиле Aurora (без системной рамки).
    exec() / accept() / reject() работают как у QDialog; содержимое — в self.body."""
    def __init__(self, title: str, size=(600, 400), tag: str | None = None,
                 icon: QIcon | None = None, parent=None):
        super().__init__(title, size=size, tag=tag, icon=icon,
                         on_top=False, dialog=True, parent=parent)


# ── 4. КНОПКИ И ИНДИКАТОРЫ ────────────────────────────────────────
class PrimaryButton(QPushButton):
    """Главная кнопка: плоская заливка (без градиентов и бликов), иконка-стоп (опц.),
    keycap-подсказка (опц.). kind: 'accent' | 'primary' | 'danger' | 'success'."""
    def __init__(self, text: str, kind: str = "accent", hint: str | None = None,
                 stop_icon: bool = False, parent=None):
        super().__init__(text, parent)
        self.kind, self.hint, self.stop_icon = kind, hint, stop_icon
        self.setCursor(Qt.CursorShape.PointingHandCursor)
        self.setFocusPolicy(Qt.FocusPolicy.NoFocus)
        self.setFixedHeight(40)

    def enterEvent(self, e):
        self.update(); super().enterEvent(e)

    def leaveEvent(self, e):
        self.update(); super().leaveEvent(e)

    def paintEvent(self, _):
        p = QPainter(self)
        p.setRenderHint(QPainter.RenderHint.Antialiasing)
        p.setRenderHint(QPainter.RenderHint.TextAntialiasing)
        r = QRectF(self.rect()).adjusted(0.5, 0.5, -0.5, -0.5)
        en, hov, down = self.isEnabled(), self.underMouse(), self.isDown()
        if en:
            bg, fg = kind_colors(self.kind)
            if hov:
                bg = bg.lighter(106)
            if down:
                bg = bg.darker(108)
            p.setPen(Qt.PenStyle.NoPen)
            p.setBrush(bg)
        else:
            p.setPen(QPen(ink(14), 1))
            p.setBrush(ink(8))
            fg = QColor(C_FAINT)
        p.drawRoundedRect(r, 10, 10)

        f = font(13, QFont.Weight.Medium)
        p.setFont(f)
        text = self.text()
        tw = QFontMetrics(f).horizontalAdvance(text)
        icon_w = 26 if (en and self.stop_icon) else 0
        x0 = (self.width() - (tw + icon_w)) / 2
        cy = self.height() / 2
        if icon_w:
            pen = QPen(fg, 1.7); pen.setCapStyle(Qt.PenCapStyle.RoundCap)
            p.setPen(pen); p.setBrush(Qt.BrushStyle.NoBrush)
            p.drawEllipse(QPointF(x0 + 8, cy), 7.5, 7.5)
            p.drawLine(QPointF(x0 + 5.2, cy - 2.8), QPointF(x0 + 10.8, cy + 2.8))
            p.drawLine(QPointF(x0 + 5.2, cy + 2.8), QPointF(x0 + 10.8, cy - 2.8))
        p.setPen(fg)
        p.drawText(QRectF(x0 + icon_w, 0, tw + 4, self.height()),
                   Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignVCenter, text)
        if en and self.hint:                                       # keycap
            p.setFont(font_mono(10))
            kw = QFontMetrics(font_mono(10)).horizontalAdvance(self.hint) + 16
            kr = QRectF(self.width() - 14 - kw, cy - 10, kw, 20)
            p.setPen(QPen(fg, 1))
            p.setBrush(Qt.BrushStyle.NoBrush)
            p.drawRoundedRect(kr, 5, 5)
            p.drawText(kr, Qt.AlignmentFlag.AlignCenter, self.hint)
        p.end()


class GhostButton(QPushButton):
    """Вторичная кнопка: матовая плитка с тонкой рамкой. Checkable-кнопки
    (переключатель бэкенда, тумблеры инструментов, «История») во включённом
    состоянии получают волосяную янтарную рамку и шаг поверхности вверх —
    иначе не видно, какая кнопка нажата."""
    def __init__(self, text: str, parent=None):
        super().__init__(text, parent)
        self.setCursor(Qt.CursorShape.PointingHandCursor)
        self.setFocusPolicy(Qt.FocusPolicy.NoFocus)
        self.setFixedHeight(36)

    def enterEvent(self, e):
        self.update(); super().enterEvent(e)

    def leaveEvent(self, e):
        self.update(); super().leaveEvent(e)

    def paintEvent(self, _):
        p = QPainter(self)
        p.setRenderHint(QPainter.RenderHint.Antialiasing)
        p.setRenderHint(QPainter.RenderHint.TextAntialiasing)
        hov, down, en = self.underMouse(), self.isDown(), self.isEnabled()
        chk = self.isCheckable() and self.isChecked()
        if chk:
            p.setPen(QPen(qc(C_ACCENT, 170 if hov else 120), 1))
            p.setBrush(ink(24 if down else ((16 if hov else 12) if en else 6)))
        else:
            a = 24 if down else (14 if hov else 8)
            p.setPen(QPen(ink(24 if en else 12), 1))
            p.setBrush(ink(a if en else 6))
        p.drawRoundedRect(QRectF(self.rect()).adjusted(0.5, 0.5, -0.5, -0.5), 8, 8)
        p.setFont(font(12.5, QFont.Weight.Medium))
        p.setPen(QColor((C_ACCENT if chk else C_TEXT) if en else C_FAINT))
        p.drawText(QRectF(self.rect()), Qt.AlignmentFlag.AlignCenter, self.text())
        p.end()


# ── 5. ТАБЛИЦА ────────────────────────────────────────────────────
class AuroraHeader(QHeaderView):
    """Плоский заголовок: sentence case 11px, акцентная стрелка у активной колонки.
    aligns — 'left'|'center' на колонку; pads — левый отступ для 'left';
    sortable — индексы кликабельных колонок."""
    def __init__(self, parent=None, sortable=(1, 2), aligns=("left", "center", "left"), pads=(16, 0, 14)):
        super().__init__(Qt.Orientation.Horizontal, parent)
        self.sortable, self.aligns, self.pads = tuple(sortable), aligns, pads
        self.sort_col, self.sort_asc = -1, False
        self.setSectionsClickable(True)
        self.setHighlightSections(False)
        self.setMouseTracking(True)
        self.setFixedHeight(36)

    def set_sort(self, col: int, asc: bool):
        """Публичный API сортируемого заголовка: активная колонка получает
        акцентную стрелку (сортировку данных делает вызывающая сторона)."""
        self.sort_col, self.sort_asc = col, asc
        self.viewport().update()

    def mouseMoveEvent(self, e):
        idx = self.logicalIndexAt(e.position().toPoint())
        self.viewport().setCursor(Qt.CursorShape.PointingHandCursor if idx in self.sortable
                                  else Qt.CursorShape.ArrowCursor)
        super().mouseMoveEvent(e)

    def paintSection(self, p, rect, i):
        p.save()
        p.setRenderHint(QPainter.RenderHint.TextAntialiasing)
        p.setRenderHint(QPainter.RenderHint.Antialiasing)
        text = str(self.model().headerData(i, Qt.Orientation.Horizontal, Qt.ItemDataRole.DisplayRole) or "")
        active = i == self.sort_col
        f = font(11, QFont.Weight.Medium)
        p.setFont(f)
        tw = QFontMetrics(f).horizontalAdvance(text)
        total = tw + (12 if active else 0)
        al = self.aligns[i] if i < len(self.aligns) else "left"
        pad = self.pads[i] if i < len(self.pads) else 14
        x = rect.left() + (rect.width() - total) / 2 if al == "center" else rect.left() + pad
        col = QColor(C_ACCENT if active else C_DIM)
        p.setPen(col)
        p.drawText(QRectF(x, rect.top(), tw + 2, rect.height()),
                   Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignVCenter, text)
        if active:
            ax, cy = x + tw + 7, rect.top() + rect.height() / 2
            if self.sort_asc:
                poly = QPolygonF([QPointF(ax, cy + 2.2), QPointF(ax + 8, cy + 2.2), QPointF(ax + 4, cy - 2.6)])
            else:
                poly = QPolygonF([QPointF(ax, cy - 2.2), QPointF(ax + 8, cy - 2.2), QPointF(ax + 4, cy + 2.6)])
            p.setPen(Qt.PenStyle.NoPen); p.setBrush(col); p.drawPolygon(poly)
        p.fillRect(QRectF(rect.left(), rect.bottom(), rect.width(), 1), ink(14))
        p.restore()


class HoverTable(QTableWidget):
    """QTableWidget, помнящий строку под курсором (hover_row) — для подсветки целой строки."""
    def __init__(self, rows, cols, parent=None):
        super().__init__(rows, cols, parent)
        self.hover_row = -1
        self.setMouseTracking(True)

    def mouseMoveEvent(self, e):
        r = self.indexAt(e.position().toPoint()).row()
        if r != self.hover_row:
            self.hover_row = r
            self.viewport().update()
        super().mouseMoveEvent(e)

    def leaveEvent(self, e):
        if self.hover_row != -1:
            self.hover_row = -1
            self.viewport().update()
        super().leaveEvent(e)


def table_qss() -> str:
    return f"""
    QTableWidget {{ background: transparent; border: none; outline: none; }}
    QHeaderView {{ background: transparent; border: none; }}
    QHeaderView::section {{ background: transparent; border: none; }}
    QTableCornerButton::section {{ background: transparent; border: none; }}
    QScrollBar:vertical {{ background: transparent; width: 8px; margin: 6px 2px 6px 0; }}
    QScrollBar::handle:vertical {{ background: {ink_css(26)}; border-radius: 3px; min-height: 36px; }}
    QScrollBar::handle:vertical:hover {{ background: {ink_css(55)}; }}
    QScrollBar::add-line:vertical, QScrollBar::sub-line:vertical {{ height: 0; }}
    QScrollBar::add-page:vertical, QScrollBar::sub-page:vertical {{ background: transparent; }}
"""


TABLE_QSS = table_qss()


def setup_aurora_table(table: QTableWidget, row_h: int = ROW_H):
    """Вызывать ПОСЛЕ setHorizontalHeader(AuroraHeader(table)) и setHorizontalHeaderLabels()."""
    table.verticalHeader().hide()
    table.setFrameShape(QFrame.Shape.NoFrame)
    table.setShowGrid(False)
    table.setSelectionBehavior(QAbstractItemView.SelectionBehavior.SelectRows)
    table.setSelectionMode(QAbstractItemView.SelectionMode.SingleSelection)
    table.setEditTriggers(QAbstractItemView.EditTrigger.NoEditTriggers)
    table.setVerticalScrollMode(QAbstractItemView.ScrollMode.ScrollPerPixel)
    table.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
    table.setAlternatingRowColors(False)
    table.viewport().setAutoFillBackground(False)
    table.verticalHeader().setDefaultSectionSize(row_h)
    table.verticalHeader().setSectionResizeMode(QHeaderView.ResizeMode.Fixed)
    table.setStyleSheet(TABLE_QSS)


# ── 6. QSS ДЛЯ СТАНДАРТНЫХ ВИДЖЕТОВ ───────────────────────────────
CHECK_PNG = os.path.join(tempfile.gettempdir(), f"aurora_check_{os.getpid()}.png")


def ensure_check_icon():
    """PNG-галочка для QSS (image: url(...)): сам QSS галочку нарисовать не умеет.
    Галочка всегда СВЕТЛАЯ: тёмная тема — тёплый белый на приглушённом янтаре,
    светлая — белый на тёмно-янтарном фоне (тёмный глиф на янтаре не читался)."""
    color = "#fff6e6" if _theme_name == "dark" else "#ffffff"
    pix = QPixmap(18, 18)
    pix.fill(Qt.GlobalColor.transparent)
    p = QPainter(pix)
    p.setRenderHint(QPainter.RenderHint.Antialiasing)
    pen = QPen(QColor(color), 2.2)
    pen.setCapStyle(Qt.PenCapStyle.RoundCap)
    pen.setJoinStyle(Qt.PenJoinStyle.RoundJoin)
    p.setPen(pen)
    p.drawPolyline(QPolygonF([QPointF(4.6, 9.6), QPointF(7.8, 12.8), QPointF(13.6, 5.6)]))
    p.end()
    try:
        pix.save(CHECK_PNG, "PNG")
    except Exception:
        pass


def form_qss() -> str:
    """QSS стандартных виджетов для текущей темы. Применять: window.setStyleSheet(A.FORM_QSS).
    Включает QMessageBox (иначе он наследует только часть правил и может стать нечитаемым),
    галочку чекбокса и disabled-состояние."""
    popup, msg_bg, sel = T("popup"), T("msg_bg"), T("sel_text")
    am = T("accent_muted")      # приглушённый янтарь для «да/нет»-констролов
    return f"""
    QToolTip {{ background-color: {popup}; color: {C_TEXT}; border: 1px solid {ink_css(26)};
               border-radius: 6px; padding: 3px 8px; font-size: 11px; }}
    QLabel {{ color: {C_TEXT}; }}
    QLineEdit, QSpinBox, QDoubleSpinBox, QComboBox, QPlainTextEdit, QTextEdit {{
        background-color: {ink_css(9)}; color: {C_TEXT};
        border: 1px solid {ink_css(20)}; border-radius: 8px; padding: 7px 12px;
        selection-background-color: {accent_css(110)}; }}
    QLineEdit:focus, QSpinBox:focus, QDoubleSpinBox:focus, QComboBox:focus,
    QPlainTextEdit:focus, QTextEdit:focus {{ border: 1px solid {C_ACCENT}; background-color: {ink_css(12)}; }}
    QComboBox::drop-down {{ border: none; width: 24px; }}
    QComboBox QAbstractItemView {{ background-color: {popup}; border: 1px solid {ink_css(26)};
        border-radius: 8px; padding: 4px; outline: none; selection-background-color: {ink_css(18)}; }}
    QCheckBox {{ color: {C_TEXT}; spacing: 8px; }}
    QCheckBox::indicator {{ width: 16px; height: 16px; border-radius: 5px;
        border: 1px solid {ink_css(36)}; background: {ink_css(8)}; }}
    QCheckBox::indicator:hover {{ border-color: {ink_css(60)}; }}
    QCheckBox::indicator:checked {{ image: url({CHECK_PNG}); background-color: {am};
        border: 1px solid {am}; }}
    QCheckBox:disabled {{ color: {C_FAINT}; }}
    QMessageBox {{ background-color: {msg_bg}; }}
    QMessageBox QLabel {{ color: {C_TEXT}; background: transparent; }}
    QMessageBox QPushButton {{ background-color: {ink_css(9)};
        border: 1px solid {ink_css(24)}; border-radius: 8px;
        padding: 7px 18px; min-width: 72px; color: {C_TEXT}; font-weight: 500; }}
    QMessageBox QPushButton:hover {{ background-color: {ink_css(16)}; }}
    QMessageBox QPushButton:pressed {{ background-color: {ink_css(26)}; }}
    QMessageBox QPushButton:default {{ background-color: {am};
        border: 1px solid {am}; color: {sel}; }}
    QFileDialog QLabel {{ color: palette(window-text); }}
    QMenu {{ background-color: {popup}; color: {C_TEXT}; border: 1px solid {ink_css(26)};
        border-radius: 10px; padding: 6px; }}
    QMenu::item {{ padding: 7px 16px; border-radius: 7px; }}
    QMenu::item:selected {{ background-color: {ink_css(16)}; }}
    QMenu::separator {{ height: 1px; background: {ink_css(14)}; margin: 4px 8px; }}
    QSlider::groove:horizontal {{ height: 4px; border-radius: 2px; background: {ink_css(20)}; }}
    QSlider::sub-page:horizontal {{ background: {C_ACCENT}; border-radius: 2px; }}
    QSlider::handle:horizontal {{ width: 14px; margin: -5px 0; border-radius: 7px; background: #ffffff; }}
    QScrollBar:vertical {{ background: transparent; width: 8px; margin: 6px 2px 6px 0; }}
    QScrollBar::handle:vertical {{ background: {ink_css(26)}; border-radius: 3px; min-height: 36px; }}
    QScrollBar::handle:vertical:hover {{ background: {ink_css(55)}; }}
    QScrollBar::add-line:vertical, QScrollBar::sub-line:vertical {{ height: 0; }}
"""


def list_qss() -> str:
    return f"""
    QListWidget {{
        background: transparent;
        border: none;
        outline: none;
        padding: 0;
    }}
    QListWidget::item {{
        background: {ink_css(7)};
        border: 1px solid {ink_css(14)};
        border-radius: 8px;
        padding: 9px 14px;
        margin: 2px 0;
        color: {C_TEXT};
    }}
    QListWidget::item:hover {{ background: {ink_css(12)}; }}
    QListWidget::item:selected {{
        background: {ink_css(14)};
        border: 1px solid {accent_css(120)};
        color: {C_TEXT};
    }}
"""


def list_indicator_qss() -> str:
    return f"""
    QListWidget::indicator {{ width: 16px; height: 16px; border-radius: 5px;
        border: 1px solid {ink_css(36)}; background: {ink_css(8)}; }}
    QListWidget::indicator:checked {{ background-color: {T("accent_muted")};
        border: 1px solid {T("accent_muted")}; image: url({CHECK_PNG}); }}
"""


FORM_QSS = form_qss()
LIST_QSS = list_qss()
LIST_INDICATOR_QSS = list_indicator_qss()


# ── 7. Перьевые виджеты приложений и утилиты текста ────────────────
# Канонические реализации: правки вносить ТОЛЬКО здесь.


class GlyphButton(QAbstractButton):
    """Кнопка-глиф без эмодзи: значок рисуется пером. kind: copy | regen | verify | edit |
    resend | theme | gear | attach | plus | minus | refresh | close."""

    def __init__(self, kind: str, size: int = 26, tile: bool = False, parent=None):
        super().__init__(parent)
        self.kind = kind
        self.tile = tile          # True — постоянная матовая плитка (как у GhostButton)
        self.setFixedSize(size, size)
        self.setCursor(Qt.CursorShape.PointingHandCursor)
        self.setFocusPolicy(Qt.FocusPolicy.NoFocus)

    def enterEvent(self, e):
        self.update()
        super().enterEvent(e)

    def leaveEvent(self, e):
        self.update()
        super().leaveEvent(e)

    def paintEvent(self, _):
        p = QPainter(self)
        p.setRenderHint(QPainter.RenderHint.Antialiasing)
        hov, down, en = self.underMouse(), self.isDown(), self.isEnabled()
        if self.tile:
            a = 24 if down else (14 if hov else 8)
            p.setPen(QPen(ink(24 if en else 12), 1))
            p.setBrush(ink(a if en else 6))
            p.drawRoundedRect(QRectF(self.rect()).adjusted(0.5, 0.5, -0.5, -0.5), 8, 8)
        elif hov and en:
            p.setPen(Qt.PenStyle.NoPen)
            p.setBrush(ink(22 if down else 12))
            p.drawRoundedRect(QRectF(self.rect()).adjusted(1, 1, -1, -1), 7, 7)
        col = QColor(C_TEXT if (hov and en) else (C_DIM if en else C_FAINT))
        pen = QPen(col, 1.5)
        pen.setCapStyle(Qt.PenCapStyle.RoundCap)
        pen.setJoinStyle(Qt.PenJoinStyle.RoundJoin)
        p.setPen(pen)
        p.setBrush(Qt.BrushStyle.NoBrush)
        c = QPointF(self.width() / 2, self.height() / 2)
        k = self.kind
        P = lambda x, y: QPointF(c.x() + x, c.y() + y)
        if k == "copy":
            p.drawRoundedRect(QRectF(c.x() - 6, c.y() - 3, 9, 9.5), 2, 2)
            p.drawPolyline(QPolygonF([P(-3, -3), P(-3, -6.5), P(6, -6.5), P(6, 3), P(3, 3)]))
        elif k in ("regen", "refresh"):
            # «Повторить»: круговая стрелка ↻ — дуга с разрывом справа сверху
            # и заполненным треугольным наконечником по касательной (старая
            # версия с двумя штрихами читалась как циферблат).
            r = 5.5
            p.drawArc(QRectF(c.x() - r, c.y() - r, 2 * r, 2 * r), 10 * 16, -300 * 16)
            th = math.radians(70)                    # конец дуги (движение по часовой)
            px, py = r * math.cos(th), -r * math.sin(th)
            dx, dy = math.sin(th), math.cos(th)      # касательная по ходу дуги
            nx, ny = -dy, dx
            p.setBrush(col)
            p.drawPolygon(QPolygonF([
                P(px + dx * 3.4, py + dy * 3.4),
                P(px + nx * 2.4, py + ny * 2.4),
                P(px - nx * 2.4, py - ny * 2.4),
            ]))
            p.setBrush(Qt.BrushStyle.NoBrush)
        elif k == "verify":
            p.drawEllipse(P(-1.5, -1.5), 4.6, 4.6)
            p.drawLine(P(1.9, 1.9), P(6, 6))
        elif k == "edit":                                    # карандаш: корпус, колпачок, грифель
            p.save()
            p.translate(c)
            p.rotate(45)
            p.drawPolygon(QPolygonF([QPointF(-2.2, -4.6), QPointF(2.2, -4.6), QPointF(2.2, 2.6),
                                     QPointF(0, 6.0), QPointF(-2.2, 2.6)]))
            p.drawLine(QPointF(-2.2, -2.2), QPointF(2.2, -2.2))
            p.restore()
        elif k == "resend":
            p.drawLine(P(0, 6), P(0, -6))
            p.drawPolyline(QPolygonF([P(-4, -2), P(0, -6), P(4, -2)]))
        elif k == "theme":
            if theme_name() == "dark":                     # сейчас тёмная → значок «солнце»
                p.drawEllipse(c, 3.2, 3.2)
                for i in range(8):
                    a = i * math.pi / 4
                    p.drawLine(P(math.cos(a) * 5.4, math.sin(a) * 5.4), P(math.cos(a) * 7.2, math.sin(a) * 7.2))
            else:                                            # светлая → значок «луна»
                outer, cut = QPainterPath(), QPainterPath()
                outer.addEllipse(c, 6.2, 6.2)
                cut.addEllipse(P(3.2, -2.6), 5.2, 5.2)
                p.drawPath(outer.subtracted(cut))
        elif k == "gear":
            p.drawEllipse(c, 2.0, 2.0)
            p.drawEllipse(c, 4.4, 4.4)
            for i in range(8):
                a = i * math.pi / 4
                p.drawLine(P(math.cos(a) * 4.4, math.sin(a) * 4.4), P(math.cos(a) * 6.4, math.sin(a) * 6.4))
        elif k == "attach":
            path = QPainterPath()
            path.moveTo(P(4, -4))
            path.lineTo(P(4, 3))
            path.cubicTo(P(4, 7.5), P(-3, 7.5), P(-3, 3))
            path.lineTo(P(-3, -3))
            path.cubicTo(P(-3, -7.5), P(1, -7.5), P(1, -3))
            path.lineTo(P(1, 2.5))
            p.drawPath(path)
        elif k == "close":
            p.drawLine(P(-3.5, -3.5), P(3.5, 3.5))
            p.drawLine(P(-3.5, 3.5), P(3.5, -3.5))
        elif k == "plus":
            p.drawLine(P(-4.5, 0), P(4.5, 0))
            p.drawLine(P(0, -4.5), P(0, 4.5))
        elif k == "minus":
            p.drawLine(P(-4.5, 0), P(4.5, 0))
        p.end()



class ExtTile(QWidget):
    """Плитка-аватар файла: расширение на градиенте, цвет стабильно выводится из расширения."""

    def __init__(self, ext: str, size: int = 28, parent=None):
        super().__init__(parent)
        self.ext = (ext or "").lstrip(".").upper()[:3] or "•"
        self.setFixedSize(size, size)

    def paintEvent(self, _):
        p = QPainter(self)
        p.setRenderHint(QPainter.RenderHint.Antialiasing)
        p.setRenderHint(QPainter.RenderHint.TextAntialiasing)
        tile = QRectF(self.rect())
        p.setPen(QPen(ink(20), 1))
        p.setBrush(ink(10))
        p.drawRoundedRect(tile.adjusted(0.5, 0.5, -0.5, -0.5), 7, 7)
        p.setFont(font_mono(9))
        p.setPen(QColor(C_DIM))
        p.drawText(tile, Qt.AlignmentFlag.AlignCenter, self.ext)
        p.end()



def _rgb(v) -> tuple:
    """(r, g, b) из токена frame_* (токен хранит и альфу — она здесь не нужна)."""
    return tuple(int(c) for c in v[:3])


class SolidDialog(AuroraDialog):
    """AuroraDialog для окон настроек/таблиц: непрозрачный (текст не просвечивает, даже если
    композитор делает диалоги полупрозрачными) и обычного типа окна вместо «Dialog»."""

    def __init__(self, title: str, size=(600, 400), tag: str | None = None,
                 icon: QIcon | None = None, parent=None):
        super().__init__(title, size=size, tag=tag, icon=icon, parent=parent)
        self.setWindowFlags(Qt.WindowType.Window | Qt.WindowType.FramelessWindowHint)
        self.setWindowModality(Qt.WindowModality.WindowModal)

    def paintEvent(self, e):
        # Страховка композитору: под кэшированный фон рамки (_bg, см. _AuroraFrame)
        # льём полностью непрозрачную поверхность — иначе при DE-прозрачности
        # диалогов сквозь них виден чат (окно «Память»).
        th = THEMES[theme_name()]
        top, bot = _rgb(th["frame_top"]), _rgb(th["frame_bot"])
        mid = tuple((top[i] + bot[i]) / 2 for i in range(3))
        p = QPainter(self)
        p.setRenderHint(QPainter.RenderHint.Antialiasing)
        p.setPen(Qt.PenStyle.NoPen)
        p.setBrush(QColor(*[int(v) for v in mid]))
        m = SHADOW_M
        p.drawRoundedRect(QRectF(m, m, self.width() - 2 * m, self.height() - 2 * m), BODY_R, BODY_R)
        p.end()
        super().paintEvent(e)

    def hideEvent(self, e):
        super().hideEvent(e)
        # errors.txt 2026-11-17 («шлейф» с левой стороны после закрытия
        # диалога, тёмная тема): после unmap освобождённый регион первый
        # кадр показывает тёмный фон окна — виджеты под ним (край сайдбара,
        # лента) перекрашиваются только следующим проходом события
        # (замер по видео: кадр со strip≈19 (фон), через 0.1с — 27 (сайдбар)).
        # Репейнт области диалога СИНХРОННО в hideEvent, до unmap: буфер
        # родителя уже корректен в момент, когда композитор открывает
        # регион, — и «шлейфа» нет независимо от нагрузки/задержек expose.
        p = self.parentWidget()
        if p is not None and p.isVisible():
            r = QRect(self.mapTo(p, QPoint(0, 0)), self.frameGeometry().size())
            p.repaint(r)



# Префиксы эмодзи/стрелок в тексте кнопок и заголовках из старых данных
_EMOJI_PREFIX = re.compile(
    "^[\u2190-\u21ff\u2300-\u23ff\u25a0-\u25ff\u2600-\u27bf\u2b00-\u2bff"
    "\U0001f000-\U0001ffff\ufe0f\u200d\\s]+")
_ARROW_PREFIX = re.compile(r"^[>v]\s+")


def strip_emoji(text: str) -> str:
    """'📁 Папка' → 'Папка', '> Запустить' → 'Запустить', '◼ Остановить' → 'Остановить'.

    Legacy guard: строки i18n и заголовки чатов уже вычищены от эмодзи;
    остался как страховка от эмодзи в данных старых сохранённых чатов."""
    if not text:
        return text
    t = _EMOJI_PREFIX.sub("", text)
    return _ARROW_PREFIX.sub("", t)



def setup_app(app: QApplication):
    """Один раз ПОСЛЕ создания QApplication: шрифт Inter 10, стиль Fusion, PNG-галочка для QSS."""
    app.setFont(QFont("Inter", 10))
    app.setStyle("Fusion")
    ensure_check_icon()


