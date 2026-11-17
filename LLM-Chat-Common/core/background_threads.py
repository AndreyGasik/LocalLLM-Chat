# core/background_threads.py
import json
import subprocess
from PyQt6.QtCore import QThread, pyqtSignal
from http_client import _HTTP, _NO_PROXY
from config import OLLAMA_API, OLLAMA_TAGS, SEARXNG_URL, MAX_TITLE_LEN, DEFAULT_CHAT_TITLE


class ModelLoaderThread(QThread):
    models_loaded = pyqtSignal(list)
    error_occurred = pyqtSignal(str)

    def run(self):
        try:
            resp = _HTTP.get(OLLAMA_TAGS, timeout=5, proxies=_NO_PROXY)
            models = resp.json().get("models", [])
            self.models_loaded.emit(models)
        except Exception as e:
            self.error_occurred.emit(str(e))


class UnloadThread(QThread):
    """Выгрузка модели из памяти Ollama: запрос keep_alive=0 через API и проверка по /api/ps,
    что модель действительно ушла (раньше доверяли коду возврата `ollama stop`)."""
    done = pyqtSignal(bool, str)          # (выгружена, подробности ошибки)

    def __init__(self, model_name):
        super().__init__()
        self.model_name = model_name

    @staticmethod
    def _base():
        base = OLLAMA_API.rstrip("/")
        return base[:-len("/api/chat")] if base.endswith("/api/chat") else base

    def _is_loaded(self):
        resp = _HTTP.get(self._base() + "/api/ps", timeout=5, proxies=_NO_PROXY)
        resp.raise_for_status()
        for m in resp.json().get("models", []):
            if self.model_name in (m.get("name"), m.get("model")):
                return True
        return False

    def run(self):
        try:                               # официальный способ выгрузки: пустой чат с keep_alive = 0
            resp = _HTTP.post(
                OLLAMA_API,
                json={"model": self.model_name, "messages": [], "keep_alive": 0, "stream": False},
                timeout=60, proxies=_NO_PROXY,
            )
            resp.raise_for_status()
        except Exception as api_err:       # запасной путь — консольная команда
            try:
                r = subprocess.run(["ollama", "stop", self.model_name],
                                   capture_output=True, text=True, timeout=30)
            except Exception as cli_err:
                self.done.emit(False, f"{api_err}; {cli_err}")
                return
            if r.returncode != 0:
                self.done.emit(False, r.stderr.strip() or str(api_err))
                return
        # Ollama освобождает память не мгновенно — ждём, пока модель исчезнет из /api/ps
        for _ in range(25):
            try:
                if not self._is_loaded():
                    self.done.emit(True, "")
                    return
            except Exception:
                self.done.emit(True, "")   # запрос на выгрузку принят, а проверить статус не удалось
                return
            self.msleep(300)
        self.done.emit(False, "")          # всё ещё в памяти (обычно идёт генерация)


class SearxngCheckThread(QThread):
    result = pyqtSignal(bool)

    def run(self):
        delays = [0, 1.5, 3.0]
        for i, delay in enumerate(delays):
            if delay:
                self.msleep(int(delay * 1000))
            try:
                r = _HTTP.post(
                    SEARXNG_URL,
                    data={"q": "test", "format": "json"},
                    headers={"User-Agent": "Mozilla/5.0 (X11; Linux x86_64) LLM-Chat/1.0"},
                    timeout=8,
                    allow_redirects=True,
                    proxies=_NO_PROXY
                )
                if r.status_code == 200:
                    r.json()
                    self.result.emit(True)
                    return
            except Exception:
                pass
        self.result.emit(False)

class TitleGenThread(QThread):
    result = pyqtSignal(str)

    def __init__(self, model_name, user_text):
        super().__init__()
        self.model_name = model_name
        self.user_text = user_text

    def run(self):
        prompt = (
            f"In {MAX_TITLE_LEN} characters or fewer, write a short title that "
            f"summarises this message. Reply with ONLY the title text — no quotes, "
            f"no punctuation at the end, no extra words.\n\nMessage: {self.user_text[:400]}"
        )
        try:
            resp = _HTTP.post(
                OLLAMA_API,
                json={
                    "model": self.model_name,
                    "messages": [{"role": "user", "content": prompt}],
                    "stream": False,
                },
                timeout=30,
                proxies=_NO_PROXY,
            )
            resp.raise_for_status()
            raw = resp.json().get("message", {}).get("content", "").strip()
            raw = raw.strip().strip('"\'').strip()
            raw = raw.split("\n")[0].strip()
            if len(raw) > MAX_TITLE_LEN:
                raw = raw[:MAX_TITLE_LEN].rstrip()
            self.result.emit(raw or DEFAULT_CHAT_TITLE)
        except Exception:
            self.result.emit(DEFAULT_CHAT_TITLE)
