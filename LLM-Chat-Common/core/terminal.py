# LLM-Chat-Common/core/terminal.py
#
# Инструмент терминала: deny-лист на регулярках, безопасное исполнение с
# мгновенной остановкой (Stop) и убийством всей группы процессов.
# Единый источник логики для обоих бэкендов.
# Это НЕ песочница: команды выполняются от имени пользователя.
import os
import re
import signal
import subprocess
import time


# Плановый вариант с субстрочным blacklist ("rm -rf /", "mkfs", ...) легко
# обходится ("rm -fr /", "rm -r -f /", "rm --recursive /"...), поэтому здесь
# набор РЕГУЛЯРОК, каждая из которых закрывает класс опасных команд. Это НЕ
# песочница: механизм работает от имени пользователя. Список открытый —
# при обнаружении нового опасного шаблона просто добавьте пару (regex, причина).
_TERMINAL_TARGET = (                     # корень / дом.папка / системные каталоги
    r"[\"']?(?:/(?:\s|$|\*)"             # / , /*
    r"|/\.(?:\s|$|\*)"                  # /. , /.* (скрытые в корне)
    r"|~(?:\s|$|\*|/\s|/$|/\*)"          # ~ , ~/ , ~/* (подпапки вида ~/x — разрешены)
    r"|~/(?:\*|\.(?:\s|$|\*))"           # ~/.* — скрытые в доме
    r"|\$HOME(?:\s|$|/\*?$)|\$\{HOME\}"   # $HOME
    r"|/home(?:\s|$|/\*?$|/[^/\s]+(?:\s|$|/\*?$))"  # /home и /home/<user> целиком
    r"|/(?:bin|boot|dev|etc|lib|lib64|opt|proc|root|run|sbin|srv|sys|usr|var)(?:/|\s|$)"
    r"|\.\.(?:\s|$|/\s|/$|/\*))"          # .. , ../ , ../* (родитель неизвестного cwd)
)
# Маски/относительные цели массового удаления: * , . , ./* , ~/.* и т.п.
# (регрессия-урок: "rm -rf ./*" однажды реально выполнился в тестах — теперь
# покрыто и закреплено тестом, а все тесты запускаются в tmp-каталоге).
_TERMINAL_GLOB_TARGET = r"[\"']?(?:\*|\.(?:\s|$|/\*|\*)|\.\.(?:\s|$|/\s|/$|/\*))"

