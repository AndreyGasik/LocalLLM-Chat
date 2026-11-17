# core/llama_server.py
#
# Логика жизненного цикла процесса llama-server (_toggle_server,
# _check_server_health, _tail_server_log, _signal_server_group,
# _stop_server_proc[_blocking], _check_server_stopped, _finalize_server_stop),
# выделенная в отдельный класс без прямых обращений
# к виджетам MainWindow. Вместо чтения/записи self.srv_btn / self.status_bar
# напрямую — сигналы (starting/ready/stopping/stopped/error), на которые
# подписывается UI-слой (ui/main_window/*). Сама логика запуска/остановки/
# health-check/таймаутов не изменена.
import os
import signal
import socket
import subprocess
from pathlib import Path

from PyQt6.QtCore import QObject, QTimer, pyqtSignal

from http_client import _HTTP, _NO_PROXY
from i18n import get_lang
from config import DATA_DIR

SERVER_LOG_PATH = DATA_DIR / "llama_server.log"


def _find_pid_listening_on_port(port: int) -> int | None:
    """Ищет PID процесса, слушающего TCP-порт, через /proc/net/tcp[6] +
    /proc/<pid>/fd — без psutil/lsof/fuser, чистый Linux /proc. Нужен для
    восстановления после краша: llama-server запускается с
    start_new_session=True (своя группа процессов), поэтому если само
    приложение упало, сервер продолжает висеть и держать порт сам по себе,
    а новый процесс ChatWindow ничего не знает про его PID
    (self.proc = None в свежем экземпляре) — обычный stop()/_signal_group
    тут бессилен, убивать он может только то, что сам же и запустил."""
    target_hex = format(port, "04X")
    inode = None
    for proc_net in ("/proc/net/tcp", "/proc/net/tcp6"):
        try:
            with open(proc_net) as f:
                next(f, None)  # строка заголовка
                for line in f:
                    parts = line.split()
                    if len(parts) < 10:
                        continue
                    local_port = parts[1].split(":")[1]
                    state = parts[3]
                    if local_port.upper() == target_hex and state == "0A":  # 0A = LISTEN
                        inode = parts[9]
                        break
        except FileNotFoundError:
            continue
        if inode:
            break
    if not inode or inode == "0":
        return None

    target = f"socket:[{inode}]"
    try:
        pid_dirs = [p for p in Path("/proc").iterdir() if p.name.isdigit()]
    except Exception:
        return None
    for pid_dir in pid_dirs:
        try:
            for fd in (pid_dir / "fd").iterdir():
                try:
                    if os.readlink(fd) == target:
                        return int(pid_dir.name)
                except OSError:
                    continue
        except (FileNotFoundError, PermissionError):
            continue
    return None


