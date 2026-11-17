#!/usr/bin/env python3
# Запуск: python3 LLM-Chat-Common/tests/ui/test_full_window.py  (offscreen; каждый тест — отдельный процесс)
# Полная сборка окна: якорь при чтении выше низа; прилипание к низу при autoscroll.
import os, sys, traceback
os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
# Путь к app/ вычисляется от расположения скрипта — тесты живут в репо
_HERE = os.path.dirname(os.path.abspath(__file__))
APP = os.path.abspath(os.path.join(_HERE, "..", "..", "..", "app"))
os.chdir(APP); sys.path.insert(0, APP)
def hook(t, v, tb): traceback.print_exception(t, v, tb)
sys.excepthook = hook

from PyQt6.QtWidgets import QApplication
from PyQt6.QtCore import QTimer, QPoint
app = QApplication([])
import i18n, theme
from base import ChatMainWindow
import core.common_loader as cl
BotReplyWidget = cl.load_common_module("ui/bubble").BotReplyWidget

win = ChatMainWindow(); win.resize(1100, 720); win.show()

def drive():
    try:
        ca = win.chat_area
        ca.append_user("Тест", msg_index=900)
        ca.set_show_thoughts(True)
        ca.start_bot_response("test-model", True, msg_index=901)
        ca.append_thought_chunk("думаю…" + " очень длинная мысль " * 40)
        ca.append_chunk("Ответ **жирный** и `код`.")
        ca.mark_round_start()
        ca.append_tool_call("SEARCH", "тест запрос")
        ca.append_tool_result("найдено 1", "detail …")
        ca.append_chunk("Итоговый вывод.")
        ca.finish_response(2.0, 100, 50.0, 0.3)
        app.processEvents()
        sb = ca.verticalScrollBar()
        reply = ca._bot_reply if ca._bot_reply else next(
            (w for w, _ in reversed(ca._bubbles) if isinstance(w, BotReplyWidget)), None)
        hdr = reply._thought._header

        # Кейс 1: чтение выше низа → якорь заголовка стабилен при toggle
        sb.setValue(max(0, sb.maximum() // 2))
        ca._autoscroll = False
        app.processEvents()
        y0 = hdr.mapTo(ca.viewport(), QPoint(0, 0)).y()
        v0 = sb.value()
        reply._thought._toggle()          # свернуть
        app.processEvents()
        y1 = hdr.mapTo(ca.viewport(), QPoint(0, 0)).y()
        assert y0 == y1, f"anchor moved: {y0} -> {y1}"
        assert sb.value() == v0, f"scroll moved {v0} -> {sb.value()}"
        reply._thought._toggle()          # развернуть
        app.processEvents()
        y2 = hdr.mapTo(ca.viewport(), QPoint(0, 0)).y()
        assert y0 == y2, f"anchor moved on expand: {y0} -> {y2}"
        print("case1 anchor PASS", y0)

        # Кейс 2: у низа → держим низ (контент вырос вниз)
        ca._autoscroll = True
        sb.setValue(sb.maximum())
        app.processEvents()
        h0 = ca._content.height()
        reply._thought._toggle()          # свернуть (контент сжался)
        app.processEvents()
        # после сворачивания у низа вьюпорт остаётся прижат к низу
        assert sb.value() >= sb.maximum() - 1, f"not at bottom: {sb.value()}/{sb.maximum()}"
        reply._thought._toggle()          # обратно
        app.processEvents()
        assert sb.value() >= sb.maximum() - 1
        print("case2 bottom-stick PASS")
        print("FULL WINDOW PASS")
    finally:
        win.close(); app.quit()

QTimer.singleShot(300, drive)
app.exec()
