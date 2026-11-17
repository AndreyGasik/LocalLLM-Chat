#!/usr/bin/env python3
# Запуск: python3 LLM-Chat-Common/tests/ui/test_qscroll_chat.py  (offscreen; каждый тест — отдельный процесс)
# Smoke-тест перестроенной ленты чата (QScrollArea + секционный BotReply).
import os, sys
os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
# Путь к app/ вычисляется от расположения скрипта — тесты живут в репо
_HERE = os.path.dirname(os.path.abspath(__file__))
APP = os.path.abspath(os.path.join(_HERE, "..", "..", "..", "app"))
sys.path.insert(0, APP)
from core.common_loader import load_common_module

from PyQt6.QtWidgets import QApplication
from PyQt6.QtCore import QPoint
app = QApplication([])

ca_mod = load_common_module("ui/chat_area")
ChatArea = ca_mod.ChatArea
bubble_mod = load_common_module("ui/bubble")
sw_mod = load_common_module("ui/stream_widgets")

FAIL = []
def check(name, cond, info=""):
    print(("PASS " if cond else "FAIL ") + name + (f"  [{info}]" if info and not cond else ""))
    if not cond: FAIL.append(name)

# ── конструирование ──
area = ChatArea()
area.resize(500, 320)
area.show()
app.processEvents()
check("construct", area._lay is not None)

# ── пользователь ──
area.append_user("Привет, найди информацию о Ленине", msg_index=0)
app.processEvents()
check("user bubble added", len(area._bubbles) == 1)

# ── стриминговый ответ с мыслями и двумя раундами ──
area.set_show_thoughts(True)
area.start_bot_response("qwen3:4b", tools_active=True, msg_index=1)
area.append_thought_chunk("Пользователь спрашивает про Ленина. ")
area.append_thought_chunk("Надо воспользоваться поиском.")
for ch in ["Владимир ", "Ильич ", "Ленин ", "родился ", "в Симбирске."]:
    area.append_chunk(ch)
app.processEvents()
area._flush_buffers()   # в приложении текст сбрасывает 33мс таймер; в тесте — явно
app.processEvents()
reply = area._bot_reply
check("reply created", reply is not None)
check("thought block exists", reply._thought is not None)
check("bubble round 1 exists", len(reply._bubbles) == 1 and reply._bubbles[0].label._text.strip() != "")
check("thinking hidden", reply._indicator is None)

# ── round 2: инструмент + новый текст ──
area.mark_round_start()
area.append_tool_call("SEARCH", "Ленин место рождения")
area.append_tool_result("✓ поиск: 3 результата", "simbirsk.ru …")
for ch in ["По данным источников, ", "он родился в Симбирске."]:
    area.append_chunk(ch)
area.trim_stream_to_round("Он родился в Симбирске 22 апреля 1870 года.")
area.finish_response(3.2, 250, 78.1, 0.42)
app.processEvents()
check("two text bubbles", len(reply._bubbles) == 2, f"got {len(reply._bubbles)}")
check("tool rows outside frame", len(reply._tool_rows) == 2)
check("stats footer", reply._stats_lbl is not None and "tok/s" in reply._stats_lbl.text())
check("plain text joined", "Симбирске" in reply._plain_text)

# ── markdown-финализация ──
check("markdown rendered", reply._bubbles[0].label._is_markdown)

# ── экспорт ──
txt = area.toPlainText()
check("export has user", "[Вы]" in txt)
check("export has assistant", "[Ассистент]" in txt)
check("export has thoughts", "[Мысли]" in txt)
check("export has tool", "SEARCH" in txt)

# ── стабильность toggle: якорь заголовка и неподвижность скролла ──
# добавим ещё один пользовательский баббл ниже, чтобы был контент под блоком
area.append_user("Спасибо!", msg_index=2)
app.processEvents()

sb = area.verticalScrollBar()
# уходим от низа с подтверждением (как реальный пользователь)
area._autoscroll = False
sb.setValue(sb.maximum() // 3)
app.processEvents()

vp = area.viewport()
tw = reply._thought
hdr_y_before = tw._header.mapTo(vp, QPoint(0, 0)).y()
tw._toggle()          # свернуть; handler якорит синхронно + singleShot(0) доводка
app.processEvents()   # асинхронные усадки widgetResizable/reflow тоже усаживаются
hdr_y_after = tw._header.mapTo(vp, QPoint(0, 0)).y()
check("toggle: header anchored", hdr_y_after == hdr_y_before,
      f"{hdr_y_before} -> {hdr_y_after}")
check("toggle: bubbles kept size", all(b.label.height() > 10 for b in reply._bubbles))

tw._toggle()          # развернуть обратно
app.processEvents()
hdr_y_re = tw._header.mapTo(vp, QPoint(0, 0)).y()
check("toggle back: header anchored", hdr_y_re == hdr_y_before,
      f"{hdr_y_before} -> {hdr_y_re}")

# ── автоскролл во время стриминга держит низ ──
area.append_user("Ещё вопрос", msg_index=3)
area.start_bot_response("qwen3:4b", False, msg_index=4)
ok_bottom = True
for i in range(40):
    area.append_chunk(f"Строка номер {i} достаточно длинная для переноса. ")
    app.processEvents()
    if sb.value() < sb.maximum() - 1:
        ok_bottom = False
check("streaming: stuck to bottom", ok_bottom)
area.finish_response(1.0, 500, 90.0, 0.1)
app.processEvents()

# ── история: готовое сообщение ──
area.append_assistant_message("Готовый **ответ** из истории", "qwen3:4b", 5)
app.processEvents()
last = area._bubbles[-1][0]
check("history reply markdown", "**" not in last._bubbles[0].label.toPlainText())
check("history reply footer buttons", last._action_frame is not None and last._stats_lbl is not None)

# ── удаление от индекса ──
n_before = len(area._bubbles)
area.remove_from_index(3)
app.processEvents()
check("remove_from_index", all(i < 3 for _, i in area._bubbles) and len(area._bubbles) < n_before)

# ── очистка ──
area.clear_chat()
app.processEvents()
check("clear_chat", len(area._bubbles) == 0 and area._lay.count() == 1)

# ── пустое состояние не падает (paint) ──
area.viewport().update()
app.processEvents()
check("empty state paint ok", True)

print()
print("FAILED:" if FAIL else "ALL PASS", FAIL if FAIL else "")
sys.exit(1 if FAIL else 0)
