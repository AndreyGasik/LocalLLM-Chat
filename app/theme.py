# app/theme.py — тонкая склейка Aurora для единого приложения.
# Все токены/виджеты живут в LLM-Chat-Common/aurora.py — правки ТОЛЬКО там.
import os
import sys

_COMMON = os.path.join(
    os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
    "LLM-Chat-Common",
)
if os.path.isdir(_COMMON) and _COMMON not in sys.path:
    sys.path.insert(0, _COMMON)

import aurora
from aurora import make_icon, strip_emoji

A = aurora  # алиас: A.C_TEXT, A.font, A.AuroraWindow и т.д.



# Обёртка: приложение-специфичные утилиты поверх Aurora
def set_state(w, state):
    w.setProperty("state", state or "")
    w.style().unpolish(w)
    w.style().polish(w)

def get_theme() -> str:
    return aurora.theme_name()

def switch_theme(name: str) -> None:
    aurora.set_theme(name)

# Иконка единого приложения: янтарная плитка с перьевым глифом LLM
def make_app_icon():
    from PyQt6.QtCore import Qt, QPointF, QRectF
    from PyQt6.QtGui import QPen, QColor, QPolygonF, QPainter, QPainterPath
    def draw(p):
        pen = QPen(QColor("#241703"), 9)
        pen.setCapStyle(Qt.PenCapStyle.RoundCap)
        pen.setJoinStyle(Qt.PenJoinStyle.RoundJoin)
        p.setPen(pen)
        p.setBrush(Qt.BrushStyle.NoBrush)
        for x in (18, 50):
            p.drawPolyline(QPolygonF([QPointF(x, 34), QPointF(x, 94), QPointF(x + 22, 94)]))
        p.drawPolyline(QPolygonF([QPointF(82, 94), QPointF(82, 34), QPointF(98, 66),
                                  QPointF(114, 34), QPointF(114, 94)]))
    return make_icon("#e09a2d", draw)

# app_qss: общий QSS для сайдбара/меню/полей единого окна
def app_qss() -> str:
    ink, acc = aurora.ink_css, aurora.accent_css
    return aurora.FORM_QSS + f"""
        QWidget#sidebarScroll, QScrollArea {{ background: transparent; border: none; }}
        QLabel#dim10 {{ font-size: 10px; color: {aurora.C_DIM}; }}
        QLabel#dim11 {{ font-size: 11px; color: {aurora.C_DIM}; }}
        QLabel#fieldLabel {{ font-size: 11px; color: {aurora.C_DIM}; }}
        QLabel#dim10[state="ok"], QLabel#dim11[state="ok"] {{ color: {aurora.C_OK}; }}
        QLabel#dim10[state="bad"], QLabel#dim11[state="bad"] {{ color: {aurora.C_DANGER}; }}
        QFrame#hline {{ background-color: {ink(14)}; border: none; }}
        QSplitter::handle {{ background-color: {ink(14)}; }}
        QSplitter::handle:horizontal {{ width: 1px; }}
        QListView#chatView {{ background: transparent; border: none; }}
        QListWidget#historyList {{
            background-color: {ink(7)}; border: 1px solid {ink(18)};
            border-radius: 10px; outline: none; padding: 4px; }}
        QToolButton#modelPicker {{
            background-color: {ink(9)}; border: 1px solid {ink(20)};
            border-radius: 8px; padding: 4px 28px 4px 12px;
            color: {aurora.C_TEXT}; text-align: left; }}
        QToolButton#modelPicker:hover {{ border-color: {ink(48)}; }}
        QToolButton#modelPicker::menu-indicator {{ image: none; }}
        QToolButton#menuBtn {{
            background-color: {ink(8)}; border: 1px solid {ink(20)};
            border-radius: 8px; padding: 4px 14px; color: {aurora.C_TEXT}; }}
        QToolButton#menuBtn:hover {{ border-color: {ink(28)}; }}
        QLineEdit#spinEdit {{ background: transparent; border: none; padding: 0px; }}
    """

# Реэкспорт всех Aurora-имён через __getattr__ (живые токены после set_theme)
def __getattr__(name: str):
    return getattr(aurora, name)


