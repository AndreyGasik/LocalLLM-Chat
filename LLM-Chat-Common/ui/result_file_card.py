# ui/result_file_card.py
from pathlib import Path
from PyQt6.QtWidgets import QWidget, QVBoxLayout, QHBoxLayout, QFileDialog, QMessageBox
from PyQt6.QtCore import QUrl
from PyQt6.QtGui import QDesktopServices
from ui.widgets import FileCard
from aurora import GhostButton
from i18n import get_lang


class ResultFileCard(QWidget):
    """
    Карточка файла, который сгенерировала модель (черновик лежит в
    изолированной папке вывода, см. config.GENERATED_FILES_DIR).

    Ничего не перезаписывает автоматически: «Сохранить как» — это
    явное действие пользователя через стандартный диалог, «Открыть»
    просто открывает черновик системным просмотрщиком.
    """
    def __init__(self, path: str, parent=None):
        super().__init__(parent)
        self.path = path
        lay = QVBoxLayout(self)
        lay.setContentsMargins(0, 0, 0, 0)
        lay.setSpacing(6)

        self.card = FileCard(path, self)
        lay.addWidget(self.card)

        btn_row = QHBoxLayout()
        btn_row.setSpacing(6)

        self.btn_open = GhostButton("Открыть" if get_lang() == "ru" else "Open")
        self.btn_open.setFixedHeight(28)
        self.btn_open.clicked.connect(self._open_file)
        btn_row.addWidget(self.btn_open)

        self.btn_save = GhostButton("Сохранить как…" if get_lang() == "ru" else "Save as…")
        self.btn_save.setFixedHeight(28)
        self.btn_save.clicked.connect(self._save_as)
        btn_row.addWidget(self.btn_save)

        btn_row.addStretch()
        lay.addLayout(btn_row)

        self._apply_theme()

    def _open_file(self):
        QDesktopServices.openUrl(QUrl.fromLocalFile(self.path))

    def _save_as(self):
        src = Path(self.path)
        dest, _ = QFileDialog.getSaveFileName(
            self,
            "Сохранить как" if get_lang() == "ru" else "Save as",
            str(Path.home() / src.name)
        )
        if not dest:
            return
        try:
            Path(dest).write_bytes(src.read_bytes())
        except Exception as e:
            QMessageBox.warning(self, "Ошибка" if get_lang() == "ru" else "Error", str(e))

    def _apply_theme(self):
        # кнопки (GhostBtn) рисуются по токенам Aurora — отдельный QSS не нужен
        self.btn_open.update()
        self.btn_save.update()

    def recolor(self):
        self.card.recolor()
        self._apply_theme()
