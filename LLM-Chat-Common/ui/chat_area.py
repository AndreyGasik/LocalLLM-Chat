# ui/chat_area.py
"""Лента чата.

Перестроена с QListView+setIndexWidget на QScrollArea+QVBoxLayout
(2026-11-16). QListView — model/view-механизм со статичными строками:
каждый рост текста запускал цепочку dataChanged→sizeHintChanged→
doItemsLayout(), делегат опрашивал осциллирующие sizeHint QTextEdit, а
doItemsLayout() сам умел сдвигать прокрутку. Побеждять это пришлось
«наслоением на наслоение»: таймерный замок позиции, suppress-флаги,
монотонный гард range, кэш _row_height в делегате — и дрожание всё равно
оставалось при стриминге и toggle блоков.

Обычный QVBoxLayout в QScrollArea раскладывает те же виджеты напрямую и
детерминированно: один виджет вырос → один проход раскладки → один
rangeChanged у скроллбара. Все перечисленные костыли удалены вместе с
делегатом и моделью (ui/chat_model.py).

Структура ответа бота — секционная (см. ui/bubble.py): мысли/инструменты
строками вне рамки, текст — в TextBubble; toggle блока не трогает бабблы.
"""
import re

from PyQt6.QtWidgets import QScrollArea, QFrame, QWidget, QLabel, QVBoxLayout
from PyQt6.QtCore import Qt, QTimer, pyqtSignal, QRectF, QCoreApplication, QEvent
from PyQt6.QtGui import QColor, QFontMetrics, QPainter, QPen

from theme import get_palette as _P
from i18n import _t
from aurora import font, font_mono, ink
from chat_widgets import ErrorRow
from ui.bubble import BubbleWidget, BotReplyWidget
from ui.stream_widgets import _CollapsibleToolWidget


def _tool_export_text(ww) -> str:
    """Текст блока инструмента для экспорта: без HTML-сущностей (&gt;),
    без значка раскрытия (▶/▼/>/v), с аргументами вызова и пометкой ✓ у
    результата."""
    import html as _html
    header = _html.unescape(re.sub(r'<[^>]+>', '', ww._header_lbl.text())).strip()
    header = re.sub(r'^(?:[▶▼>]|v)\s+', '', header)
    if getattr(ww, "_role", "call") == "call":
        detail = (getattr(ww, "_detail", "") or "").strip()
        if detail and not detail.startswith("Инструмент:") and detail not in header:
            header = f"{header}: {detail.splitlines()[0][:200]}"
    else:
        if not header.startswith(("✓", "⚠")):
            header = f"✓ {header}"
    return header


class _ChatViewport(QWidget):
    """Viewport ленты с колбэком рисования пустого состояния. Отдельный
    подкласс вместо eventFilter — рисунок идёт штатным paintEvent ПОСЛЕ
    отрисовки самого viewport (прозрачного, сквозь него виден фон Aurora)."""

    def __init__(self, hook, parent=None):
        super().__init__(parent)
        self._hook = hook

    def paintEvent(self, event):
        super().paintEvent(event)
        if self._hook:
            self._hook()