def _build_palette() -> dict:
    """Графит + янтарь."""
    dark = A.theme_name() == "dark"
    if dark:
        P = {
            "BG": "#141415", "USER_BG": "rgba(255,255,255,16)", "BOT_BG": "rgba(255,255,255,9)",
            "USER_BR": "rgba(255,255,255,30)", "BOT_BR": "rgba(255,255,255,18)",
            "USER_NAME": "#a1a1a6", "BOT_NAME": "#eda23c",
            "TEXT": "#ededed", "DIM": "#a1a1a6",
            "THOUGHT_FG": "#a1a1a6", "THOUGHT_BG": "rgba(255,255,255,6)", "THOUGHT_BR": "rgba(255,255,255,22)",
            "TOOL_CALL": "#eda23c", "TOOL_CALL_BG": "rgba(237,162,60,14)", "TOOL_CALL_BR": "rgba(237,162,60,110)",
            "TOOL_RES": "#4cc38a", "TOOL_RES_BG": "rgba(76,195,138,12)", "TOOL_RES_BR": "rgba(76,195,138,100)",
            "ERROR": "#e5484d",
            "SCROLLBAR": "transparent", "SCROLL_H": "rgba(255,255,255,26)", "SCROLL_HH": "rgba(255,255,255,55)",
            "INPUT_BG": "rgba(255,255,255,10)", "BORDER": "rgba(255,255,255,22)",
            "MENU_BG": "#1c1c1e", "MENU_SEL": "rgba(255,255,255,12)", "MENU_TEXT": "#ededed",
            "THEME_ICON": "",
            "CODE_BG": "#101012", "CODE_BR": "#26262a",
            "CODE_FG": "#e4e4e7", "INLINE_BG": "#232326", "INLINE_BR": "#2e2e33",
            "QUOTE_BR": "#3f3f46", "QUOTE_FG": "#a1a1a6", "QUOTE_BG": "#19191b",
            "LINK": "#eda23c", "HEADING": "#f1f1f3", "HR": "#2e2e33",
            "STRONG": "#f1f1f3", "EM": "#ededed",
            "ACT_FG": "#85858b", "ACT_HOVER": "#ededed",
            "CHIP_BG": "rgba(255,255,255,9)", "CHIP_BR": "rgba(255,255,255,22)", "CHIP_FG": "#ededed",
            "CHIP_X": "#e5484d", "CHIP_X_HV": "#eda23c",
            "CARD_BG": "rgba(255,255,255,8)", "CARD_BR": "rgba(255,255,255,20)", "CARD_FG": "#ededed",
            "CARD_DIM": "#85858b",
            "PG_KW": "#eda23c", "PG_STR": "#4cc38a", "PG_NUM": "#e5c07b",
            "PG_COM": "#6f6f76", "PG_FN": "#7aa2f2", "PG_CLS": "#56b6c2",
            "PG_OP": "#a1a1a6", "PG_VAR": "#ededed", "PG_ERR": "#e5484d",
            "PG_NAME": "#e4e4e7", "PG_BI": "#7aa2f2", "STATS_FG": "#85858b",
            "USER_TEXT": "#ededed",
        }
    else:
        P = {
            "BG": "#fafafa", "USER_BG": "#ffffff", "BOT_BG": "rgba(24,24,27,5)",
            "USER_BR": "rgba(24,24,27,16)", "BOT_BR": "rgba(24,24,27,12)",
            "USER_NAME": "#525252", "BOT_NAME": "#b45309",
            "TEXT": "#171717", "DIM": "#525252",
            "THOUGHT_FG": "#525252", "THOUGHT_BG": "rgba(24,24,27,4)", "THOUGHT_BR": "rgba(24,24,27,16)",
            "TOOL_CALL": "#92400e", "TOOL_CALL_BG": "rgba(180,83,9,10)", "TOOL_CALL_BR": "rgba(180,83,9,90)",
            "TOOL_RES": "#166534", "TOOL_RES_BG": "rgba(22,163,74,9)", "TOOL_RES_BR": "rgba(22,163,74,80)",
            "ERROR": "#dc2626",
            "SCROLLBAR": "transparent", "SCROLL_H": "rgba(24,24,27,26)", "SCROLL_HH": "rgba(24,24,27,55)",
            "INPUT_BG": "#ffffff", "BORDER": "rgba(24,24,27,14)",
            "MENU_BG": "#ffffff", "MENU_SEL": "rgba(24,24,27,7)", "MENU_TEXT": "#171717",
            "THEME_ICON": "",
            "CODE_BG": "#f4f4f5", "CODE_BR": "#e4e4e7",
            "CODE_FG": "#18181b", "INLINE_BG": "#ececee", "INLINE_BR": "#dcdce0",
            "QUOTE_BR": "#d4d4d8", "QUOTE_FG": "#525252", "QUOTE_BG": "#f4f4f5",
            "LINK": "#b45309", "HEADING": "#18181b", "HR": "#e4e4e7",
            "STRONG": "#18181b", "EM": "#171717",
            "ACT_FG": "#737373", "ACT_HOVER": "#171717",
            "CHIP_BG": "rgba(24,24,27,6)", "CHIP_BR": "rgba(24,24,27,16)", "CHIP_FG": "#171717",
            "CHIP_X": "#dc2626", "CHIP_X_HV": "#b45309",
            "CARD_BG": "#ffffff", "CARD_BR": "rgba(24,24,27,12)", "CARD_FG": "#171717",
            "CARD_DIM": "#737373",
            "PG_KW": "#b45309", "PG_STR": "#15803d", "PG_NUM": "#a16207",
            "PG_COM": "#7b7b83", "PG_FN": "#1d4ed8", "PG_CLS": "#0f766e",
            "PG_OP": "#525252", "PG_VAR": "#171717", "PG_ERR": "#dc2626",
            "PG_NAME": "#18181b", "PG_BI": "#2563eb", "STATS_FG": "#737373",
            "USER_TEXT": "#171717",
        }
    acc, ok, danger = (A.THEMES[A.theme_name()]["accent"], A.THEMES[A.theme_name()]["ok"],
                       A.THEMES[A.theme_name()]["danger"])
    P.update({"ACCENT": acc, "ACCENT2": ok, "OK": ok, "WARN": acc, "DANGER": danger,
              "SEL_TEXT": A.THEMES[A.theme_name()]["sel_text"]})
    return P





