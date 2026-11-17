# LLM-Chat-Common/ui/widgets.py
"""Общие виджеты чата единого приложения LLM Chat.
Правки вносить ТОЛЬКО здесь; app/ держит тонкие обёртки-реэкспорты."""
from pathlib import Path

from PyQt6.QtWidgets import (
    QWidget, QHBoxLayout, QVBoxLayout, QLabel, QMenu,
    QApplication, QComboBox, QAbstractSpinBox,
    QAbstractButton, QSizePolicy, QMessageBox,
)
from PyQt6.QtCore import (
    Qt, pyqtSignal, QObject, QEvent, QTimer, QPointF, QRectF,
)
from PyQt6.QtGui import (
    QPainter, QPen, QPolygonF, QColor, QFont, QIcon, QPixmap,
)

from theme import get_palette as _P
from aurora import (ExtTile, GlyphButton, font as _font, ink, ink_css, T,
                    C_TEXT, strip_emoji)
from chat_widgets import ModelMenuButton, style_menu
from i18n import _t


class _SpinEditFixer(QObject):
    """Принудительно задаёт геометрию внутреннего поля ввода спинбокса.

    После обновления Qt встроенный расчёт области редактирования
    (QSpinBox + stylesheet + NoButtons) даёт поле почти нулевой ширины,
    и число не видно. Геометрия ставится вручную при ресайзе/показе/смене
    стиля, поэтому результат не зависит от версии Qt."""
    _EVENTS = (QEvent.Type.Resize, QEvent.Type.Show, QEvent.Type.StyleChange,
               QEvent.Type.LayoutRequest, QEvent.Type.PolishRequest)

    def __init__(self, spin: QAbstractSpinBox, left: int = 6, right: int = 4):
        super().__init__(spin)
        self._spin = spin
        self._l, self._r = left, right
        le = spin.lineEdit()
        if le is not None:
            le.setStyleSheet(
                "QLineEdit { background: transparent; border: none;"
                " border-radius: 0px; padding: 0px; margin: 0px; }"
            )
            le.setTextMargins(0, 0, 0, 0)
            le.setAlignment(Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignVCenter)
        spin.installEventFilter(self)
        QTimer.singleShot(0, self._apply)

    def _apply(self):
        try:
            le = self._spin.lineEdit()
            if le is None:
                return
            w, h = self._spin.width(), self._spin.height()
            rect = (self._l, 1, max(10, w - self._l - self._r), max(10, h - 2))
            if le.geometry().getRect() != rect:
                le.setGeometry(*rect)
        except RuntimeError:
            pass

    def eventFilter(self, obj, event):
        if obj is self._spin and event.type() in self._EVENTS:
            self._apply()
            QTimer.singleShot(0, self._apply)
        return False


class NoWheelComboBox(QComboBox):
    """QComboBox, не реагирующий на прокрутку колеса мыши: панель параметров
    скроллится целиком (sidebar обёрнут в QScrollArea), и без этого прокрутка
    колесом над списком меняла бы выбранное значение вместо прокрутки
    панели — стандартное (и неудобное здесь) поведение QComboBox в Qt."""
    def wheelEvent(self, event):
        event.ignore()




# ── Один класс выбора модели на оба приложения: в Ollama исторически
# ModelSelector (QPushButton+QMenu), в Llama — ModelPicker (QToolButton+QMenu).
# С общим классом оба имени указывают на одну реализацию, вызывающий код
# не меняется.
ModelSelector = ModelMenuButton
ModelPicker = ModelMenuButton


class FileChip(QWidget):
    removed = pyqtSignal(str)
    def __init__(self, path: str, parent=None):
        super().__init__(parent)
        self.path = path
        p = Path(path)
        self.name = p.name
        self.ext = p.suffix.lower()
        try: self.size = p.stat().st_size
        except Exception: self.size = 0
        self.setAttribute(Qt.WidgetAttribute.WA_StyledBackground, True)
        self._setup_ui()
        self._apply_theme()

    def _setup_ui(self):
        lay = QHBoxLayout(self)
        lay.setContentsMargins(8, 3, 5, 3)
        lay.setSpacing(6)
        self.lbl_icon = ExtTile(self.ext, 20)
        lay.addWidget(self.lbl_icon)
        name_text = self.name if len(self.name) <= 22 else self.name[:19] + "…"
        self.lbl_name = QLabel(name_text)
        self.lbl_name.setToolTip(self.path)
        lay.addWidget(self.lbl_name)
        size_text = self._fmt_size(self.size)
        self.lbl_size = QLabel(size_text)
        lay.addWidget(self.lbl_size)
        self.btn_x = GlyphButton("close", 18)
        self.btn_x.clicked.connect(lambda: self.removed.emit(self.path))
        lay.addWidget(self.btn_x)

    @staticmethod
    def _fmt_size(size: int) -> str:
        if size < 1024: return f"{size} B"
        elif size < 1024 * 1024: return f"{size / 1024:.1f} KB"
        else: return f"{size / (1024 * 1024):.1f} MB"

    def _apply_theme(self):
        p = _P()
        self.setStyleSheet(f"""
            FileChip {{
                background: {p["CHIP_BG"]};
                border: 1px solid {p["CHIP_BR"]};
                border-radius: 12px;
            }}
            QLabel {{
                color: {p["CHIP_FG"]};
                font-size: 11px;
                background: transparent;
                border: none;
            }}
        """)
        self.lbl_size.setStyleSheet(
            f"color: {p['DIM']}; font-size: 10px; background: transparent; border: none;"
        )
        self.btn_x.update()

    def recolor(self):
        self._apply_theme()


