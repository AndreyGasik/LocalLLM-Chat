# ui/main_window/loop_actions.py
#
# "Цикл до верного ответа": пока включён тумблер self.loop_toggle, обычная
# отправка сообщения не даёт один ответ, а гоняет модель по циклу
# решить -> строго проверить -> (если найдена ошибка) решить заново с учётом
# замечания -> проверить -> ... пока проверка не подтвердит ответ как
# ГОТОВО или не кончится лимит попыток (self.loop_max_iter). Пользователь
# не подсказывает и не вмешивается — только явно видит каждый раунд как
# обычное сообщение бота с бейджем прогресса, ровно как уже работает
# кнопка 🔍 "Перепроверить" (ActionsMixin._on_verify_answer), паттерн
# которой этот цикл переиспользует и просто зацикливает.
#
# В отличие от эталона, здесь нет self.tool_support_cache/ToolCheckThread —
# Llama не определяет "нативную" поддержку тулов у модели (это
# Ollama-специфичная асинхронная проверка), поэтому _loop_ensure_tools из
# эталона убран целиком: оба раунда (_loop_run_solve/_loop_run_verify)
# запускают _start_worker() напрямую, без промежуточного шага.
import re

from i18n import _t
from config import MAX_LOOP_ITER
from core.skills import load_skill

_VERDICT_RE = re.compile(r'ВЕРДИКТ\s*:\s*(ГОТОВО|ДОРАБОТАТЬ)', re.IGNORECASE)
_REASON_RE  = re.compile(r'Причина\s*:\s*(.+)', re.IGNORECASE | re.DOTALL)


class LoopMixin:
    def _loop_parse_verdict(self, text: str):
        """Возвращает (verdict, reason). verdict — 'ГОТОВО' / 'ДОРАБОТАТЬ' / None
        (формат не распознан — считаем это неудачной попыткой, не гадаем)."""
        matches = list(_VERDICT_RE.finditer(text or ""))
        if not matches:
            return None, ""
        verdict = matches[-1].group(1).upper()
        reason = ""
        if verdict == "ДОРАБОТАТЬ":
            after = text[matches[-1].end():]
            m = _REASON_RE.search(after) or _REASON_RE.search(text)
            reason = m.group(1).strip() if m else text.strip()[-400:]
        return verdict, reason

    def _start_loop(self, question: str):
        if self.worker and self.worker.isRunning():
            return
        if not (self.model_combo.currentText() or "").strip():
            return

        self._loop_active      = True
        self._loop_phase       = None
        self._loop_round       = 1
        self._loop_max         = self.loop_max_iter.value() if getattr(self, "loop_max_iter", None) else MAX_LOOP_ITER
        self._loop_question    = question
        self._loop_last_answer = ""
        self.loop_toggle.setEnabled(False)
        self._loop_run_solve()

    def _loop_run_solve(self):
        skill_text = load_skill("solve_loop")
        badge = _t("status_loop_solving", n=self._loop_round, m=self._loop_max)

        self._loop_phase = "solve"
        self._start_worker(
            badge_override=f"[{badge}]",
            extra_system=skill_text,
        )
        self.status_bar.setText(badge)

    def _loop_run_verify(self, answer_text: str):
        skill_text = load_skill("verify_loop")
        base_sys   = self.system_prompt.toPlainText().strip() or "Ты полезный ассистент."
        verify_sys = f"{base_sys}\n\n{skill_text}" if skill_text else base_sys

        verify_messages = [
            {"role": "system", "content": verify_sys},
            {"role": "user", "content": (
                f"Вопрос пользователя:\n{self._loop_question}\n\n"
                f"Ответ на проверку:\n{answer_text}\n\n"
                f"Перепроверь этот ответ согласно инструкции выше."
            )}
        ]
        badge = _t("status_loop_verifying", n=self._loop_round, m=self._loop_max)

        self._loop_phase = "verify"
        self._start_worker(
            override_messages=verify_messages,
            force_search=True,
            badge_override=f"[{badge}]",
        )
        self.status_bar.setText(badge)

    def _loop_after_finished(self, full_text: str):
        # Вызывается из _on_finished (chat_io.py) сразу после того, как
        # текущий раунд цикла завершился и уже записан в conversation_history.
        if not getattr(self, "_loop_active", False):
            return
        phase = getattr(self, "_loop_phase", None)

        if phase == "solve":
            self._loop_last_answer = full_text
            self._loop_run_verify(full_text)
            return

        if phase == "verify":
            verdict, reason = self._loop_parse_verdict(full_text)

            if verdict == "ГОТОВО":
                self._loop_finish(success=True)
                return

            if verdict == "ДОРАБОТАТЬ" and self._loop_round < self._loop_max:
                self._loop_round += 1
                followup = _t("loop_followup_prompt", reason=reason or full_text.strip()[-400:])
                idx = len(self.conversation_history)
                self.conversation_history.append({"role": "user", "content": followup, "files": []})
                self.chat_area.append_user(followup, idx, [])
                self._update_context_label()
                self._loop_run_solve()
                return

            # лимит попыток исчерпан, либо модель не выдала распознаваемый
            # вердикт вообще — в обоих случаях честно останавливаемся, а не
            # гадаем и не зацикливаемся бесконечно
            self._loop_finish(success=False, reason=reason)

    def _loop_finish(self, success: bool, reason: str = ""):
        n, m = self._loop_round, self._loop_max
        self._loop_active = False
        self._loop_phase   = None
        self.loop_toggle.setEnabled(True)

        if success:
            self._set_idle(_t("status_loop_done", n=n))
            return

        self._set_idle(_t("status_loop_gaveup", m=m))
        note = _t("loop_giveup_note", m=m, reason=reason or "—")
        idx = len(self.conversation_history)
        self.conversation_history.append({"role": "assistant", "content": note})
        self.chat_area.append_assistant_message(note, model_name=self.model_combo.currentText() or "", msg_index=idx)
        self._save_settings_and_history()
