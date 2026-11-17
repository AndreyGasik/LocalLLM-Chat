# LLM-Chat-Common/ui/dialogs/memory_dialog.py — общий для обеих версий.
from PyQt6.QtCore import Qt, QRectF, QSize
from PyQt6.QtGui import QColor, QFont, QFontMetrics, QPainter, QPalette
from PyQt6.QtWidgets import (
    QLabel, QStyle, QStyledItemDelegate,
    QTableWidgetItem, QHeaderView,
)

from aurora import (
    SolidDialog, GhostButton, PrimaryButton, HoverTable, AuroraHeader,
    setup_aurora_table, paint_row_pill, paint_selection_marker,
    font, T, C_TEXT, C_DIM, strip_emoji,
)
from ui.widgets import confirm
from i18n import _t


class _MemoryRowDelegate(QStyledItemDelegate):
    """Строка таблицы памяти: пилюля на всю строку (hover / выделение), текст по колонкам."""

    ROW_H = 34

    def __init__(self, table):
        super().__init__(table)
        self._table = table

    def sizeHint(self, option, index):
        # ширина нужна ResizeToContents: текст ячейки + отступы колонки
        col = index.column()
        f = font(12.5, QFont.Weight.DemiBold if col == 0 else QFont.Weight.Normal)
        w = QFontMetrics(f).horizontalAdvance(str(index.data(Qt.ItemDataRole.DisplayRole) or ""))
        return QSize(w + (18 if col == 0 else 8) + 16, self.ROW_H)

    def paint(self, p, option, index):
        rect = QRectF(option.rect)
        row, col = index.row(), index.column()
        ncols = self._table.columnCount()
        sel = bool(option.state & QStyle.StateFlag.State_Selected)
        hov = row == self._table.hover_row
        p.save()
        p.setRenderHint(QPainter.RenderHint.Antialiasing)
        p.setRenderHint(QPainter.RenderHint.TextAntialiasing)
        paint_row_pill(p, rect, col, ncols, sel, hov)
        p.setClipping(False)
        if sel and col == 0:
            paint_selection_marker(p, rect, rect.center().y())
        text = str(index.data(Qt.ItemDataRole.DisplayRole) or "")
        f = font(12.5, QFont.Weight.DemiBold if col == 0 else QFont.Weight.Normal)
        p.setFont(f)
        color = {3: C_DIM}.get(col, C_TEXT)
        p.setPen(QColor(T("sel_text") if (sel and col in (1, 2)) else color))
        pad = 18 if col == 0 else 8
        avail = int(rect.width() - pad - 8)
        p.drawText(QRectF(rect.left() + pad, rect.top(), avail, rect.height()),
                   Qt.AlignmentFlag.AlignVCenter | Qt.AlignmentFlag.AlignLeft,
                   QFontMetrics(f).elidedText(text, Qt.TextElideMode.ElideRight, avail))
        p.restore()


class MemoryDialog(SolidDialog):
    """Просмотр и удаление записей долговременной памяти (MemoryDB).
    Вынесено из инлайн-метода MainWindow._show_memory в отдельный класс —
    поведение и вёрстка не изменены."""

    def __init__(self, memory_db, parent=None):
        super().__init__(strip_emoji(_t("dlg_mem_title")), size=(700 + 32, 420 + 32), parent=parent)
        self.memory_db = memory_db

        rows = self.memory_db.read()
        lay = self.body
        lay.setContentsMargins(16, 2, 16, 12)
        lay.setSpacing(8)

        if not rows:
            empty = QLabel(_t("dlg_mem_empty"))
            empty.setWordWrap(True)
            lay.addWidget(empty)
            lay.addStretch(1)
        else:
            table = HoverTable(len(rows), 4)
            table.setHorizontalHeader(AuroraHeader(table, sortable=(), aligns=("left",) * 4, pads=(18, 8, 8, 8)))
            table.setHorizontalHeaderLabels([
                _t("dlg_mem_col_cat"), _t("dlg_mem_col_key"),
                _t("dlg_mem_col_val"), _t("dlg_mem_col_upd"),
            ])
            setup_aurora_table(table, row_h=_MemoryRowDelegate.ROW_H)
            hdr = table.horizontalHeader()
            hdr.setMinimumSectionSize(96)       # чтобы подписи колонок не слипались
            hdr.setSectionResizeMode(0, QHeaderView.ResizeMode.ResizeToContents)
            hdr.setSectionResizeMode(1, QHeaderView.ResizeMode.ResizeToContents)
            hdr.setSectionResizeMode(2, QHeaderView.ResizeMode.Stretch)
            hdr.setSectionResizeMode(3, QHeaderView.ResizeMode.ResizeToContents)
            table.setItemDelegate(_MemoryRowDelegate(table))
            # Qt рисует подсветку выбранной строки (PE_PanelItemViewRow) ПОД делегатом —
            # палитрой делаем её прозрачной, остаётся только пилюля Aurora.
            pal = table.palette()
            pal.setColor(QPalette.ColorRole.Highlight, QColor(0, 0, 0, 0))
            pal.setColor(QPalette.ColorRole.HighlightedText, QColor(C_TEXT))
            table.setPalette(pal)
            for i, r in enumerate(rows):
                table.setItem(i, 0, QTableWidgetItem(r["category"]))
                table.setItem(i, 1, QTableWidgetItem(r["key"]))
                table.setItem(i, 2, QTableWidgetItem(r["value"]))
                table.setItem(i, 3, QTableWidgetItem(r["updated"]))
            lay.addWidget(table, 1)

            def _delete_selected():
                if not table.selectedItems():
                    return
                row_idx = table.currentRow()
                cat = table.item(row_idx, 0).text()
                key = table.item(row_idx, 1).text()
                if confirm(
                    self, _t("dlg_mem_del_title"), _t("dlg_mem_del_body", cat=cat, key=key)
                ):
                    self.memory_db.delete(cat, key)
                    table.removeRow(row_idx)

            del_btn = PrimaryButton(_t("dlg_mem_del_btn"), kind="danger")
            del_btn.setFixedHeight(32)
            del_btn.clicked.connect(_delete_selected)
            lay.addWidget(del_btn)

        close_btn = GhostButton("Закрыть")
        close_btn.setFixedHeight(32)
        close_btn.clicked.connect(self.reject)
        lay.addWidget(close_btn)