class FileCard(QWidget):
    def __init__(self, path: str, parent=None):
        super().__init__(parent)
        self.path = path
        p = Path(path)
        self.name = p.name
        self.ext = p.suffix.lower()
        try: self.size = p.stat().st_size
        except Exception: self.size = 0
        self.setAttribute(Qt.WidgetAttribute.WA_StyledBackground, True)
        self._setup_ui()
        self._apply_theme()

    def _setup_ui(self):
        lay = QHBoxLayout(self)
        lay.setContentsMargins(10, 7, 10, 7)
        lay.setSpacing(10)
        self.lbl_icon = ExtTile(self.ext, 34)
        lay.addWidget(self.lbl_icon)
        info = QVBoxLayout()
        info.setSpacing(1)
        info.setContentsMargins(0, 0, 0, 0)
        self.lbl_name = QLabel(self.name)
        self.lbl_name.setToolTip(self.path)
        self.lbl_name.setWordWrap(False)
        info.addWidget(self.lbl_name)
        size_text = FileChip._fmt_size(self.size)
        type_text = self.ext[1:].upper() if self.ext else "FILE"
        self.lbl_meta = QLabel(f"{type_text} · {size_text}")
        info.addWidget(self.lbl_meta)
        lay.addLayout(info, stretch=1)
        lay.addStretch()

    def _apply_theme(self):
        p = _P()
        self.setStyleSheet(f"""
            FileCard {{
                background: {p["CARD_BG"]};
                border: 1px solid {p["CARD_BR"]};
                border-radius: 12px;
            }}
            QLabel {{
                background: transparent;
                border: none;
            }}
        """)
        self.lbl_name.setStyleSheet(
            f"color: {p['CARD_FG']}; font-size: 12px; font-weight: 500;"
        )
        self.lbl_meta.setStyleSheet(f"color: {p['CARD_DIM']}; font-size: 10px;")

    def recolor(self):
        self._apply_theme()




class ThemedLabel(QLabel):
    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.setContextMenuPolicy(Qt.ContextMenuPolicy.CustomContextMenu)
        self.customContextMenuRequested.connect(self._show_context_menu)

    def _show_context_menu(self, pos):
        menu = QMenu(self)
        style_menu(menu)
        selected = self.selectedText()
        act_copy = menu.addAction(_t("ctx_copy"))
        act_copy.setEnabled(bool(selected))
        act_sel_all = menu.addAction(_t("ctx_select_all"))
        chosen = menu.exec(self.mapToGlobal(pos))
        if chosen == act_copy and selected:
            QApplication.instance().clipboard().setText(selected)
        elif chosen == act_sel_all:
            self.selectAll()


def _dlg_glyph_icon(kind: str) -> QIcon:
    """Перьевая иконка для кнопок «Да/Нет»: светлая галочка / крестик.
    Системные иконки Qt в тёмной теме рисуют тёмный глиф на янтарной кнопке —
    галочку не видно."""
    pm = QPixmap(36, 36)
    pm.fill(Qt.GlobalColor.transparent)
    p = QPainter(pm)
    p.setRenderHint(QPainter.RenderHint.Antialiasing)
    pen = QPen(QColor(C_TEXT), 2.6)
    pen.setCapStyle(Qt.PenCapStyle.RoundCap)
    pen.setJoinStyle(Qt.PenJoinStyle.RoundJoin)
    p.setPen(pen)
    p.setBrush(Qt.BrushStyle.NoBrush)
    if kind == "check":
        p.drawPolyline(QPolygonF([QPointF(9, 19), QPointF(15.5, 25.5), QPointF(27, 10.5)]))
    else:                                    # «Нет»: крест в тонком кольце
        c_no = QColor(C_TEXT)
        c_no.setAlpha(190)
        p.setPen(QPen(c_no, 2.2))
        p.drawEllipse(QPointF(18, 18), 10.5, 10.5)
        p.drawLine(QPointF(11.5, 24.5), QPointF(24.5, 11.5))
    p.end()
    return QIcon(pm)


def confirm(parent, title: str, body: str) -> bool:
    """Диалог «Да / Нет» вместо QMessageBox.question: тот же набор кнопок и
    вопросительная иконка, но галочка на «Да» нарисована пером и всегда
    светлая, акцент кнопки — приглушённый (QSS QMessageBox QPushButton:default)."""
    mb = QMessageBox(parent)
    mb.setIcon(QMessageBox.Icon.Question)
    mb.setWindowTitle(title)
    mb.setText(body)
    btn_yes = mb.addButton(QMessageBox.StandardButton.Yes)
    btn_no = mb.addButton(QMessageBox.StandardButton.No)
    btn_yes.setIcon(_dlg_glyph_icon("check"))
    btn_no.setIcon(_dlg_glyph_icon("no"))
    mb.setDefaultButton(btn_yes)
    mb.exec()
    return mb.clickedButton() is btn_yes


