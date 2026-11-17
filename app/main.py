#!/usr/bin/env python3
# main.py — единая точка входа LLM Chat (llama.cpp / Ollama).
#
# Запуск: ./main.py  или  python3 main.py  (из каталога app/)
# Двойной щелчок в файловом менеджере работает при наличии shebang + chmod +x.
import sys
import os
import traceback
import threading

_HERE = os.path.dirname(os.path.abspath(__file__))
_ROOT = os.path.dirname(_HERE)       # repo root (для Common)
if _HERE not in sys.path:
    sys.path.insert(0, _HERE)
os.chdir(_HERE)

os.environ.setdefault("QT_QPA_PLATFORM", "xcb")

# Перехватчик исключений: вместо qFatal (abort) печатает traceback и
# продолжает работу. Без него любое исключение в paintEvent/slot убивает
# приложение (PyQt6 вызывает qFatal при необработанном исключении).
def _qt_excepthook(t, v, tb):
    traceback.print_exception(t, v, tb)
    sys.stderr.write("── EXCEPTION (см. выше; приложение продолжило работу)\n")

sys.excepthook = _qt_excepthook

def _thread_excepthook(args):
    if args.exc_type is SystemExit:
        return
    traceback.print_exception(args.exc_type, args.exc_value, args.exc_traceback)
    sys.stderr.write("── THREAD EXCEPTION\n")

threading.excepthook = _thread_excepthook

from PyQt6.QtWidgets import QApplication

import i18n     # осознанно РАНЬШЕ theme: закрепляет sys.modules['i18n'] за обёрткой app/i18n.py
import theme

from base import ChatMainWindow
from theme import make_app_icon


def main():
    sys.argv[0] = "llm-chat"
    app = QApplication(sys.argv)
    app.setApplicationName("LLM Chat")
    app.setApplicationDisplayName("LLM Chat")
    app.setWindowIcon(make_app_icon())
    theme.setup_app(app)

    window = ChatMainWindow()
    window.show()

    sys.exit(app.exec())


if __name__ == "__main__":
    main()
