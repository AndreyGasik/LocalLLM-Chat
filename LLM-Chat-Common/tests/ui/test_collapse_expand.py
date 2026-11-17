#!/usr/bin/env python3
# Запуск: python3 LLM-Chat-Common/tests/ui/test_collapse_expand.py  (offscreen; каждый тест — отдельный процесс)
# Спец-тест: сворачивание/разворачивание блоков и прыжки элементов.
import os, sys, traceback, time
os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
# Путь к app/ вычисляется от расположения скрипта — тесты живут в репо
_HERE = os.path.dirname(os.path.abspath(__file__))
APP = os.path.abspath(os.path.join(_HERE, "..", "..", "..", "app"))
os.chdir(APP); sys.path.insert(0, APP)
sys.excepthook = lambda *a: traceback.print_exception(*a)
from PyQt6.QtWidgets import QApplication
from PyQt6.QtCore import QTimer, QPoint
app = QApplication([])
import i18n, theme
from base import ChatMainWindow
import core.common_loader as cl
BotReplyWidget = cl.load_common_module("ui/bubble").BotReplyWidget

win = ChatMainWindow(); win.resize(1100, 760); win.show()
FAIL = []
def check(name, cond, info=""):
    print(("PASS " if cond else "FAIL ") + name + (f"  [{info}]" if info and not cond else ""))
    if not cond: FAIL.append(name)