class _SectionHeader(QAbstractButton):
    """Заголовок секции: шеврон (вправо/вниз) и название (sentence case)."""

    def __init__(self, title: str, parent=None):
        super().__init__(parent)
        self._title = strip_emoji(title).strip()
        self.setCheckable(True)
        self.setFixedHeight(UI_ROW_H)
        self.setCursor(Qt.CursorShape.PointingHandCursor)
        self.setFocusPolicy(Qt.FocusPolicy.NoFocus)
        self.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Fixed)

    def enterEvent(self, e):
        self.update()
        super().enterEvent(e)

    def leaveEvent(self, e):
        self.update()
        super().leaveEvent(e)

    def paintEvent(self, _):
        p = QPainter(self)
        p.setRenderHint(QPainter.RenderHint.Antialiasing)
        p.setRenderHint(QPainter.RenderHint.TextAntialiasing)
        hov = self.underMouse()
        if hov:
            p.setPen(Qt.PenStyle.NoPen)
            # ink(16) — тот же уровень hover-поверхности, что у GhostButton
            # (aurora.py:~595); ink(11) в светлой теме практически невидим,
            # а текст C_TEXT (#ededed — константа тёмной темы) ложился белым
            # по белому. Текст — токены темы: hover T("text"), покой T("dim").
            p.setBrush(ink(16))
            p.drawRoundedRect(QRectF(self.rect()).adjusted(0, 1, 0, -1), 9, 9)
        col = QColor(T("text") if hov else T("dim"))
        pen = QPen(col, 1.6)
        pen.setCapStyle(Qt.PenCapStyle.RoundCap)
        pen.setJoinStyle(Qt.PenJoinStyle.RoundJoin)
        p.setPen(pen)
        cy = self.height() / 2
        if self.isChecked():
            p.drawPolyline(QPolygonF([QPointF(11, cy - 1.8), QPointF(14.5, cy + 1.8), QPointF(18, cy - 1.8)]))
        else:
            p.drawPolyline(QPolygonF([QPointF(12.5, cy - 3.5), QPointF(16.2, cy), QPointF(12.5, cy + 3.5)]))
        f = _font(11, QFont.Weight.Medium)
        p.setFont(f)
        p.setPen(col)
        p.drawText(QRectF(28, 0, self.width() - 34, self.height()),
                   Qt.AlignmentFlag.AlignVCenter | Qt.AlignmentFlag.AlignLeft, self._title)
        p.end()

UI_ROW_H = 32
UI_SPACING = 8


class CollapsibleSection(QWidget):
    def __init__(self, title: str, expanded: bool = False, parent=None):
        super().__init__(parent)
        self._expanded = expanded
        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(0)

        self._toggle_btn = _SectionHeader(title)
        self._toggle_btn.setChecked(expanded)
        self._title = title
        self._toggle_btn.toggled.connect(self._on_toggle)
        layout.addWidget(self._toggle_btn)

        self._body = QWidget()
        self._body.setObjectName("collapsibleBody")
        # WA_StyledBackground: QSS-фон секции рисуется и у «пустого» QWidget
        self._body.setAttribute(Qt.WidgetAttribute.WA_StyledBackground, True)
        self._body_layout = QVBoxLayout(self._body)
        # внутренние поля карточки: контент не прижат к рамке
        self._body_layout.setContentsMargins(10, 6, 10, 10)
        self._body_layout.setSpacing(UI_SPACING)
        self._body.setVisible(expanded)
        layout.addWidget(self._body)
        self.refresh_theme()

    def _on_toggle(self, checked: bool):
        self._expanded = checked
        self._body.setVisible(checked)
        self._toggle_btn.update()

    def refresh_theme(self):
        """Заголовок и карточка секции рисуются по токенам темы.
        Карточка выделяет раскрытую область: без неё содержимое «висит в
        воздухе» сайдбара и сливается с остальными полями."""
        self._toggle_btn.update()
        self._body.setStyleSheet(
            f"QWidget#collapsibleBody {{ background-color: {ink_css(6)};"
            f" border: 1px solid {ink_css(14)}; border-radius: 10px; }}"
        )

    def add_widget(self, widget: QWidget):
        self._body_layout.addWidget(widget)

    def add_layout(self, layout):
        self._body_layout.addLayout(layout)

    def add_row(self, label_text: str, widget: QWidget):
        lbl = QLabel(label_text)
        lbl.setObjectName("fieldLabel")
        row = QVBoxLayout()
        row.setContentsMargins(0, 0, 0, 0)
        row.setSpacing(3)
        row.addWidget(lbl)
        row.addWidget(widget)
        self._body_layout.addLayout(row)
