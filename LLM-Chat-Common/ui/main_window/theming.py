# ui/main_window/theming.py
import json

from PyQt6.QtCore import Qt
from PyQt6.QtGui import QAction

from theme import get_palette as _P, toggle_theme, app_qss, strip_emoji
from i18n import _t, get_lang
from config import HISTORY_FILE


class ThemingMixin:
    def _toggle_theme(self):
        toggle_theme()
        p = _P()
        self.retheme()                      # фон окна, заголовок и его кнопки (Aurora)
        self._apply_theme_styles(p)
        self._save_settings_and_history()

    def _toggle_lang(self):
        """Queue a language change that takes effect on next launch."""
        # Read the setting that was last saved (may differ from get_lang() if
        # user toggled multiple times before restarting)
        if HISTORY_FILE.exists():
            try:
                saved = json.loads(HISTORY_FILE.read_text(encoding="utf-8"))
                current = saved.get("settings", {}).get("lang", get_lang())
            except Exception:
                current = get_lang()
        else:
            current = get_lang()
        next_lang = "en" if current == "ru" else "ru"
        # Persist immediately so the next launch picks it up
        self._save_settings_and_history_with_lang(next_lang)
        other = "EN" if next_lang == "ru" else "RU"
        self.lang_btn.setText(other)
        self.status_bar.setText(_t("lang_pending"))

    def _apply_theme_styles(self, p: dict):
        # Весь вид — из Aurora (FORM_QSS) + QSS приложения; фон не задаётся
        # (стекло рисует рамка окна), поэтому корневого background здесь нет.
        self.setStyleSheet(app_qss())
        self.theme_btn.update()               # значок «солнце/луна» рисуется по текущей теме
        self._rebuild_menu()
        self.chat_area.apply_theme(p)
        self._refresh_spin_arrow_colors()
        for sec in (getattr(self, "_sec_model", None), getattr(self, "_sec_gen", None)):
            if sec is not None:
                sec.refresh_theme()
        if hasattr(self, "web_link_label"):
            self._update_web_link()

    def _rebuild_menu(self):
        p = _P()
        self.act_menu.clear()
        # popup со скруглёнными углами: окно меню прозрачное, фон рисует QSS
        self.act_menu.setWindowFlags(self.act_menu.windowFlags()
                                     | Qt.WindowType.FramelessWindowHint
                                     | Qt.WindowType.NoDropShadowWindowHint)
        self.act_menu.setAttribute(Qt.WidgetAttribute.WA_TranslucentBackground)
        for label, slot in [
            (_t("menu_save_history"), self._save_history_manual),
            (_t("menu_export"),       self._export_txt),
            # Выгрузка модели из памяти — только у Ollama-бэкенда (llama.cpp
            # выгружает модель вместе с процессом llama-server при «Остановить»)
            *([(_t("menu_unload"), self._unload_model)]
              if getattr(self, "backend", "llama") == "ollama" else []),
            (None, None),
            (_t("menu_clear_history"), self._clear_history),
        ]:
            if label is None:
                self.act_menu.addSeparator()
            else:
                self.act_menu.addAction(QAction(strip_emoji(label), self, triggered=slot))