_TERMINAL_DENY_RE = [
    # повышение привилегий: без TTY sudo обычно падает, но при NOPASSWD-настройке
    # модель получила бы root — блокируем полностью (см. описание TERMINAL_TOOL)
    (re.compile(r"\b(?:sudo|sudoedit|doas|pkexec)\b", re.I),
     "повышение привилегий (sudo/doas/pkexec)"),
    (re.compile(r"(?:^|[;&|]\s*|\$\(\s*)su\s", re.I),
     "повышение привилегий (su)"),
    # рекурсивное/силовое удаление по опасным целям (любой порядок флагов:
    # rm -rf /, rm -fr ~, rm -r /home/user, rm --recursive /*)
    (re.compile(r"\brm\b[^;|&\n]*\s-{1,2}[\w-]*[rfR][\w-]*\s+[\"']?" + _TERMINAL_TARGET, re.I),
     "рекурсивное удаление системных путей"),
    (re.compile(r"\brm\b[^;|&\n]*--(?:recursive|force)\b[^;|&\n]*\s[\"']?" + _TERMINAL_TARGET, re.I),
     "рекурсивное удаление системных путей"),
    # rm без рекурсии по системным каталогам — тоже под запретом
    (re.compile(r"\brm\b[^;|&\n]*\s[\"']?/(?:bin|boot|dev|etc|lib|lib64|proc|root|run|sbin|srv|sys|usr|var)(?:/|\s|$)", re.I),
     "удаление в системных каталогах"),
    # rm -r/-f с сегментами /./ или /.. внутри пути — обфускация: нормализация
    # может 'разрешить' опасный путь в безобидный (/home/./../user → /user),
    # поэтому такие команды блокируем по сырому тексту
    (re.compile(r"\brm\b[^;|&\n]*\s-{1,2}[\w-]*[rfR][\w-]*[^;|&\n]*/\.{1,2}(?:/|\s|$)", re.I),
     "рекурсивное удаление с ./.. в путях"),
    # rm -rf по маскам/относительным целям (rm -rf *, rm -rf ., rm -rf ./*, rm -rf ..)
    (re.compile(r"\brm\b[^;|&\n]*\s-{1,2}[\w-]*[rfR][\w-]*\s+" + _TERMINAL_GLOB_TARGET, re.I),
     "массовое удаление по маске"),
    (re.compile(r"\bfind\s+(?:/|~|\$HOME)\s[^;|&\n]*(?:-delete\b|-exec\s+rm\b|-execdir\s+rm\b)", re.I),
     "find -delete/-exec rm по корню или домашней папке"),
    (re.compile(r"\bch(?:mod|own)\b[^;|&\n]*\s-{1,2}[\w]*R[\w]*\b[^;|&\n]*\s[\"']?" + _TERMINAL_TARGET, re.I),
     "рекурсивная смена прав/владельца на системных путях"),
    (re.compile(r"\bmkfs(?:\.\w+)?\b", re.I),
     "форматирование файловой системы"),
    (re.compile(r"\bdd\b[^;|&\n]*\bof\s*=\s*[\"']?/dev/", re.I),
     "dd с записью на устройство"),
    (re.compile(r"\b(?:shred|blkdiscard|wipefs)\b[^;|&\n]*/dev/", re.I),
     "затирание устройства"),
    (re.compile(r">\s*/dev/(?:sd|nvme|vd|hd|mmcblk)", re.I),
     "перезапись дискового устройства"),
    (re.compile(r"\b(?:shutdown|reboot|poweroff|halt)\b", re.I),
     "выключение/перезагрузка системы"),
    (re.compile(r":\s*\(\s*\)\s*\{\s*:\s*\|\s*:\s*&", re.I),
     "форк-бомба"),
    (re.compile(r"\b(?:curl|wget)\b[^;|&\n]*\|\s*(?:sudo\s+)?(?:ba|z|da|fi|k)?sh\b", re.I),
     "исполнение скачанного из сети"),
    (re.compile(r">\s*/etc/", re.I),
     "запись в /etc через перенаправление"),
    (re.compile(r"\btee\s+(?:-a\s+)?/etc/", re.I),
     "запись в /etc через tee"),
]

_TERMINAL_TIMEOUT_MIN, _TERMINAL_TIMEOUT_MAX = 5, 300
_TERMINAL_OUTPUT_CAP = 6000             # суммарный потолок отчёта в символах


def _normalize_cmd_paths(cmd: str) -> str:
    """Текстово сворачивает /./ и /x/../ в путях — иначе 'rm -rf /home/./user'
    или 'rm -rf /home/user/..' обходят deny-лист. Используется ТОЛЬКО для
    проверки по deny-листу; сама команда выполняется как пришла."""
    prev = None
    while prev != cmd:
        prev = cmd
        # '/./' → '/' и хвост '/.' → '/': заменяем ВСЮ тройку, иначе
        # остаётся двойной слеш ('/home//user'), который не матчится deny-листом
        cmd = re.sub(r"/\./", "/", cmd)
        cmd = re.sub(r"/\.$", "/", cmd)
        cmd = re.sub(r"/[^/.][^/\s]*/\.\.(?=/|$)", "/", cmd)
    return cmd


def _kill_proc_group(proc: "subprocess.Popen"):
    """Убить процесс и ВСЕХ его детей: start_new_session=True делает pid лидером
    новой сессии/группы, поэтому killpg накрывает и bash, и запущенные им
    пайпы/фоновые процессы (без этого 'sleep 300 | ...' жил бы после kill)."""
    try:
        os.killpg(os.getpgid(proc.pid), signal.SIGKILL)
    except Exception:
        try:
            proc.kill()
        except Exception:
            pass