def drive():
    try:
        ca = win.chat_area
        ca.clear_chat()
        ca.set_show_thoughts(True)
        # высокий документ: 3 пары + финальный ответ с высоким блоком мыслей
        for m in range(3):
            ca.append_user(f"Вопрос {m}", msg_index=m*2)
            ca.append_assistant_message("Ответ " + "абзац текста. " * 40, "m", m*2+1)
        ca.append_user("Мой вопрос к модели", msg_index=6)
        ca.start_bot_response("lfm3-1.7b", True, msg_index=7)
        ca.append_thought_chunk("Расуждаю вслух. " * 120)
        ca.append_chunk("Текст первого раунда. ")
        ca.append_tool_call("SEARCH", "запрос")
        ca.append_tool_result("✓ найдено", "детали")
        ca.append_chunk("Финальный вывод ответа, ещё немного текста.")
        ca.finish_response(2.0, 100, 50.0, 0.3)
        for _ in range(20): app.processEvents(); time.sleep(0.01)

        sb = ca.verticalScrollBar()
        reply = next((w for w, _ in reversed(ca._bubbles) if isinstance(w, BotReplyWidget)), None)
        tw = reply._thought
        rows = [w for (w, _) in ca._bubbles]            # верхний уровень
        ghosts = lambda: len(ca._content.children()) - len(rows) - len(reply._bubbles) \
                         - len(reply._tool_rows) - len(reply._cards) - 1  # -1 = stretch нет (кто?) → проверим по фактам
        moves = []
        sb.valueChanged.connect(lambda v: moves.append(v))

        def snapshot():
            return {id(w): w.mapTo(ca._content, QPoint(0,0)).y() for w in rows}

        # ═══ Сценарий A: сворачивание в середине документа ═══
        sb.setValue(max(0, sb.maximum() // 3)); ca._autoscroll = False
        for _ in range(10): app.processEvents(); time.sleep(0.01)
        moves.clear()
        before = snapshot()
        hdr_vp = tw._header.mapTo(ca.viewport(), QPoint(0,0)).y()
        val0 = sb.value()
        tw._toggle()                                    # свернуть
        for _ in range(15): app.processEvents(); time.sleep(0.01)
        after = snapshot()
        # значение скролла не дёрнулось ни разу
        check("A: value не двигался при collapse", moves == [], f"moves={moves[:8]}")
        # строки ВЫШЕ блока (включая заголовок) стоят на месте
        hdr_doc_before = tw._header.mapTo(ca._content, QPoint(0,0)).y()
        hdr_doc_after  = tw._header.mapTo(ca._content, QPoint(0,0)).y()
        check("A: заголовок на месте (doc)", hdr_doc_before == hdr_doc_after)
        above_ok = all(after[id(w)] == before[id(w)] for w in rows
                       if w.mapTo(ca._content, QPoint(0,0)).y() < hdr_doc_before - 1)
        check("A: строки выше блока неподвижны", above_ok)
        # якорь: заголовок в той же точке viewport
        hdr_vp_after = tw._header.mapTo(ca.viewport(), QPoint(0,0)).y()
        check("A: якорь заголовка (vp)", hdr_vp == hdr_vp_after, f"{hdr_vp} -> {hdr_vp_after}")
        # призраков нет: считаем только ВИДИМЫХ детей (скрытые
        # deleteLater-pending виджеты не рисуются и не мешают)
        vis = [ch for ch in ca._content.children() if ch.isWidgetType() and ch.isVisible()]
        check("A: призраков нет", len(vis) == len(rows), f"visible={len(vis)}, rows={len(rows)}")
        # высота блока ужалась
        tw_doc_h = tw.height()
        check("A: блок ужался", tw_doc_h < 60, f"h={tw_doc_h}")

        # ═══ Сценарий B: развернуть обратно ═══
        moves.clear()
        collapsed_before = snapshot()
        tw._toggle()                                    # развернуть
        for _ in range(15): app.processEvents(); time.sleep(0.01)
        after2 = snapshot()
        check("B: value не двигался при expand", moves == [], f"moves={moves[:8]}")
        expanded_ok = all(after2[id(w)] == before[id(w)] for w in rows)
        check("B: все строки вернулись точно", expanded_ok)
        hdr_vp_re = tw._header.mapTo(ca.viewport(), QPoint(0,0)).y()
        check("B: якорь заголовка (vp)", hdr_vp == hdr_vp_re, f"{hdr_vp} -> {hdr_vp_re}")

        # ═══ Сценарий C: повторные toggle-циклы (5 раз) ═══
        moves.clear()
        ok = True
        for i in range(5):
            tw._toggle()
            for _ in range(6): app.processEvents()
            tw._toggle()
            for _ in range(6): app.processEvents()
            y = tw._header.mapTo(ca.viewport(), QPoint(0,0)).y()
            if y != hdr_vp: ok = False
        check("C: 5 циклов toggle — якорь стабилен", ok)
        check("C: value не двигался за 10 toggle", moves == [], f"moves={moves[:8]}")

        # ═══ Сценарий D: collapse у низа (bottom-stick) ═══
        ca._autoscroll = True
        sb.setValue(sb.maximum())
        for _ in range(6): app.processEvents()
        v0 = sb.value(); m0 = sb.maximum()
        tw._toggle()                                    # свернуть у низа
        for _ in range(10): app.processEvents(); time.sleep(0.01)
        check("D: у низа — остались у низа", sb.value() >= sb.maximum() - 1,
              f"{sb.value()}/{sb.maximum()} (было {v0}/{m0})")
        tw._toggle()
        for _ in range(10): app.processEvents(); time.sleep(0.01)
        check("D: развернули у низа — снова у низа", sb.value() >= sb.maximum() - 1)

        # ═══ Сценарий E: стриминг — прыжки элементов ВЫШЕ растущего блока ═══
        ca.append_user("Следующий вопрос", msg_index=8)
        ca.start_bot_response("lfm3-1.7b", True, msg_index=9)
        for _ in range(10): app.processEvents(); time.sleep(0.01)
        snap = snapshot()
        moves.clear()
        ok_above = True; ok_bottom = True; ok_monotonic = True
        last_max = -1
        for i in range(25):
            ca.append_chunk(f"Строка {i} растущего ответа, достаточно длинная для переноса. ")
            ca._flush_buffers()
            app.processEvents()
            s2 = snapshot()
            # все СТАРЫЕ строки неподвижны в документе
            for k, v in snap.items():
                if s2.get(k) != v: ok_above = False
            if sb.value() < sb.maximum() - 1: ok_bottom = False
            if sb.maximum() < last_max: ok_monotonic = False
            last_max = sb.maximum()
        check("E: стриминг — старые строки неподвижны", ok_above)
        check("E: стриминг — держим низ", ok_bottom)
        check("E: стриминг — max растёт монотонно", ok_monotonic)
        ca.finish_response(1.0, 300, 90.0, 0.1)
        for _ in range(10): app.processEvents(); time.sleep(0.01)

        # финальная проверка призраков после всего
        vis = [ch for ch in ca._content.children() if ch.isWidgetType() and ch.isVisible()]
        top_rows = len(ca._bubbles)
        check("F: призраков нет после всех операций", len(vis) == top_rows,
              f"visible={len(vis)}, rows={top_rows}")

        print()
        print("FAILED:" if FAIL else "ALL PASS", FAIL if FAIL else "")
    finally:
        win.close(); app.quit()

QTimer.singleShot(300, drive)
app.exec()
sys.exit(1 if FAIL else 0)
