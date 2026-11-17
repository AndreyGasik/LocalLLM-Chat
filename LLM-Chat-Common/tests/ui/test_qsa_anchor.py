#!/usr/bin/env python3
# Чистый эксперимент (документация поведения Qt):
# Запуск: python3 LLM-Chat-Common/tests/ui/test_qsa_anchor.py
# Чистый эксперимент: как QScrollArea меняет value при ужании/росте виджета.
import os
os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
from PyQt6.QtWidgets import QApplication, QScrollArea, QWidget, QVBoxLayout, QLabel
from PyQt6.QtCore import Qt
app = QApplication([])

sa = QScrollArea()
sa.setWidgetResizable(True)
sa.resize(400, 300)
content = QWidget()
lay = QVBoxLayout(content)
lay.setContentsMargins(0, 0, 0, 0)
labels = [QLabel(f"строка {i:02d} — текст для высоты") for i in range(60)]
for l in labels:
    lay.addWidget(l)
sa.setWidget(content)
sa.show()
app.processEvents()
sb = sa.verticalScrollBar()
print("viewport h:", sa.viewport().height(), "content h:", content.height(), "max:", sb.maximum())

def log(tag):
    print(f"{tag}: value={sb.value()} max={sb.maximum()} content_y={content.y()} content_h={content.height()}")

sb.valueChanged.connect(lambda v: print(f"  [valueChanged -> {v}]"))

# Кейс 1: середина документа, ужать контент на ~10 строк
sb.setValue(sb.maximum() // 3)
app.processEvents()
log("mid, before shrink")
for l in labels[-12:]:
    l.hide()
content.adjustSize()
log("after adjustSize (shrink 12 lines)")
app.processEvents()
log("after processEvents")

# Кейс 2: вернуть, ужать при bottom visible
for l in labels[-12:]:
    l.show()
content.adjustSize()
app.processEvents()
sb.setValue(sb.maximum())
log("bottom, before shrink")
for l in labels[-12:]:
    l.hide()
content.adjustSize()
log("after adjustSize (shrink at bottom)")
app.processEvents()
log("after processEvents")

# Кейс 3: рост контента в середине
sb.setValue(sb.maximum() // 3)
app.processEvents()
log("mid, before grow")
for l in labels[-12:]:
    l.show()
content.adjustSize()
log("after adjustSize (grow 12 lines)")
app.processEvents()
log("after processEvents")