class ChatArea(QScrollArea):
    copy_requested   = pyqtSignal(str)
    regen_requested  = pyqtSignal(int)
    edit_requested   = pyqtSignal(int, str)
    resend_requested = pyqtSignal(int)
    verify_requested = pyqtSignal(int, str)

    def __init__(self, parent=None):
        super().__init__(parent)
        self._model_name = ""          # имя модели для пустого состояния
        self.setWidgetResizable(True)
        self.setFrameShape(QFrame.Shape.NoFrame)
        # Скроллбар ВСЕГДА видим (узкий, 6px): его появление/исчезание в
        # момент, когда контент перерастает окно, меняло бы ширину viewport
        # на эти 6px — лишний перенос строк во всех QTextEdit ленты и
        # заметный «вздрагивающий» рефлоу (один из источников дрожания в
        # QListView-версии).
        self.setVerticalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOn)
        self.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)

        sb = self.verticalScrollBar()
        sb.setSingleStep(20)
        sb.setPageStep(200)

        self.setViewport(_ChatViewport(self._paint_empty_state))
        self.viewport().setAutoFillBackground(False)   # фон окна Aurora виден сквозь ленту

        self._content = QWidget()
        self._content.setObjectName("chat_content")
        self._lay = QVBoxLayout(self._content)
        self._lay.setContentsMargins(0, 6, 0, 6)
        self._lay.setSpacing(6)
        self._lay.addStretch(1)        # контент прижат кверху при малой высоте
        self.setWidget(self._content)

        # Автоскролл: «у низа ли» — единственный источник истины. Прилипание
        # к низу происходит синхронно в rangeChanged (тем же проходом, что и
        # рост контента — без промежуточных кадров). Уход от низа
        # подтверждается 60 мс, чтобы транзитные программные прыжки не роняли
        # автоскролл; возврат к низу — мгновенный.
        self._autoscroll = True
        self._bottom_timer = QTimer(self)
        self._bottom_timer.setSingleShot(True)
        self._bottom_timer.setInterval(60)
        self._bottom_timer.timeout.connect(self._confirm_left_bottom)
        sb.rangeChanged.connect(self._on_scrollbar_range_changed)
        sb.valueChanged.connect(self._on_scrollbar_value_changed)

        self.setStyleSheet(
            "QScrollArea { background: transparent; border: none; }"
            "QWidget#chat_content { background: transparent; }"
            + self._scroll_stylesheet(_P())
        )

        self._bubbles = []             # [(widget, msg_index)]

        self._bot_reply: BotReplyWidget | None = None
        self._thought_widget = None
        self._in_thought = False
        self._show_thoughts = False
        self._marker_buf = ""
        self._bot_active = False
        self._chunk_buf = ""
        self._thought_buf = ""
        self._bot_msg_index = -1
        self._thought_gap_pending = False

        # Живое подавление сырых тегов вызова инструментов в потоке
        # (<tool_call>...</tool_call> / <|tool_call_start|>...<|tool_call_end|>))
        # — независимый слой ПЕРЕД обработкой <think> в append_chunk, чтобы не
        # трогать уже отлаженную логику мыслей. Сам вызов инструмента и так
        # показывается отдельным виджетом через append_tool_call, а очищенный
        # текст всё равно подставляется через trim_stream_to_round.
        self._toolcall_marker_buf = ""
        self._toolcall_buf = ""
        self._toolcall_close = None

        self._flush_timer = QTimer(self)
        self._flush_timer.setInterval(33)
        self._flush_timer.timeout.connect(self._flush_buffers)
        self._flush_timer.start()

    # ── пустое состояние: тихая сцена-приглашение вместо мёртвого серого поля ──
    def set_model_name(self, name: str):
        if name != self._model_name:
            self._model_name = name
            self.viewport().update()

    def resizeEvent(self, event):
        super().resizeEvent(event)
        self.viewport().update()

    def _paint_empty_state(self):
        if self._bubbles or self._bot_active:
            return
        vp = self.viewport()
        p = QPainter(vp)
        p.setRenderHint(QPainter.RenderHint.Antialiasing)
        p.setRenderHint(QPainter.RenderHint.TextAntialiasing)
        pal = _P()
        w, h = vp.width(), vp.height()
        cy = int(h * 0.42)                       # оптический центр — чуть выше середины

        # маячок: янтарная точка статуса + имя модели моно-цифрами
        fm = QFontMetrics(font_mono(15))
        name = self._model_name or "…"
        dot_r = 3.0
        row_w = 6 + dot_r * 2 + 8 + fm.horizontalAdvance(name)
        x0 = (w - row_w) / 2
        p.setPen(Qt.PenStyle.NoPen)
        p.setBrush(QColor(pal["ACCENT"]))
        p.drawEllipse(QRectF(x0 + 6, cy - dot_r, dot_r * 2, dot_r * 2))
        p.setFont(font_mono(15))
        p.setPen(QColor(pal["TEXT"]))
        p.drawText(QRectF(x0 + 6 + dot_r * 2 + 8, cy - 12, row_w, 24),
                   Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignVCenter, name)

        # подсказка
        p.setFont(font(12))
        p.setPen(QColor(pal["DIM"]))
        p.drawText(QRectF(0, cy + 20, w, 20),
                   Qt.AlignmentFlag.AlignHCenter | Qt.AlignmentFlag.AlignVCenter, _t("empty_hint"))

        # клавиши: [Enter] отправить · [Shift+Enter] новая строка
        kf = font_mono(10)
        kfm = QFontMetrics(kf)
        key1, key2 = "Enter", "Shift+Enter"
        lbl1, lbl2 = _t("kbd_send"), _t("kbd_newline")
        cap = lambda s_: kfm.horizontalAdvance(s_) + 14
        lab = lambda s_: QFontMetrics(font(11)).horizontalAdvance(s_)
        row_w2 = cap(key1) + 6 + lab(lbl1) + 20 + cap(key2) + 6 + lab(lbl2)
        x = (w - row_w2) / 2
        y = cy + 52
        for key, lbl in ((key1, lbl1), (key2, lbl2)):
            kw = cap(key)
            kr = QRectF(x, y - 9, kw, 18)
            p.setPen(QPen(ink(26), 1))
            p.setBrush(ink(8))
            p.drawRoundedRect(kr, 5, 5)
            p.setFont(kf)
            p.setPen(QColor(pal["DIM"]))
            p.drawText(kr, Qt.AlignmentFlag.AlignCenter, key)
            x += kw + 6
            p.setFont(font(11))
            p.setPen(QColor(pal["DIM"]))
            p.drawText(QRectF(x, y - 9, lab(lbl) + 4, 18),
                       Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignVCenter, lbl)
            x += lab(lbl) + 20
        p.end()

    def _scroll_stylesheet(self, p: dict) -> str:
        return f"""
            QScrollBar:vertical {{
                background: {p['SCROLLBAR']};
                width: 6px;
                border-radius: 3px;
            }}
            QScrollBar::handle:vertical {{
                background: {p['SCROLL_H']};
                border-radius: 3px;
                min-height: 20px;
            }}
            QScrollBar::handle:vertical:hover {{ background: {p['SCROLL_HH']}; }}
            QScrollBar::add-line:vertical, QScrollBar::sub-line:vertical {{ height: 0; }}
        """

    def set_show_thoughts(self, show: bool):
        self._show_thoughts = show

    def apply_theme(self, p: dict):
        self.setStyleSheet(
            "QScrollArea { background: transparent; border: none; }"
            "QWidget#chat_content { background: transparent; }"
            + self._scroll_stylesheet(p)
        )
        for bubble, _ in self._bubbles:
            if hasattr(bubble, "recolor"):
                bubble.recolor(p)

    # ── плавный попиксельный скролл колеса ──
    # QScrollArea по умолчанию шагает по singleStep (20px) на щелчок колеса —
    # лента чата должна ехать пиксельно, как в QListView-версии
    # (ScrollPerPixel). pixelDelta даёт точные пиксели (точпад/сенсорные),
    # angleDelta переводим в ~90px на стандартный щелчок (±120 · 0.75).
    def wheelEvent(self, event):
        bar = self.verticalScrollBar()
        pd = event.pixelDelta()
        if pd is not None and not pd.isNull():
            dy = pd.y()
        else:
            dy = int(event.angleDelta().y() * 0.75)
        if dy:
            bar.setValue(bar.value() - dy)
            event.accept()
        else:
            super().wheelEvent(event)

    # ── лента ──
    def _add_widget(self, w: QWidget, msg_index: int):
        """Добавляет строку ленты ПЕРЕД финальным stretch (контент прижат
        кверху, когда сообщений мало)."""
        self._lay.insertWidget(self._lay.count() - 1, w)
        self._bubbles.append((w, msg_index))
        if hasattr(w, "animate_in"):
            w.animate_in()

    def _connect_bubble(self, bubble):
        if hasattr(bubble, "copy_clicked"):
            bubble.copy_clicked.connect(self.copy_requested.emit)
        if hasattr(bubble, "regen_clicked"):
            bubble.regen_clicked.connect(self.regen_requested.emit)
        if hasattr(bubble, "edit_clicked"):
            bubble.edit_clicked.connect(self.edit_requested.emit)
        if hasattr(bubble, "resend_clicked"):
            bubble.resend_clicked.connect(self.resend_requested.emit)
        if hasattr(bubble, "verify_clicked"):
            bubble.verify_clicked.connect(self.verify_requested.emit)

    # ── скролл: механика QScrollArea ──
    def _sync_layout(self):
        """Полная СИНХРОННАЯ сборка раскладки ленты.

        Порядок критичен (урок отладки «anchor moved 1016→1062»):
        1) контент ресайзится к актуальному sizeHint ДО activate() — иначе
           activate() раскладывает по СТАРОЙ (завышенной) высоте контента и
           раздаёт лишние пиксели stretchable-элементам (заголовок имени
           13→87px, футер 36→86px — «дыхание» бабблов);
        2) activate() верхнего layout раскладывает детей по уже верной высоте;
        3) sendPostedEvents сбрасывает отложенные LayoutRequest детей
           (setGeometry ребёнка активирует ЕГО layout асинхронно — без сброса
           внутренние геометрии reply'ев остались бы старыми в момент
           измерения якоря).
        widgetResizable=True позже выставит контенту ту же геометрию
        штатно — повторного сдвига нет, размеры совпадают."""
        h = self._content.sizeHint().height()
        self._content.resize(self.viewport().width(), max(h, self.viewport().height()))
        self._lay.activate()
        # ПОЛНАЯ усадка цепочки вложенных layout'ов: sendPostedEvents
        # обрабатывает одно ПОКОЛЕНИЕ отложенных LayoutRequest за вызов
        # (события, запощенные при обработке, откладываются до следующего
        # вызова). Цепочка content→reply→TextBubble→StreamLabel занимает
        # несколько поколений: замер якоря после ОДНОГО поколения шёл по
        # недоусаженной геометрии (трассировка сворачивания: hdr doc +73)
        # — enforcement компенсировал мусор, контент отскакивал на кадр.
        for _ in range(6):
            QCoreApplication.sendPostedEvents(None, QEvent.Type.LayoutRequest)

    def _on_scrollbar_range_changed(self, _minv: int, maxv: int):
        # Прилипание к низу — в тот же проход, что и рост range. Пока
        # подтверждение ухода от низа не истекло (_bottom_timer активен —
        # пользователь только что крутил колесо вверх), не выдёргиваем ленту
        # обратно к низу на каждом flush'е.
        if self._autoscroll and not self._bottom_timer.isActive():
            self.verticalScrollBar().setValue(maxv)

    def _on_scrollbar_value_changed(self, value: int):
        sb = self.verticalScrollBar()
        if value >= sb.maximum() - 50:
            # возврат к низу — фиксируем мгновенно (ошибиться не страшно)
            self._autoscroll = True
            self._bottom_timer.stop()
        elif self._autoscroll:
            # уход от низа — НЕ по одному замеру: программные прыжки
            # (toggle блоков, восстановление истории) сначала подтверждаются
            self._bottom_timer.start()

    def _confirm_left_bottom(self):
        try:
            sb = self.verticalScrollBar()
            if sb.value() < sb.maximum() - 50:
                self._autoscroll = False
        except RuntimeError:
            pass

    def _scroll_smooth(self):
        # Раскладка теперь синхронна: никаких таймеров-отложений (в
        # QListView-версии таймер был нужен, чтобы пережить асинхронный
        # doItemsLayout). Имя метода сохранено для вызывающего кода.
        self._do_scroll()

    def _do_scroll(self):
        self._sync_layout()
        if self._autoscroll and not self._bottom_timer.isActive():
            self.verticalScrollBar().setValue(self.verticalScrollBar().maximum())

    def _scroll_to_bottom_forced(self):
        self._autoscroll = True
        self._bottom_timer.stop()
        self._sync_layout()
        sb = self.verticalScrollBar()
        sb.setValue(sb.maximum())

    def _on_collapsible_toggled(self, reply: BotReplyWidget, block: QWidget):
        """Разворачивание/сворачивание строки мыслей/инструмента.

        Строки живут вне рамки баббла, раскладка синхронна — таймерный
        замок позиции (25мс-тики QListView-версии) больше не нужен.

        Правила:
          • читатель у низа — держим низ: контент вырос/ужался, лента
            «докручивается» сама (как терминал);
          • иначе — НИКАКИХ компенсаций: заголовок блока — первый элемент
            строки, всё выше него не меняется, значит его doc-позиция
            ИНВАРИАНТНА к toggle; value скролла не трогаем вовсе, и
            заголовок остаётся в точке клика сам. Enforcement'ы (замер до,
            компенсация после) здесь ВРЕДНЫ: они измеряли якорь в разные
            моменты усадки layout-цепочки, получали разные «старые»
            позиции и дрались между собой — каждый цикл toggle накапливал
            дрейф ±4px, а промежуточные кадры давали «подскок» контента
            и следы ярких элементов (трассировки test_expand_trace3:
            moves=[526, 522, 526] — все три от наших же enforcement'ов;
            чистый эксперимент test_qsa_anchor: QScrollArea в середине
            документа value не двигает вовсе).
        Никакой автодокрутки к содержимому блока (поведение «nearest»
        как у ChatGPT/Claude)."""
        sb = self.verticalScrollBar()
        if self._autoscroll and not self._bottom_timer.isActive():
            self._sync_layout()
            sb.setValue(sb.maximum())
        else:
            self._sync_layout()
            # Полная перерисовка: быстрые сдвиги прозрачного контента поверх
            # фона окна могут оставлять следы — гасим их обновлением всего
            # viewport (после _sync_layout геометрия уже финальная).
            self.viewport().update()

    # ── добавление сообщений ──
    def append_user(self, text: str, msg_index: int = -1, files: list = None):
        bubble = BubbleWidget(msg_index=msg_index)
        bubble.add_name(_t("user_name"))
        if files:
            for f in files:
                bubble.add_file_card(f)
        bubble.add_text(text)
        bubble.set_plain_text(text)
        bubble._finalize_footer()
        self._connect_bubble(bubble)
        self._add_widget(bubble, msg_index)
        self._reset_bot_state()
        self._scroll_to_bottom_forced()

    def start_bot_response(self, model_name: str, tools_active: bool, msg_index: int = -1,
                            badge_override: str = None):
        self._reset_bot_state()
        self._bot_active = True
        if not self._flush_timer.isActive():
            self._flush_timer.start()

        badge = badge_override if badge_override is not None else ("инструменты" if tools_active else "")
        reply = BotReplyWidget(model_name, badge, msg_index)
        self._connect_bubble(reply)
        reply.show_thinking()
        self._bot_reply = reply
        self._bot_msg_index = msg_index
        self._add_widget(reply, msg_index)
        self._scroll_to_bottom_forced()

    def _ensure_thought_label(self):
        if self._thought_widget is None and self._bot_reply is not None:
            self._thought_widget = self._bot_reply.ensure_thought()
            reply = self._bot_reply
            w = self._thought_widget
            w.toggled.connect(lambda w=w: self._on_collapsible_toggled(reply, w))
        return self._thought_widget

    def _thought_with_gap(self, text: str) -> str:
        """Мысли каждого раунда генерации копятся в одном блоке. Без
        разделителя тексты раундов склеивались встык. Перед первым куском
        нового раунда вставляем пустую строку."""
        if self._thought_gap_pending and text:
            self._thought_gap_pending = False
            w = self._thought_widget
            if w is not None and w.stream_label._text.strip():
                return "\n\n" + text
        return text

    def append_thought_chunk(self, chunk: str):
        if not self._bot_active or not self._bot_reply: return
        if not self._show_thoughts: return
        self._ensure_thought_label()
        self._thought_buf += chunk

    _TOOLCALL_OPENS = ["<tool_call>", "<|tool_call_start|>"]
    _TOOLCALL_CLOSES = {"<tool_call>": "</tool_call>", "<|tool_call_start|>": "<|tool_call_end|>"}
    _TOOLCALL_MAX_TAG_LEN = max(len(s) for s in _TOOLCALL_OPENS + list(_TOOLCALL_CLOSES.values()))
    # Реальный JSON вызова инструмента (url/query/аргументы) укладывается в
    # несколько сотен символов. Если после открывающего тега накопилось
    # больше — это, скорее всего, не вызов, а модель поставила голый
    # открывающий тег перед обычным текстом ответа и забыла его закрыть.
    # Без этого лимита буфер молча копил бы ВЕСЬ оставшийся ответ до конца
    # раунда — пользователь видел пустой пузырь (как будто программа
    # зависла), а затем сырой тег и весь текст разом в finish_response().
    _TOOLCALL_GIVEUP_LEN = 500

    def _filter_tool_call_markers(self, chunk: str) -> str:
        """Вырезает из потока сырые <tool_call>...</tool_call> /
        <|tool_call_start|>...<|tool_call_end|> ДО того, как текст попадёт
        в append_chunk — модели, обученные на текстовом tool-calling
        (Nanbeige, LFM2), всегда оборачивают вызов в один из этих маркеров,
        и промежуточный сырой JSON/аргументы не несут пользователю никакой
        ценности (сам вызов уже отдельно показывается append_tool_call).
        Если тег так и не закрылся до конца раунда — см. finish_response,
        буфер возвращается видимым, чтобы ничего не потерялось молча."""
        chunk = self._toolcall_marker_buf + chunk
        self._toolcall_marker_buf = ""
        out = []
        while chunk:
            if self._toolcall_close is None:
                best_idx, best_open = None, None
                for open_tag in self._TOOLCALL_OPENS:
                    i = chunk.find(open_tag)
                    if i != -1 and (best_idx is None or i < best_idx):
                        best_idx, best_open = i, open_tag
                if best_open is None:
                    tail_start = chunk.rfind("<")
                    if tail_start != -1 and tail_start > len(chunk) - self._TOOLCALL_MAX_TAG_LEN:
                        if any(t.startswith(chunk[tail_start:]) for t in self._TOOLCALL_OPENS):
                            out.append(chunk[:tail_start])
                            self._toolcall_marker_buf = chunk[tail_start:]
                            chunk = ""
                            break
                    out.append(chunk)
                    break
                out.append(chunk[:best_idx])
                self._toolcall_buf = chunk[best_idx:best_idx + len(best_open)]
                self._toolcall_close = self._TOOLCALL_CLOSES[best_open]
                chunk = chunk[best_idx + len(best_open):]
            else:
                i = chunk.find(self._toolcall_close)
                if i != -1:
                    chunk = chunk[i + len(self._toolcall_close):]
                    self._toolcall_buf = ""
                    self._toolcall_close = None
                else:
                    tail_start = chunk.rfind("<")
                    if tail_start != -1 and tail_start > len(chunk) - len(self._toolcall_close):
                        if self._toolcall_close.startswith(chunk[tail_start:]):
                            self._toolcall_buf += chunk[:tail_start]
                            self._toolcall_marker_buf = chunk[tail_start:]
                            chunk = ""
                            break
                    self._toolcall_buf += chunk
                    if len(self._toolcall_buf) > self._TOOLCALL_GIVEUP_LEN:
                        leaked = re.sub(
                            r'^(?:<tool_call>|<\|tool_call_start\|>)', '', self._toolcall_buf
                        )
                        out.append(leaked)
                        self._toolcall_buf = ""
                        self._toolcall_close = None
                    break
        return "".join(out)

    def append_chunk(self, chunk: str):
        if not self._bot_active or not self._bot_reply: return

        chunk = self._filter_tool_call_markers(chunk)
        if not chunk:
            return

        chunk = chunk.replace('&lt;think&gt;', '<think>').replace('&lt;/think&gt;', '</think>')
        chunk = self._marker_buf + chunk
        self._marker_buf = ""

        while chunk:
            if not self._in_thought:
                idx = chunk.find("<think>")
                if idx != -1:
                    if idx > 0:
                        self._chunk_buf += chunk[:idx]
                    self._in_thought = True
                    if self._show_thoughts:
                        self._ensure_thought_label()
                    chunk = chunk[idx + len("<think>"):]
                    continue

                # Одинокий </think> без открывающего тега: у Nanbeige (и
                # похожих reasoning-моделей) ход иногда начинается "в
                # режиме размышления" неявно — сервер не всегда отдаёт
                # это отдельным полем reasoning_content, и тогда
                # единственный маркер — закрывающий тег в потоке content.
                # Раньше весь черновик-рассуждение до этого тега шёл
                # прямо в видимый ответ, а следом дописывался настоящий
                # финальный ответ — пользователь видел два ответа подряд.
                # Забираем уже показанный текст текущего раунда обратно
                # в мысли.
                close_idx = chunk.find("</think>")
                if close_idx != -1:
                    self._reclaim_round_as_thought(chunk[:close_idx])
                    chunk = chunk[close_idx + len("</think>"):]
                    continue

                tail_start = chunk.rfind("<")
                if tail_start != -1 and tail_start > len(chunk) - 8:
                    if "<think>".startswith(chunk[tail_start:]) or "</think>".startswith(chunk[tail_start:]):
                        self._chunk_buf += chunk[:tail_start]
                        self._marker_buf = chunk[tail_start:]
                        break
                self._chunk_buf += chunk
                break
            else:
                idx = chunk.find("</think>")
                if idx != -1:
                    self._thought_buf += chunk[:idx]
                    self._in_thought = False
                    chunk = chunk[idx + len("</think>"):]
                else:
                    tail_start = chunk.rfind("<")
                    if tail_start != -1 and tail_start > len(chunk) - 9:
                        if "</think>".startswith(chunk[tail_start:]):
                            self._thought_buf += chunk[:tail_start]
                            self._marker_buf = chunk[tail_start:]
                            break
                    self._thought_buf += chunk
                    break

    def _reclaim_round_as_thought(self, leaked_tail: str):
        """См. append_chunk. Баббл текущего раунда содержит ровно текст
        текущего раунда, поэтому забираем его целиком в мысли; видимой
        рамки вокруг опустевшего раунда не остаётся (ленивый TextBubble)."""
        self._flush_buffers()
        leaked = leaked_tail
        if self._bot_reply is not None and self._bot_reply.current_bubble is not None:
            leaked = self._bot_reply.reclaim_round_text() + leaked
        if leaked and self._show_thoughts:
            tw = self._ensure_thought_label()
            if tw is not None:
                tw.stream_label.append_text(self._thought_with_gap(leaked))
                tw.request_resize()

    def finish_response(self, elapsed: float, tokens: int, speed: float, ttft: float):
        if not self._bot_active or not self._bot_reply: return
        if self._toolcall_close is not None and self._toolcall_buf:
            # Тег так и не закрылся до конца генерации (например, обрыв по
            # max_tokens посреди JSON аргументов) — показываем как есть,
            # чтобы ничего не потерялось молча, но без самого сырого тега.
            self._chunk_buf += re.sub(
                r'^(?:<tool_call>|<\|tool_call_start\|>)', '', self._toolcall_buf
            )
        self._toolcall_buf = ""
        self._toolcall_close = None
        self._toolcall_marker_buf = ""
        self._flush_buffers()
        self._bot_active = False
        self._in_thought = False

        stats = f"{elapsed:.1f} с · TTFT {ttft:.2f} с · {tokens} tk · {speed:.1f} tok/s"
        self._bot_reply.finalize(stats, self._show_thoughts)
        self._scroll_smooth()

    def append_tool_call(self, tool_name: str, query: str):
        if not self._bot_reply: return
        self._flush_buffers()               # текст раунда дописать до запечатывания
        w = _CollapsibleToolWidget(header=tool_name, detail=query, role="call")
        self._bot_reply.append_tool_row(w)
        reply = self._bot_reply
        w.toggled.connect(lambda w=w: self._on_collapsible_toggled(reply, w))
        self._scroll_smooth()

    def append_tool_result(self, summary: str, detail: str = ""):
        if not self._bot_reply: return
        self._flush_buffers()
        w = _CollapsibleToolWidget(header=summary, detail=detail or summary, role="result")
        self._bot_reply.append_tool_row(w)
        reply = self._bot_reply
        w.toggled.connect(lambda w=w: self._on_collapsible_toggled(reply, w))
        self._scroll_smooth()

    def append_result_file(self, path: str, fmt: str):
        """Вставляет карточку файла-черновика (см. core/file_writer.py +
        core/write_tool_definitions.py::WRITE_TOOLS), который сгенерировала
        модель через write_text_file, в текущий ответ — строкой вне рамки,
        по образцу append_tool_result выше."""
        if not self._bot_reply: return
        from ui.result_file_card import ResultFileCard
        self._flush_buffers()
        self._bot_reply.append_file_card(ResultFileCard(path))
        self._scroll_smooth()

    def append_error(self, err: str):
        row_widget = ErrorRow(err)
        row_widget.recolor(_P())
        self._add_widget(row_widget, -1)
        self._scroll_smooth()

    def append_assistant_message(self, text: str, model_name: str = "", msg_index: int = -1):
        reply = BotReplyWidget(model_name, "", msg_index)
        self._connect_bubble(reply)
        reply.add_final_text(text)
        self._add_widget(reply, msg_index)
        self._reset_bot_state()
        self._scroll_smooth()

    def toPlainText(self) -> str:
        parts = []
        sep = "-" * 60
        for widget, _idx in self._bubbles:
            if isinstance(widget, BubbleWidget):
                parts.append(sep)
                parts.append("[Вы]")
                for j in range(widget._inner.count()):
                    wi = widget._inner.itemAt(j)
                    if not (wi and wi.widget()): continue
                    ww = wi.widget()
                    if isinstance(ww, QLabel) and getattr(ww, '_is_markdown', False):
                        raw = ww._plain_text.strip() if hasattr(ww, '_plain_text') else re.sub(r'<[^>]+>', '', ww.text()).strip()
                        if raw:
                            parts.append(raw)
            elif isinstance(widget, BotReplyWidget):
                parts.append(sep)
                parts.append("[Ассистент]")
                if widget._thought is not None:
                    thought_text = widget._thought.stream_label.toPlainText().strip()
                    if thought_text:
                        parts.append("  [Мысли]")
                        for line in thought_text.splitlines():
                            parts.append(f"    {line}")
                for b in widget._bubbles:
                    raw = b.label.toPlainText().strip()
                    if raw:
                        parts.append(raw)
                for tw in widget._tool_rows:
                    parts.append(f"  [{_tool_export_text(tw)}]")
                if widget._stats_lbl is not None:
                    raw = re.sub(r'<[^>]+>', '', widget._stats_lbl.text()).strip()
                    if raw:
                        parts.append(f"  [{raw}]")
        if parts:
            parts.append(sep)
        return "\n".join(parts)

    def clear_chat(self):
        self._flush_timer.stop()
        self._reset_bot_state()
        while self._lay.count() > 1:        # последний item — прижимающий stretch
            item = self._lay.takeAt(0)
            w = item.widget()
            if w is not None:
                # hide() обязателен ДО deleteLater: DeferredDelete обрабатывается
                # только полным циклом события loop, а до того момента виджет
                # остаётся ребёнком контента и ПРОДОЛЖАЕТ РИСОВАТЬСЯ по старой
                # геометрии («призраки» очищенного чата в offscreen-трассировке).
                w.hide()
                w.deleteLater()
        self._bubbles = []
        self._sync_layout()
        self.verticalScrollBar().setValue(0)
        self.viewport().update()            # показать сцену пустого состояния
        self._flush_timer.start()

    def remove_from_index(self, msg_index: int):
        self._flush_timer.stop()
        doomed = [w for (w, idx) in self._bubbles if idx >= msg_index]
        for w in doomed:
            self._lay.removeWidget(w)
            w.hide()            # см. комментарий в clear_chat про призраки
            w.deleteLater()
        self._bubbles = [(w, i) for (w, i) in self._bubbles if i < msg_index]
        self._reset_bot_state()
        self._sync_layout()
        self._flush_timer.start()

    def mark_round_start(self):
        """Вызывается перед каждым новым раундом генерации (после вызова
        инструментов). Схемой «раунд = свой баббл» границы раундов
        проводятся самими TextBubble'ами, здесь остаётся только гэп между
        раундами мыслей."""
        self._flush_buffers()
        self._thought_gap_pending = True

    def trim_stream_to_round(self, cleaned_text: str):
        """Заменяет текст ТЕКУЩЕГО раунда на очищенную от служебной строки
        вызова инструмента версию. Раунд живёт в отдельном баббле, поэтому
        замена — это setText одного лейбла (раньше приходилось вырезать
        хвост по _round_start_len из общего потока и перестраивать текст
        всего ответа). Пустой текст — раунд был черновиком, баббл убираем.
        Мысли предыдущих раундов не трогаем."""
        self._flush_buffers()
        if self._bot_reply is not None:
            self._bot_reply.replace_round_text(cleaned_text)
        self._chunk_buf = ""
        self._thought_buf = ""
        self._marker_buf = ""
        self._in_thought = False
        self._toolcall_buf = ""
        self._toolcall_close = None
        self._toolcall_marker_buf = ""
        self._sync_layout()

    def _reset_bot_state(self):
        self._bot_active = False
        self._in_thought = False
        self._marker_buf = ""
        self._chunk_buf = ""
        self._thought_buf = ""
        self._bot_reply = None
        self._thought_widget = None
        self._bot_msg_index = -1
        self._thought_gap_pending = False
        self._toolcall_buf = ""
        self._toolcall_close = None
        self._toolcall_marker_buf = ""

    def _flush_buffers(self):
        changed = False
        if self._chunk_buf and self._bot_active and self._bot_reply is not None:
            self._bot_reply.hide_thinking()
            self._bot_reply.stream_label().append_text(self._chunk_buf)
            self._chunk_buf = ""
            changed = True
        if self._thought_buf and self._bot_active and self._thought_widget is not None:
            self._bot_reply.hide_thinking()
            self._thought_widget.stream_label.append_text(
                self._thought_with_gap(self._thought_buf)
            )
            self._thought_buf = ""
            self._thought_widget.request_resize()
            changed = True
        if changed:
            # Синхронная сборка сразу после роста текста: между append и
            # следующим кадром не существует промежуточного состояния, которое
            # мог бы увидеть асинхронный LayoutRequest (в QListView-версии
            # именно эти промежутки давали «подрыгивание» на доли секунды).
            self._sync_layout()
            if self._autoscroll and not self._bottom_timer.isActive():
                self.verticalScrollBar().setValue(self.verticalScrollBar().maximum())