class LlamaServerManager(QObject):
    """Управляет процессом llama-server: запуск, опрос /health, остановка
    (мягкая -> принудительная через ~5с), чтение хвоста лога."""

    starting = pyqtSignal()   # Popen выполнен, начали опрашивать /health
    ready    = pyqtSignal()   # /health ответил 200
    stopping = pyqtSignal()   # начали останавливать (SIGTERM отправлен)
    stopped  = pyqtSignal()   # процесс гарантированно остановлен
    error    = pyqtSignal(str)  # уже локализованный текст ошибки, готов для QMessageBox

    def __init__(self, parent=None):
        super().__init__(parent)
        self.proc = None
        self.ready_flag = False
        self._log_file = None
        self.port = None
        self.ctx = None

        self._health_check_iter = 0
        self._health_timer = QTimer(self)
        self._health_timer.setInterval(500)
        self._health_timer.timeout.connect(self._check_health)

        self._stop_check_iter = 0
        self._stop_timer = QTimer(self)
        self._stop_timer.setInterval(200)
        self._stop_timer.timeout.connect(self._check_stopped)

    def is_running(self) -> bool:
        return self.proc is not None

    def kill_orphan_on_port(self, port: int) -> bool:
        """Убивает процесс, который держит порт, но не является self.proc
        этого экземпляра — типичный случай после краша приложения (см.
        _find_pid_listening_on_port выше). SIGTERM, ~2с на грациозное
        завершение, затем SIGKILL. Возвращает True, если порт после этого
        свободен (либо ничего не нашли — тоже ОК, порт мог освободиться
        сам). Вызывается синхронно из UI-потока, но это редкий разовый
        сценарий восстановления, не обычный путь запуска."""
        pid = _find_pid_listening_on_port(port)
        if not pid:
            return True
        try:
            os.kill(pid, signal.SIGTERM)
        except ProcessLookupError:
            return True
        except PermissionError:
            return False

        import time
        for _ in range(20):  # 20 * 0.1с = 2с на грациозное завершение
            time.sleep(0.1)
            try:
                os.kill(pid, 0)
            except ProcessLookupError:
                return True
        try:
            os.kill(pid, signal.SIGKILL)
        except ProcessLookupError:
            pass
        except PermissionError:
            return False
        time.sleep(0.2)
        return _find_pid_listening_on_port(port) is None

    # ------------------------------------------------------------------ start
    def start(self, *, exe: str, model_dir: str, model_file: str, port: int,
              threads: int, ngl: int, np_: int, ctx: int,
              jinja: bool = False, mtp_enabled: bool = False,
              mtp_draft_n: int = 2, mtp_draft_model: str = ""):
        """Пытается запустить сервер. Возвращает None при успехе (после
        этого начинается опрос /health и рано или поздно придёт сигнал
        ready или error), либо готовый локализованный текст ошибки, если
        запуск не удалось даже начать (порт занят / файл не найден и т.п.) —
        в этом случае вызывающая сторона показывает его сама (решение
        о виде диалога — за UI-слоем)."""
        self.ready_flag = False

        with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
            if s.connect_ex(("127.0.0.1", port)) == 0:
                return (f"Порт {port} уже используется!" if get_lang() == "ru"
                        else f"Port {port} is already in use!")

        if not exe:
            # Дефолтного пути нет: папка сервера выбирается в UI
            # («Модель и Сервер» → «Выбрать папку сервера…»).
            return ("Сначала выберите папку сервера («Модель и Сервер»)."
                    if get_lang() == "ru" else
                    "Choose the server folder first (Model & Server).")
        if not Path(exe).exists():
            return (("Исполняемый файл не найден:\n" if get_lang() == "ru"
                      else "Executable not found:\n") + exe)

        if not model_file:
            return ("Выберите модель GGUF из списка" if get_lang() == "ru"
                    else "Select a GGUF model from the list")

        full_model_path = str(Path(model_dir) / model_file)
        cmd = [
            exe, "-m", full_model_path,
            "-c", str(ctx),
            "--port", str(port),
            "-t", str(threads),
            "-ngl", str(ngl),
            "-np", str(np_),
        ]
        if jinja:
            cmd.append("--jinja")
        if mtp_enabled:
            cmd += ["--spec-type", "draft-mtp"]
            cmd += ["--spec-draft-n-max", str(mtp_draft_n)]
            if mtp_draft_model:
                if not Path(mtp_draft_model).exists():
                    return (("Файл MTP draft-модели не найден:\n" if get_lang() == "ru"
                              else "MTP draft model file not found:\n") + mtp_draft_model)
                cmd += ["-md", mtp_draft_model]

        try:
            self._log_file = open(SERVER_LOG_PATH, "w")
            env = os.environ.copy()
            lib_dir = str(Path(exe).resolve().parent)
            env["LD_LIBRARY_PATH"] = lib_dir + os.pathsep + env.get("LD_LIBRARY_PATH", "")
            self.proc = subprocess.Popen(
                cmd, stdout=self._log_file, stderr=subprocess.STDOUT, env=env,
                start_new_session=True,  # своя группа процессов — чтобы гарантированно
                                          # убить и возможные дочерние процессы бэкенда
            )
        except Exception as e:
            self.proc = None
            return (("Не удалось запустить сервер:\n" if get_lang() == "ru"
                      else "Failed to start server:\n") + str(e))

        self.port = port
        self.ctx = ctx
        self._health_check_iter = 0
        self._health_timer.start()
        self.starting.emit()
        return None

    # ------------------------------------------------------------- health
    def _check_health(self):
        self._health_check_iter += 1

        if self.proc and self.proc.poll() is not None:
            self._health_timer.stop()
            code = self.proc.returncode
            self.proc = None
            self.ready_flag = False
            msg = (
                f"llama-server завершился (код {code}) до выхода на /health.\n\n"
                f"Последние строки лога:\n{self.tail_log()}"
                if get_lang() == "ru" else
                f"llama-server exited (code {code}) before /health was available.\n\n"
                f"Last log lines:\n{self.tail_log()}"
            )
            self.error.emit(msg)
            self.stopped.emit()
            return

        try:
            r = _HTTP.get(f"http://127.0.0.1:{self.port}/health", timeout=1, proxies=_NO_PROXY)
            if r.status_code == 200:
                self._health_timer.stop()
                self.ready_flag = True
                self.ready.emit()
                return
        except Exception:
            pass

        if self._health_check_iter >= 360:
            self._health_timer.stop()
            msg = (
                "llama-server не ответил на /health за 3 минуты.\n\n"
                f"Последние строки лога:\n{self.tail_log()}"
                if get_lang() == "ru" else
                "llama-server did not respond to /health within 3 minutes.\n\n"
                f"Last log lines:\n{self.tail_log()}"
            )
            self.stop()
            self.error.emit(msg)

    def tail_log(self, max_lines: int = 25) -> str:
        try:
            if self._log_file:
                self._log_file.flush()
            lines = SERVER_LOG_PATH.read_text(encoding="utf-8", errors="ignore").splitlines()
            return "\n".join(lines[-max_lines:]) if lines else ("(лог пуст)" if get_lang() == "ru" else "(log empty)")
        except Exception as e:
            return ("(не удалось прочитать лог: " if get_lang() == "ru" else "(failed to read log: ") + str(e) + ")"

    # -------------------------------------------------------------- stop
    def _signal_group(self, sig):
        """Посылает сигнал всей группе процессов сервера (см. start_new_session=True
        при запуске), а не только прямому дочернему процессу — если llama-server
        порождает дочерние процессы, terminate()/kill() самого proc их
        не тронул бы, и они могли бы остаться висеть."""
        proc = self.proc
        if not proc:
            return
        try:
            pgid = os.getpgid(proc.pid)
            os.killpg(pgid, sig)
        except (ProcessLookupError, PermissionError, OSError):
            try:
                if sig == signal.SIGKILL:
                    proc.kill()
                else:
                    proc.terminate()
            except Exception:
                pass

    def stop(self):
        """Асинхронная остановка сервера — не блокирует UI. Ждём через
        таймер, опрашивая процесс, точно так же, как ждём готовности при
        запуске."""
        if not self.proc:
            self._finalize_stop()
            return

        self.stopping.emit()
        self._signal_group(signal.SIGTERM)

        self._stop_check_iter = 0
        self._stop_timer.start()

    def _check_stopped(self):
        if not self.proc:
            self._stop_timer.stop()
            self._finalize_stop()
            return

        if self.proc.poll() is not None:
            self._stop_timer.stop()
            self._finalize_stop()
            return

        self._stop_check_iter += 1
        # ~5 секунд (25 * 200мс) на грациозное завершение (SIGTERM),
        # затем принудительно добиваем (SIGKILL) — тот же таймаут, что
        # был раньше, только не блокируя интерфейс всё это время.
        if self._stop_check_iter >= 25:
            self._signal_group(signal.SIGKILL)
            try:
                self.proc.wait(timeout=2)
            except Exception:
                pass
            self._stop_timer.stop()
            self._finalize_stop()

    def _finalize_stop(self):
        self.proc = None
        if self._log_file:
            try:
                self._log_file.close()
            except Exception:
                pass
            self._log_file = None
        self.ready_flag = False
        self.stopped.emit()

    def stop_blocking(self):
        """Синхронная версия — только для закрытия приложения (closeEvent).
        Там отзывчивость UI уже не важна, а гарантированно дождаться
        завершения процесса перед выходом — необходимо."""
        self._health_timer.stop()
        self._stop_timer.stop()
        if self.proc:
            self._signal_group(signal.SIGTERM)
            try:
                self.proc.wait(timeout=5)
            except Exception:
                self._signal_group(signal.SIGKILL)
                try:
                    self.proc.wait(timeout=2)
                except Exception:
                    pass
            self.proc = None
        if self._log_file:
            try:
                self._log_file.close()
            except Exception:
                pass
            self._log_file = None