def get_palette() -> dict:
    return _build_palette()

# ── Единая система размеров для боковой панели ────────────────────────
UI_RADIUS   = 8   # скругление полей ввода
UI_ROW_H    = 32  # высота однострочных контролов
UI_ICON_BTN = 28  # сторона квадратной icon-only кнопки
UI_MARGIN   = 12  # внешние отступы секций/сайдбара
UI_SPACING  = 8   # расстояние между рядами внутри секции


# ── Кнопки сайдбара (обёртки над Aurora) ──────────────────────────────
class GhostBtn(A.GhostButton):
    """GhostButton для сайдбара: высота UI_ROW_H, эмодзи отбрасываются."""

    def __init__(self, text="", parent=None):
        super().__init__(strip_emoji(text), parent)
        self.setFixedHeight(UI_ROW_H)

    def setText(self, text):
        super().setText(strip_emoji(text))
        self.updateGeometry()

    def sizeHint(self):
        from PyQt6.QtCore import QSize
        from PyQt6.QtGui import QFontMetrics
        w = QFontMetrics(A.font(12.5, A.QFont.Weight.DemiBold)).horizontalAdvance(self.text()) + 34
        return QSize(w, UI_ROW_H)


class PrimaryBtn(A.PrimaryButton):
    """PrimaryButton без эмодзи в тексте."""

    def __init__(self, text="", kind="accent", stop_icon=False, parent=None):
        super().__init__(strip_emoji(text), kind=kind, stop_icon=stop_icon, parent=parent)
        self.setFixedHeight(UI_ROW_H)

    def setText(self, text):
        super().setText(strip_emoji(text))


# ── RowPillDelegate: компактная строка списка с пилюлей Aurora ───────
# Импорты ЯВНЫЕ: раньше эти имена резолвились через модульный
# __getattr__-форвардинг в aurora — тот же класс хрупкости, что и убитый
# баг с _rgb (опечатка всплывала бы только в рантайме, при отрисовке).
from PyQt6.QtWidgets import QStyledItemDelegate, QStyle
from PyQt6.QtCore import QRectF, Qt
from PyQt6.QtGui import QFont, QFontMetrics, QPainter, QColor
from aurora import (
    paint_row_pill, paint_selection_marker, font, T, C_TEXT,
)


class RowPillDelegate(QStyledItemDelegate):
    """Компактная строка списка: пилюля при наведении и у выделенной."""

    ROW_H = 30

    def sizeHint(self, option, index):
        from PyQt6.QtCore import QSize
        return QSize(option.rect.width(), self.ROW_H)

    def paint(self, p, option, index):
        rect = QRectF(option.rect)
        sel = bool(option.state & QStyle.StateFlag.State_Selected)
        hov = bool(option.state & QStyle.StateFlag.State_MouseOver)
        p.save()
        p.setRenderHint(QPainter.RenderHint.Antialiasing)
        p.setRenderHint(QPainter.RenderHint.TextAntialiasing)
        paint_row_pill(p, rect, 0, 1, sel, hov)
        p.setClipping(False)
        if sel:
            paint_selection_marker(p, rect, rect.center().y())
        f = QFont(index.data(Qt.ItemDataRole.FontRole) or font(12.5))
        f.setPixelSize(13)
        p.setFont(f)
        p.setPen(QColor(T("sel_text") if sel else C_TEXT))
        text = QFontMetrics(f).elidedText(index.data(Qt.ItemDataRole.DisplayRole) or "",
                                          Qt.TextElideMode.ElideRight, int(rect.width() - 26))
        p.drawText(QRectF(rect.left() + 14, rect.top(), rect.width() - 22, rect.height()),
                   Qt.AlignmentFlag.AlignVCenter | Qt.AlignmentFlag.AlignLeft, text)
        p.restore()

def toggle_theme() -> str:
    new = "light" if A.theme_name() == "dark" else "dark"
    A.set_theme(new)
    return new