def _execute_command_safe(command: str, timeout: int = 30,
                          is_running=None) -> str:
    """Запуск команды модели в bash с многослойной защитой.

    Отличия от наивного subprocess.run из плана:
      1) deny-лист на регулярках вместо субстрочного blacklist, плюс
         нормализация путей (/./ и /x/../) перед проверкой;
      2) ожидание завершения — циклом с опросом каждые ~0.2 с, поэтому кнопка
         Stop работает МГНОВЕННО даже под запущенной командой (плановый вариант
         с subprocess.run(timeout=...) висел бы до таймаута, и UI был бы
         вынужден прибивать QThread через terminate());
      3) при Stop/таймауте убивается вся группа процессов, а не только bash;
      4) timeout зажимается в [5, 300] — модель не сможет передать 999999;
      5) вывод обрезается до _TERMINAL_OUTPUT_CAP суммарно.

    Возвращает строку-отчёт для модели: код возврата + STDOUT + STDERR.
    Отчёт при успехе начинается с 'Код возврата: 0' — на этом строится
    заголовок карточки инструмента в UI.
    """
    command = (command or "").strip()
    # модель иногда оборачивает команду в markdown-обратные кавычки
    if len(command) > 1 and command[0] == "`" and command[-1] == "`":
        command = command.strip("`").strip()
    if not command:
        return "ОШИБКА: пустая команда."
    try:
        timeout = int(float(timeout))
    except (TypeError, ValueError):
        timeout = 30
    timeout = max(_TERMINAL_TIMEOUT_MIN, min(timeout, _TERMINAL_TIMEOUT_MAX))

    check_cmd = _normalize_cmd_paths(command)
    for rx, label in _TERMINAL_DENY_RE:
        if rx.search(command) or rx.search(check_cmd):
            return (
                "ОШИБКА БЕЗОПАСНОСТИ: команда заблокирована (" + label + "). "
                "Деструктивные и системно-опасные команды не выполняются. "
                "Сообщи пользователю, что он может выполнить её сам, если уверен."
            )

    try:
        proc = subprocess.Popen(
            command, shell=True, executable="/bin/bash",
            stdout=subprocess.PIPE, stderr=subprocess.PIPE,
            text=True, errors="replace", start_new_session=True,
        )
    except Exception as e:
        return f"ОШИБКА: не удалось запустить процесс: {e}"

    # communicate(timeout=...) при повторном вызове НЕ теряет уже прочитанный
    # вывод (документированное поведение) — поэтому опрашиваем короткими
    # интервалами, попутно проверяя флаг Stop.
    deadline = time.time() + timeout
    stopped_note = ""
    out, err = "", ""
    while True:
        try:
            out, err = proc.communicate(timeout=0.2)
            break
        except subprocess.TimeoutExpired:
            if is_running is not None and not is_running():
                stopped_note = "ОШИБКА: остановлено пользователем (Stop), процесс убит."
                break
            if time.time() >= deadline:
                stopped_note = f"ОШИБКА: таймаут {timeout} с — процесс убит."
                break

    if stopped_note:
        _kill_proc_group(proc)
        try:
            out, err = proc.communicate(timeout=3)
        except Exception:
            out, err = out or "", err or ""

    parts = []
    if stopped_note:
        parts.append(stopped_note)
    parts.append(f"Код возврата: {proc.returncode}")
    if out and out.strip():
        parts.append("STDOUT:\n" + out.strip())
    if err and err.strip():
        parts.append("STDERR:\n" + err.strip())
    text = "\n".join(parts)
    if len(text) > _TERMINAL_OUTPUT_CAP:
        text = (text[:_TERMINAL_OUTPUT_CAP]
                + f"\n[... вывод обрезан: показано {_TERMINAL_OUTPUT_CAP} из {len(text)} знаков ...]")
    return text
