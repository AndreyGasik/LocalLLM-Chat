# LLM-Chat-Common/tool_parsing.py
#
# ЕДИНЫЙ разбор текстовых вызовов инструментов и фильтр live-стрима.
# Приложение подключает этот файл через тонкую обёртку
# core/tool_parsing.py — править парсеры нужно ТОЛЬКО здесь.
# Тесты: pytest LLM-Chat-Common/tests
# core/tool_parsing.py
import re
import json

_KNOWN_TOOL_NAMES = {
    "search", "scrape_url", "extract_links",
    "extract_metadata", "search_page", "scrape_multiple",
    "read_file", "read_pdf",
    "memory_write", "memory_read", "memory_delete",
    "write_text_file",
    "execute_terminal_command"
}

_EXAMPLE_CUE_RE = re.compile(
    r'(наприм\w*|пример\w*|образец\w*|шаблон\w*|for\s+example|e\.g\.|for\s+instance|such\s+as)\s*[:,\-]?\s*$',
    re.IGNORECASE
)

# Плейсхолдер синтаксиса — это <запрос>, <url>, <абсолютный_путь>. Закрывающие
# теги (</arg_value>, </tool_call>) и <arg_key>/<arg_value> — НЕ плейсхолдеры:
# модели вроде Spark-X2.6 дописывают их хвостом к обычной строке "SEARCH: ...",
# и из-за этого строка раньше считалась документацией и не вырезалась.
_PLACEHOLDER_RE = re.compile(r'<(?!/)(?!arg_(?:key|value)>)[^<>\n]{1,40}>')
_STRAY_ARG_TAG_RE = re.compile(r'</?(?:arg_key|arg_value|tool_call)>', re.IGNORECASE)

# Маленькие модели (LFM3, Gemma и т.п.) иногда пишут маркер вызова
# кириллическими буквами-двойниками («СЕARCH: …» вместо «SEARCH: …») и/или
# оборачивают его в скобки («[SEARCH: …]» — по аналогии с форматом результата
# «[Результат …]»). Парсер обязан это прощать: маркер есть маркер.
# Нормализация посимвольная (длины строк совпадают), поэтому аргументы
# вырезаются из ИСХОДНОЙ строки по тем же координатам — текст запроса
# не искажается.
_TOOL_LOOKALIKE = str.maketrans({
    "А": "A", "В": "B", "Е": "E", "К": "K", "М": "M", "Н": "H",
    "О": "O", "Р": "P", "С": "C", "Т": "T", "У": "Y", "Х": "X",
    "а": "a", "в": "b", "е": "e", "к": "k", "м": "m", "н": "h",
    "о": "o", "р": "p", "с": "c", "т": "t", "у": "y", "х": "x",
})


def _tool_line_variants(line: str):
    """[(ядро-исходное, ядро-нормализованное)] для сопоставления маркеров
    вызова. Ядро — строка без внешних «[…]»; нормализация — только перевод
    букв-двойников, длина исходного и нормализованного ядра совпадает."""
    s = line.strip()
    if s.startswith("[") and s.endswith("]"):
        s = s[1:-1]
    yield s, s.translate(_TOOL_LOOKALIKE)


# Строки «[Результат …]» в ТЕКСТЕ ответа модели всегда фальшивые: настоящие
# результаты инструментального цикла приходят ОТДЕЛЬНЫМИ user-сообщениями
# (см. _append_tool_result в core/worker.py). Модель, которая сама пишет
# «[Результат execute_terminal_command]: 2026-01-17 …», имитирует выполнение,
# которого не было — типичная ошибка крошечных моделей (диагностика
# ноябрь 2026: LFM3-1.7B, вопросы «какое время в системе» и «где родился
# Ленин»; воспроизведено A/B-тестом llama-server).
_FAKE_RESULT_LINE_RE = re.compile(
    r'^[ \t]*\[Результат[^\]\n]{0,100}\][^\n]*$', re.MULTILINE)

_FAKE_RESULT_NUDGE = (
    "[Служебное] В твоём предыдущем ответе была строка «[Результат …]», но ты "
    "написал её сам, не вызывая инструмент — этот результат выдуман и он НЕ "
    "настоящий. Результат всегда пишет система. Чтобы выполнить инструмент, "
    "выведи ВНЕ блока размышлений одну строку вызова, например:\n"
    "EXEC_CMD: date\n"
    "SEARCH: В.И.Ленин место рождения"
)



def _looks_like_placeholder(arg: str) -> bool:
    """True, если это описание синтаксиса (плейсхолдер <...>), а не реальный вызов."""
    if _PLACEHOLDER_RE.search(arg):
        return True
    if re.search(r'\s[-–—]\s', arg):
        return True
    return False


def _doc_value(val, full_only: bool = False) -> bool:
    """Значение аргумента — плейсхолдер документации, а не данные:
    «...»/«…» (цитата формата) или <плейсхолдер>. full_only=True — только
    «целиком плейсхолдер» (для свободного текста content, где короткий
    реальный HTML/markdown с тегами — легитимные данные)."""
    if not isinstance(val, str):
        return False
    v = _STRAY_ARG_TAG_RE.sub('', val).strip()
    if not v:
        return True
    if set(v) <= {".", "…", " ", "\t"}:
        return True
    if re.fullmatch(r'(?:<[^<>\n]{1,40}>\s*)+', v):
        return True
    if not full_only and len(v) <= 60 and "\n" not in v and _PLACEHOLDER_RE.search(v):
        return True
    return False


# Ключи аргументов, в которых реальные данные НЕ содержат <> — короткая
# цитата формата распознаётся уверенно. Свободный текст документа проверяется
# только «целиком» (full_only); command терминала не проверяется ВООБЩЕ:
# перенаправления «< file > file2» в настоящих командах похожи на плейсхолдер;
# память не проверяется: пустые значения у memory_read легитимны.
_DOC_PLAIN_KEYS = {"query", "url", "urls", "path"}
_DOC_FULL_KEYS = {"suggested_name", "content"}


def _call_args_documentation(tool_name: str, args) -> bool:
    """True — «вызов» с плейсхолдерными аргументами: это ЦИТАТА ФОРМАТА из
    инструкции инструментов, а не настоящий вызов. Применяется ко всем
    JSON/argkv/XML-парсерам (единый дискриминатор: парсер и чистка зеркальны).

    Диагностика 2026-11-17 (errors.txt, Qwen3.5-9B, вопрос «что ты умеешь?»):
    модель ответила списком возможностей, процитировав JSON-пример из
    системной инструкции с content="..."; правило «имя известно → принимать»
    выполняло её как настоящий write_text_file: файл с содержимым «...»,
    черновик-ответ выбрасывался (clear_stream), ответ писался заново."""
    if not isinstance(args, dict) or not args:
        return False
    for k in _DOC_PLAIN_KEYS & args.keys():
        if _doc_value(args[k]):
            return True
    for k in _DOC_FULL_KEYS & args.keys():
        if _doc_value(args[k], full_only=True):
            return True
    return False


# ── Словарь текстовых маркеров → (canonical-имя, разбор хвоста) ──────────
# Названия маркеров — то, что реально пишут модели; canonical — имена
# инструментов в _KNOWN_TOOL_NAMES.
_SIMPLE_MARKER_TOOLS = {
    "SEARCH":       "search",
    "SCRAPE":       "scrape_url",
    "LINKS":        "extract_links",
    "META":         "extract_metadata",
    "SEARCHPAGE":   "search_page",
    "SCRAPEMULTI":  "scrape_multiple",
    "READ_FILE":    "read_file",
    "READ_PDF":     "read_pdf",
    "EXEC_CMD":     "execute_terminal_command",
    "MEMORY_WRITE": "memory_write",
    "MEMORY_READ":  "memory_read",
    "MEMORY_DELETE": "memory_delete",
}


def _levenshtein(a: str, b: str) -> int:
    if len(a) < len(b):
        a, b = b, a
    prev = list(range(len(b) + 1))
    for i, ca in enumerate(a, 1):
        cur = [i]
        for j, cb in enumerate(b, 1):
            cur.append(min(prev[j] + 1, cur[j - 1] + 1,
                           prev[j - 1] + (ca != cb)))
        prev = cur
    return prev[-1]


def _fuzzy_marker(word: str) -> str | None:
    """Маркер вызова с допуском опечаток: «СЕARCH»/«CEARCH»/«SARCH» → SEARCH.
    Порог: расстояние Левенштейна ≤1 для коротких слов, ≤2 для длинных
    (≥8 символов) — чтобы «Дата», «Note» и прочая проза не превращались
    в инструменты."""
    w = word.translate(_TOOL_LOOKALIKE).upper()
    if not w or not w.isascii():
        return None
    if w in _SIMPLE_MARKER_TOOLS:
        return w
    best, bd = None, 10
    for k in _SIMPLE_MARKER_TOOLS:
        d = _levenshtein(w, k)
        if d < bd:
            best, bd = k, d
    if best is None:
        return None
    limit = 2 if len(w) >= 8 else 1
    return best if bd <= limit else None


_SIMPLE_LINE_RE = re.compile(
    r'^(?:\s*)([A-Za-z_]{3,16})(\s*:\s*)?(.*)$')
# Вариант «метка перед маркером»: «Инструмент: SCRAPE: url». Пробуется
# ВТОРЫМ: жадная метка иначе съедает сам маркер («CEARCH: курс» → метка
# «CEARCH:», слово «kyrs» — и вызов потерян).
_SIMPLE_LINE_LABELED_RE = re.compile(
    r'^(?:\s*)(?:[^\n:]{0,20}:\s*)([A-Za-z_]{3,16})(\s*:\s*)?(.*)$')


def _parse_simple_line(line: str) -> list[dict] | None:
    """Разбор ОДНОЙ строки как маркера вызова (с нормализацией двойников,
    внешними «[…]» и допуском опечаток). None — не вызов."""
    for core_orig, core_norm in _tool_line_variants(line):
        if not core_norm:
            continue
        matches = (_SIMPLE_LINE_RE.match(core_norm),
                   _SIMPLE_LINE_LABELED_RE.match(core_norm))
        for m in matches:
            if not m:
                continue
            canonical = _fuzzy_marker(m.group(1))
            if not canonical:
                continue
            # Двоеточие после маркера обязательно для всех, кроме MEMORY_READ
            # (его можно писать и без аргументов: «MEMORY_READ»). Иначе
            # «SEARCH — только для …» из документации превратилось бы в вызов.
            if m.group(2) is None and canonical != "MEMORY_READ":
                continue
            # Хвост — из ИСХОДНОГО ядра по тем же координатам (запрос не искажается)
            b, e = m.span(3)
            rest = core_orig[b:e].strip()
            tool_name = _SIMPLE_MARKER_TOOLS[canonical]

            args = {}
            skip = False
            if canonical == "SEARCHPAGE":
                parts = [p.strip() for p in rest.split("|", 1)] if rest else []
                if len(parts) != 2 or not parts[0] or not parts[1]:
                    continue
                candidates = {"url": parts[0], "query": parts[1]}
            elif canonical == "MEMORY_WRITE":
                parts = [p.strip() for p in rest.split("|")] if rest else []
                if len(parts) < 3 or not parts[0].isalnum() or not parts[1] or not parts[2]:
                    continue
                candidates = {"category": parts[0], "key": parts[1], "value": parts[2]}
            elif canonical == "MEMORY_DELETE":
                parts = [p.strip() for p in rest.split("|")] if rest else []
                if len(parts) != 2 or not parts[0] or not parts[1]:
                    continue
                candidates = {"category": parts[0], "key": parts[1]}
            elif canonical == "MEMORY_READ":
                candidates = {}
                if rest:
                    parts = [p.strip() for p in rest.split("|")]
                    if parts[0]:
                        candidates["category"] = parts[0]
                    if len(parts) > 1 and parts[1]:
                        candidates["key"] = parts[1]
            elif canonical == "SCRAPEMULTI":
                if not rest:
                    continue
                candidates = {"urls": rest}
            else:
                if not rest:
                    continue
                candidates = {
                    "search": {"query": rest},
                    "scrape_url": {"url": rest},
                    "extract_links": {"url": rest},
                    "extract_metadata": {"url": rest},
                    "read_file": {"path": rest},
                    "read_pdf": {"path": rest},
                    "execute_terminal_command": {"command": rest},
                }[tool_name]

            for key, val in candidates.items():
                val = _STRAY_ARG_TAG_RE.sub('', val).strip()
                if not val:
                    continue
                if _looks_like_placeholder(val):
                    skip = True
                    break
                if key == 'urls':
                    val = [u.strip() for u in val.split(',') if u.strip()]
                args[key] = val
            if skip:
                continue
            # Пустые аргументы осмысленны только у memory_read («прочитать всё»)
            if not args and canonical != "MEMORY_READ":
                continue
            # Модель иногда пишет "SCRAPE: url1, url2" — один аргумент 'url' с
            # несколькими адресами через запятую. requests.get() воспринимает
            # такую строку как один битый URL (с запятой внутри) -> 404.
            # Если после SCRAPE: обнаружено больше одного URL, переключаемся
            # на scrape_multiple с нормальным списком 'urls'.
            if tool_name == 'scrape_url' and ',' in args.get('url', ''):
                parts = [u.strip() for u in args['url'].split(',') if u.strip()]
                if len(parts) > 1:
                    return [{"function": {"name": "scrape_multiple", "arguments": {"urls": parts}}}]
            return [{"function": {"name": tool_name, "arguments": args}}]
    return None


def _detect_tool_echo(text: str) -> bool:
    """True, если в тексте есть распознаваемое эхо вызова инструмента: любыми
    парсерами, сырыми маркерами (<tool_call>, <|tool_call_start|>) или
    ограждённым JSON-вызовом известного инструмента. Используется
    safeguard'ом черновиков lfm2/nanbeige: удаление РАСПОЗНАВАЕМОГО эха —
    штатная работа strip, а «потеря ответа»."""
    if _parse_simple_text_tools(text) \
            or _parse_xml_tag_tool_calls(text) \
            or _parse_argkv_tool_calls(text) \
            or [tc for tc in _parse_text_tool_calls(text)
                if tc.get("function", {}).get("name") in _KNOWN_TOOL_NAMES]:
        return True
    # Сырые маркеры: парсеры их не разбирают (их вычищает _strip_text_tool_call),
    # но это очевидное эхо вызова — safeguard не должен откатывать их в текст.
    if re.search(r'<\|?\s*tool_call[^>]*>', text, re.IGNORECASE):
        return True
    return False


def _parse_simple_text_tools(text: str) -> list[dict] | None:
    """Разбор текстовых вызовов в «экономном» режиме: SEARCH:/SCRAPE:/EXEC_CMD:/…
    Построчно, с допуском опечаток-двойников («СЕARCH»), внешних «[…]» и
    потерянных букв («CEARCH» → SEARCH, расстояние Левенштейна ≤1/≤2 —
    см. _fuzzy_marker)."""
    for line in text.splitlines():
        result = _parse_simple_line(line)
        if result:
            return result
    return None


# Иногда модель (насмотревшись на XML/HTML-подобные tool-call протоколы
# где-то в обучении) вместо ожидаемого построчного синтаксиса "SCRAPE: url"
# сама придумывает XML-тег: <SCRAPE, url="...">...</SCRAPE> или
# самозакрывающийся <SCRAPE url="..."/>. Раньше это не ловилось ни одним
# парсером — тег молча оставался текстом ответа, реального вызова
# инструмента не происходило (тот же баг, что был найден и исправлен в
# LLM-Chat/core/tool_parsing.py на экспорте чата с "AMD Eng Sample", где
# модель вывела 4 таких тега подряд и ни один не выполнился).
_XML_TAG_TOOL_MAP = {
    "SEARCH":        ("search",           ["query"]),
    "SCRAPE":        ("scrape_url",       ["url"]),
    "LINKS":         ("extract_links",    ["url"]),
    "META":          ("extract_metadata", ["url"]),
    "SEARCHPAGE":    ("search_page",      ["url", "query"]),
    "SCRAPEMULTI":   ("scrape_multiple",  ["urls"]),
    "READ_FILE":     ("read_file",        ["path"]),
    "READ_PDF":      ("read_pdf",         ["path"]),
    "EXEC_CMD":      ("execute_terminal_command", ["command"]),
    "MEMORY_WRITE":  ("memory_write",     ["category", "key", "value"]),
    "MEMORY_READ":   ("memory_read",      ["category", "key"]),
    "MEMORY_DELETE": ("memory_delete",    ["category", "key"]),
}

# Имя тега — как обратная ссылка (?P=name), поэтому открывающий и
# закрывающий тег обязаны совпадать буквально (с учётом IGNORECASE).
_XML_TOOL_TAG_RE = re.compile(
    r'<(?P<name>[A-Za-z_]+)(?P<attrs>[^>]*?)\s*(?:/>|>(?P<content>[\s\S]*?)</(?P=name)\s*>)',
    re.IGNORECASE
)
_XML_ATTR_RE = re.compile(r'(\w+)\s*=\s*"([^"]*)"|(\w+)\s*=\s*\'([^\']*)\'')

# Для дефенсивной зачистки в _strip_text_tool_call: любой тег с известным
# именем, парный или одиночный (незакрытый/самозакрывающийся).
_XML_TAG_STRIP_RE = re.compile(
    r'</?(?:' + '|'.join(_XML_TAG_TOOL_MAP.keys()) + r')\b[^>]*/?>',
    re.IGNORECASE
)


# Вызов в стиле GLM: ИМЯ<arg_key>ключ</arg_key><arg_value>значение</arg_value>
# (пар может быть несколько; иногда всё обёрнуто в <tool_call>...</tool_call>).
# Некоторые модели (например Spark-X2.6) выдают именно его вместо построчного
# "SEARCH: запрос" из инструкции текстового режима. Раньше такой вызов не
# распознавался ни одним парсером: инструмент не запускался, а сырой тег
# оставался и в чате, и в истории.
_ARGKV_TOOL_KEYS = {tn: list(keys) for tn, keys in _XML_TAG_TOOL_MAP.values()}
_ARGKV_TOOL_KEYS["write_text_file"] = ["suggested_name", "content"]
# "search"/"scrape"/... -> имя реального инструмента ("search"/"scrape_url"/...)
_ARGKV_ALIASES = {k.lower(): v[0] for k, v in _XML_TAG_TOOL_MAP.items()}

_ARGKV_PAIR_PAT = r'<arg_key>[\s\S]*?</arg_key>\s*<arg_value>[\s\S]*?</arg_value>\s*'
_ARGKV_CALL_RE = re.compile(
    r'(?:<tool_call>\s*)?(?<![A-Za-z_])(?P<name>[A-Za-z_]+)\s*'
    r'(?P<body>(?:' + _ARGKV_PAIR_PAT + r')+)(?:</tool_call>)?',
    re.IGNORECASE
)
_ARGKV_PAIR_FIND_RE = re.compile(
    r'<arg_key>([\s\S]*?)</arg_key>\s*<arg_value>([\s\S]*?)</arg_value>',
    re.IGNORECASE
)
# Начала строки, после которых ToolSyntaxGate глушит поток до </arg_value>:
# "ИМЯ<arg_key>" для любого известного имени и голый "<arg_key>" (вторая и
# следующие пары того же вызова).
_ARGKV_OPENERS = tuple(sorted(
    {f"{n.upper()}<ARG_KEY>" for n in list(_ARGKV_ALIASES) + list(_ARGKV_TOOL_KEYS)}
    | {"<ARG_KEY>"}
))


def _argkv_resolve(name: str):
    """Имя из текста (SEARCH, scrape, extract_links, ...) -> имя инструмента или None."""
    n = (name or "").lower()
    if n in _ARGKV_ALIASES:
        return _ARGKV_ALIASES[n]
    if n in _ARGKV_TOOL_KEYS:
        return n
    return None


# «Голый» вызов в питон-стиле, обёрнутый в квадратные скобки:
#   [execute_terminal_command(command='uname -a', timeout=10)]
# Модели (замечено за LFM2) помимо настоящего вызова иногда ЭХОМ переписывают
# его в финальном тексте ответа в таком виде. Парсеры такой текст (замышлено)
# вызовом не считают — а зачистка раньше его не трогала, и мусор оставался
# и в чате, и в истории. Имя внутри скобок проверяем и по реальным именам
# инструментов (_KNOWN_TOOL_NAMES), и по коротким псевдонимам протокола
# (EXEC_CMD, SEARCH, ...) — теми же, что признают остальные парсеры.
_BRACKETED_CALL_NAME_RE = re.compile(r'\[\s*([A-Za-z_]\w*)\s*\(')


def _bracketed_call_span_end(text: str, open_paren: int) -> int:
    """Индекс символа СРАЗУ ПОСЛЕ закрывающей ']' для вызова '[имя(...)]',
    чья '(' стоит на позиции open_paren; -1, если это не сбалансированный
    вызов (тогда текст не трогаем). Баланс скобок считаем с учётом кавычек —
    иначе command='ps aux | grep "$(uname)"' ломал бы разбор."""
    depth = 0
    in_str = False
    str_ch = ""
    i = open_paren
    n = len(text)
    while i < n:
        ch = text[i]
        if in_str:
            if ch == "\\":
                i += 2
                continue
            if ch == str_ch:
                in_str = False
        elif ch in ('"', "'"):
            in_str, str_ch = True, ch
        elif ch == "(":
            depth += 1
        elif ch == ")":
            depth -= 1
            if depth == 0:
                j = i + 1
                while j < n and text[j] in " \t":
                    j += 1
                return j + 1 if j < n and text[j] == "]" else -1
        i += 1
    return -1


def _strip_bracketed_pythonic_calls(text: str) -> str:
    """Вычищает эхо-вызовы вида [tool(k='v', ...)] для ИЗВЕСТНЫХ инструментов.
    Обычный текст (включая markdown-ссылки вида [search](url)) не трогает:
    без закрывающей ']' сразу после ')' фрагмент остаётся на месте."""
    if "(" not in text or "[" not in text:
        return text
    pieces = []
    pos = 0
    changed = False
    for m in _BRACKETED_CALL_NAME_RE.finditer(text):
        name = m.group(1)
        if name not in _KNOWN_TOOL_NAMES and not _argkv_resolve(name):
            continue
        end = _bracketed_call_span_end(text, m.end() - 1)
        if end == -1:
            continue
        pieces.append(text[pos:m.start()])
        pos = end
        changed = True
    if not changed:
        return text
    pieces.append(text[pos:])
    return "".join(pieces)


def _strip_text_tool_call(text: str) -> str:
    """Удаляет из текста строку/блок с вызовом текстового инструмента
    (SEARCH:, SCRAPE:, <tool_call>... и т.п.), чтобы:
      1) не показывать служебный синтаксис в UI;
      2) не передавать его модели в истории — иначе модель часто
         повторяет/перефразирует свой же вызов на следующей итерации,
         что приводит к видимому дублированию строк в ответе.
    Строки-документацию (с плейсхолдерами <query>/<url>) не трогает.
    """
    # Построчная чистка через _parse_simple_line: маркеры в скобках, с
    # кириллическими двойниками и с опечатками («[СЕARCH: …]», «CEARCH: …»)
    # вычищаются так же, как обычные (парсер их теперь распознаёт — остатки
    # не должны жить в UI и в истории). Строки-документацию (плейсхолдеры
    # <query>/<url>) _parse_simple_line не распознаёт — они остаются.
    kept = []
    for line in text.split('\n'):
        # Вычищенная строка заменяется пустой (как делал re.sub раньше) —
        # количество строк и позиции не меняются
        kept.append("" if _parse_simple_line(line) is not None else line)
    cleaned = '\n'.join(kept)
    # Ограда ```json {...}``` с валидным вызовом ИЗВЕСТНОГО инструмента —
    # целиком убрать: после фикса _parse_text_tool_calls такие блоки
    # распознаются как вызовы, и их остатки не должны оставаться ни в чате,
    # ни в истории (иначе модель на следующем раунде видит «свой вызов» и
    # пересказывает его словами). Блоки-документацию (не вызов) не трогаем —
    # включая ограды с подводкой «например:» (см. проверку в п.1b
    # _parse_text_tool_calls): правила приёма и вычистки зеркальны, чтобы
    # распознанный вызов всегда вычищался, а цитируемая документация — нет.
    def _fenced_call_sub(m: "re.Match") -> str:
        # Подводка-цитирование ПЕРЕД оградой — это документация, не вызов:
        # не вычищаем (зеркально проверке в п.1b _parse_text_tool_calls).
        if _EXAMPLE_CUE_RE.search(cleaned[max(0, m.start() - 40):m.start()]):
            return m.group(0)
        blob = m.group(1).strip()
        if not blob.startswith("{"):
            return m.group(0)
        try:
            obj = json.loads(blob)
        except Exception:
            return m.group(0)
        name = obj.get("name") if isinstance(obj, dict) else None
        if not (isinstance(name, str) and name in _KNOWN_TOOL_NAMES):
            return m.group(0)
        # Зеркально парсеру (единый дискриминатор): цитата формата с
        # плейсхолдерными аргументами вызовом не признаётся — и из текста
        # не вычищается (правило: распознанный вызов вычищается,
        # документация остаётся).
        if _call_args_documentation(name, obj.get("arguments", {})):
            return m.group(0)
        return ''
    cleaned = _FENCED_BLOCK_RE.sub(_fenced_call_sub, cleaned)
    # Полный блок <｜tool▁calls▁begin｜>…<｜tool▁calls▁end｜> — вырезать
    # ЦЕЛИКОМ: иначе после вырезания отдельных спецтокенов (ниже) посреди
    # ответа остаются 'function', имя инструмента и JSON-аргументы.
    cleaned = re.sub(
        r'<[|｜▁_\s]*tool[|｜▁_\s]*calls[|｜▁_\s]*begin[|｜▁_\s]*>[\s\S]*?<[|｜▁_\s]*tool[|｜▁_\s]*calls[|｜▁_\s]*end[|｜▁_\s]*>',
        '', cleaned, flags=re.IGNORECASE)
    # Спецтокены родного формата DeepSeek/Qwen, напечатанные как текст
    # (U+FF5C «｜» / U+2581 «▁», плюс ASCII-варианты):
    cleaned = re.sub(
        r'<[|｜▁_\s]*tool[|｜▁_\s]*(?:calls?[|｜▁_\s]*(?:begin|end)|call[|｜▁_\s]*(?:begin|end)|name|input)[|｜▁_\s]*>',
        '', cleaned, flags=re.IGNORECASE)
    cleaned = re.sub(r'<tool_call>\s*\{[\s\S]*?\}\s*</tool_call>', '', cleaned)
    # Вызов в стиле GLM: ИМЯ<arg_key>..</arg_key><arg_value>..</arg_value>.
    # Режем только если имя — известный инструмент (обычный текст не трогаем).
    cleaned = _ARGKV_CALL_RE.sub(
        lambda m: '' if _argkv_resolve(m.group("name")) else m.group(0), cleaned
    )
    cleaned = re.sub(r'<\|tool_call_start\|>[\s\S]*?<\|tool_call_end\|>', '', cleaned)
    cleaned = re.sub(r'```tool_call\s*\n\w+\s*\n[\s\S]*?```', '', cleaned)
    # Осиротевший тег без пары: модель иногда ставит голый <tool_call>
    # перед обычным текстом ответа и не закрывает его (нет валидного JSON,
    # нет </tool_call>) — парная регулярка выше его не находит. Вырезаем
    # только сам тег, текст после него — настоящий ответ, не трогаем.
    cleaned = re.sub(r'</?tool_call>', '', cleaned)
    cleaned = re.sub(r'<\|tool_call_(?:start|end)\|>', '', cleaned)
    # Придуманный моделью XML-тег вида <SCRAPE, url="...">...</SCRAPE>:
    # если он всё же не сложился в валидный вызов (см. _parse_xml_tag_tool_calls
    # ниже по файлу) — не даём голым тегам просочиться в текст ответа.
    cleaned = _XML_TAG_STRIP_RE.sub('', cleaned)
    # Эхо вызова в питон-стиле в квадратных скобках (см. docstring функции):
    # вычищаем последним проходом, когда остальные форматы уже разобраны.
    cleaned = _strip_bracketed_pythonic_calls(cleaned)
    cleaned = re.sub(r'\n{3,}', '\n\n', cleaned)
    return cleaned.strip()


_TOOL_LINE_KEYWORDS = [
    "SEARCH:", "SCRAPE:", "LINKS:", "META:", "SEARCHPAGE:", "SCRAPEMULTI:",
    "READ_FILE:", "READ_PDF:", "EXEC_CMD:",
    "MEMORY_WRITE:", "MEMORY_READ", "MEMORY_DELETE:",
]
_TOOL_BLOCK_OPENERS = {
    "<TOOL_CALL>": "</TOOL_CALL>",
    "<|TOOL_CALL_START|>": "<|TOOL_CALL_END|>",
    "```TOOL_CALL": "```",
}
# Открывающий тег придуманного моделью XML-формата (<SCRAPE ...>,
# <SEARCH ...> и т.п.) заранее неизвестен целиком — имя тега нужно
# сначала накопить посимвольно и свериться с _XML_TAG_TOOL_MAP, поэтому
# он не влезает в статический словарь _TOOL_BLOCK_OPENERS выше (там нужен
# фиксированный опенер целиком). Обрабатывается отдельной веткой в
# ToolSyntaxGate.feed() через _XML_TAG_OPEN_RE.
_XML_TAG_OPEN_RE = re.compile(r'^<([A-Za-z_]+)([\s,/>])')
_XML_TAG_PREFIXES = tuple(f"<{name}" for name in _XML_TAG_TOOL_MAP)
_TOOL_WATCH_MAX = max(
    [len(k) for k in _TOOL_LINE_KEYWORDS + list(_TOOL_BLOCK_OPENERS)]
    + [len(p) for p in _XML_TAG_PREFIXES]
    + [len(o) for o in _ARGKV_OPENERS]
) + 2


class ToolSyntaxGate:
    """Фильтрует live-стрим content-чанков перед показом в UI, не давая
    мелькнуть служебному синтаксису текстовых tool-call'ов (строкам
    SEARCH:/SCRAPE:/... и блокам <tool_call>{...}</tool_call>) в момент,
    когда модель их печатает. На итоговый результат раунда не влияет:
    assistant_text по-прежнему собирается из НЕотфильтрованных чанков
    (core/worker.py), а по завершении раунда история/повторный рендер
    (`clear_stream`) уже строятся из полного текста через
    `_strip_text_tool_call`/`_parse_simple_text_tools`, как и раньше.
    Здесь — только косметика во время стриминга.

    Работает построчно: в начале каждой строки копит символы, пока не
    станет ясно — это начало служебной команды (тогда строка/блок
    полностью проглатывается) или обычный текст (тогда накопленное
    сразу отдаётся и до конца строки идёт обычный live-показ).
    """

    def __init__(self):
        self._mode  = "watch"   # watch | passthrough | suppress_line | suppress_block
        self._buf   = ""
        self._close = ""
        # Было ли за раунд проглочено что-то служебное. Если да — после
        # раунда без вызова инструмента воркер синхронизирует видимый текст
        # с историей через clear_stream (см. core/worker.py).
        self.suppressed_any = False

    def feed(self, chunk: str) -> str:
        out = []
        i = 0
        n = len(chunk)
        while i < n:
            ch = chunk[i]

            if self._mode == "suppress_block":
                # Закрывающий тег может прийти отдельным чанком (даже по
                # одному символу за раз) — нельзя искать только внутри
                # текущего chunk, нужен переходящий между вызовами хвост
                # в self._buf. _close хранится в верхнем регистре (см.
                # _TOOL_BLOCK_OPENERS), а модель обычно пишет теги
                # строчными — ищем без учёта регистра. Для придуманного
                # XML-тега self._close — кортеж из двух вариантов
                # терминатора: обычное закрытие "</NAME>" и
                # самозакрывающееся "/>" (у него нет отдельного закрывающего
                # тега вообще) — берём тот, что встретится раньше, иначе
                # при самозакрывающемся теге глушилка ждала бы "</NAME>"
                # вечно и проглотила бы весь остаток стрима.
                closers = self._close if isinstance(self._close, tuple) else (self._close,)
                self._buf += chunk[i:]
                buf_upper = self._buf.upper()
                best_idx, best_len = -1, 0
                for c in closers:
                    idx = buf_upper.find(c)
                    if idx != -1 and (best_idx == -1 or idx < best_idx):
                        best_idx, best_len = idx, len(c)
                if best_idx == -1:
                    keep = max(len(c) for c in closers) - 1
                    if keep > 0:
                        self._buf = self._buf[-keep:]
                    i = n
                else:
                    leftover = self._buf[best_idx + best_len:]
                    self._mode = "watch"
                    self._buf = ""
                    if leftover:
                        out.append(self.feed(leftover))
                    i = n
                continue

            if self._mode == "suppress_line":
                nl = chunk.find("\n", i)
                if nl == -1:
                    i = n
                else:
                    i = nl + 1
                    self._mode = "watch"
                    self._buf = ""
                continue

            if self._mode == "passthrough":
                nl = chunk.find("\n", i)
                if nl == -1:
                    out.append(chunk[i:])
                    i = n
                else:
                    out.append(chunk[i:nl + 1])
                    i = nl + 1
                    self._mode = "watch"
                continue

            # self._mode == "watch"
            self._buf += ch
            i += 1
            if ch == "\n":
                # Строка кончилась, ни один вариант не подошёл — обычный текст.
                out.append(self._buf)
                self._buf = ""
                continue
            upper = self._buf.lstrip().upper()
            block_hit = next(
                (op for op in _TOOL_BLOCK_OPENERS if upper.startswith(op)), None
            )
            if block_hit:
                self._close = _TOOL_BLOCK_OPENERS[block_hit]
                self._mode  = "suppress_block"
                self.suppressed_any = True
                self._buf   = ""
                continue
            # Придуманный моделью XML-тег: <SCRAPE, url="...">... —
            # имя тега заранее неизвестно целиком, поэтому опенер не из
            # статического словаря, а разбирается регуляркой на лету, как
            # только после имени встретился разделитель (пробел/запятая/
            # "/" /">") — до этого момента могло быть ещё неоднозначно
            # (например "<SCRAPE" — префикс и SCRAPE, и SCRAPEMULTI).
            xml_m = _XML_TAG_OPEN_RE.match(upper)
            if xml_m and xml_m.group(1) in _XML_TAG_TOOL_MAP:
                self._close = (f"</{xml_m.group(1)}>", "/>")
                self._mode  = "suppress_block"
                self.suppressed_any = True
                self._buf   = ""
                continue
            # Вызов в стиле GLM: ИМЯ<arg_key>..</arg_key><arg_value>..</arg_value>
            # (или голый <arg_key> — следующая пара того же вызова). Глушим
            # до </arg_value>; хвост (следующая пара/обычный текст) feed()
            # разберёт заново.
            if any(upper.startswith(op) for op in _ARGKV_OPENERS):
                self._close = "</ARG_VALUE>"
                self._mode  = "suppress_block"
                self.suppressed_any = True
                self._buf   = ""
                continue
            line_hit = next(
                (kw for kw in _TOOL_LINE_KEYWORDS if upper.startswith(kw)), None
            )
            if line_hit:
                self._mode = "suppress_line"
                self.suppressed_any = True
                self._buf  = ""
                continue
            still_possible = any(
                marker.startswith(upper)
                for marker in list(_TOOL_BLOCK_OPENERS) + _TOOL_LINE_KEYWORDS
            ) or upper.startswith("<") and any(
                p.startswith(upper) or upper.startswith(p) for p in _XML_TAG_PREFIXES
            ) or any(op.startswith(upper) for op in _ARGKV_OPENERS)
            if not still_possible or len(self._buf) >= _TOOL_WATCH_MAX:
                out.append(self._buf)
                self._buf  = ""
                self._mode = "passthrough"
        return "".join(out)


    def flush(self) -> str:
        """Конец потока: отдать накопленное в режиме наблюдения (короткая
        последняя строка без \n, похожая на начало служебного маркера, —
        например одинокое \"M\" или \"<\"). В режимах suppress_* буфер —
        это уже проглоченный служебный синтаксис, он не возвращается."""
        out = self._buf if self._mode == "watch" else ""
        self._buf = ""
        self._mode = "watch"
        return out


def _strip_orphan_think(text: str) -> str:
    """Для текста, который уходит в историю диалога/контекст (а не в
    виджет чата — там та же проблема чинится в
    ui/chat_area.py::_reclaim_round_as_thought). Модель иногда начинает
    ход неявно "в режиме размышления" (без открывающего <think>) и
    присылает только закрывающий тег в потоке content — тогда всё до
    него на самом деле было черновиком рассуждения, а не ответом, и не
    должно попадать ни в сохранённую историю, ни обратно в контекст
    следующего запроса (иначе модель будет получать на вход свой же
    черновик как часть "своего предыдущего ответа" и путаться)."""
    text = re.sub(r'<think>[\s\S]*?</think>', '', text, flags=re.IGNORECASE)
    idx = text.find('</think>')
    if idx != -1:
        text = text[idx + len('</think>'):]
    return text.strip()


def _clean_for_history(text: str) -> str:
    t = text.replace('&lt;', '<').replace('&gt;', '>')
    # Было: re.sub(r'<think>.*', '', t, DOTALL) — вырезало ВСЁ от <think>
    # и до конца строки целиком, включая настоящий ответ после </think>,
    # если тег вообще открылся. Теперь: только парные <think>...</think>,
    # а одинокий незакрытый тег (или голое закрытие без открытия) чинится
    # через _strip_orphan_think.
    t = _strip_orphan_think(t)
    t = re.sub(r'<\|tool_call_start\|>[\s\S]*?<\|tool_call_end\|>', '', t)
    t = re.sub(r'\n{3,}', '\n', t)
    return t.strip()

def _balanced_json_from(text: str, start: int):
    """Читает сбалансированный JSON-объект, начинающийся с text[start] == '{',
    корректно обходя скобки и кавычки ВНУТРИ строковых значений
    ({"content": "код {x}"} не ломает подсчёт глубины).
    Возвращает (объект|None, индекс за закрывающей '}')."""
    if start < 0 or start >= len(text) or text[start] != "{":
        return None, start
    depth, in_string, escape = 0, False, False
    for i in range(start, len(text)):
        ch = text[i]
        if in_string:
            if escape:
                escape = False
            elif ch == "\\":
                escape = True
            elif ch == '"':
                in_string = False
            continue
        if ch == '"':
            in_string = True
        elif ch == "{":
            depth += 1
        elif ch == "}":
            depth -= 1
            if depth == 0:
                try:
                    return json.loads(text[start:i + 1]), i + 1
                except Exception:
                    return None, i + 1
    return None, len(text)


# Родной tool-call формат DeepSeek/Qwen, который модель иногда печатает
# ОБЫЧНЫМ ТЕКСТОМ в content, когда запрос шёл без массива tools (текстовый
# режим этого приложения):
#   <｜tool▁calls▁begin｜><｜tool▁call▁begin｜>function
#   <｜tool▁name｜>search
#   <｜tool▁input｜>{"query": "..."}
#   <｜tool▁call▁end｜><｜tool▁calls▁end｜>
# Спецтокены содержат U+FF5C (｜) и U+2581 (▁); часть сборок/квантов
# выдаёт ASCII-варианты (|tool_name|) — принимаем и их. Раньше такой
# вызов не распознавался вообще: модель «вызвала» поиск, а сырые
# спецтокены оставались текстом ответа.
_DEEPSEEK_NAME_RE = re.compile(
    # Токен вида <｜tool▁name｜> / <|tool_name|> / <| tool name |>:
    # разделители — ASCII '|', полноширинный '｜' (U+FF5C), '▁' (U+2581),
    # '_' и пробелы в любой комбинации.
    r"<[|｜▁_\s]*tool[|｜▁_\s]*name[|｜▁_\s]*>\s*([A-Za-z_]\w*)",
    re.IGNORECASE,
)
# Ограда ```json { ... } ``` / ```tool_call { ... } ```: модель часто
# обкладывает вызов пояснениями («Сейчас выполню поиск… ```json …```»).
# Ограда делает намерение однозначным, поэтому требования «JSON должен
# занимать ≥50% ответа» для блоков в ограде нет.
_FENCED_BLOCK_RE = re.compile(r"```[A-Za-z0-9_]*[ \t]*\n?([\s\S]*?)```")


def _json_call_from_object(obj) -> "dict | None":
    """{"name":..., "arguments":...} или {"function": {...}} → нормализованный
    вызов; None, если форма не похожа на вызов инструмента."""
    if not isinstance(obj, dict):
        return None
    if isinstance(obj.get("name"), str) and "arguments" in obj:
        args = obj["arguments"] if isinstance(obj["arguments"], dict) else {}
        return {"function": {"name": obj["name"], "arguments": args}}
    fn = obj.get("function")
    if isinstance(fn, dict) and isinstance(fn.get("name"), str):
        args = fn.get("arguments", {}) if isinstance(fn.get("arguments"), dict) else {}
        return {"function": {"name": fn["name"], "arguments": args}}
    return None


def _dedupe_calls(results: list) -> list:
    """Убирает дубли одного и того же вызова (имя + аргументы), которые
    возникают, если текст распознали сразу несколько секций парсера.
    Без дедупликации воркер выполнил бы вызов один раз, а на второй копии
    показал бы в чате лишний бейдж «(повтор)»."""
    uniq, seen = [], set()
    for r in results:
        fn = r.get("function", {})
        key = (fn.get("name", ""),
               json.dumps(fn.get("arguments", {}), sort_keys=True, ensure_ascii=False))
        if key in seen:
            continue
        seen.add(key)
        uniq.append(r)
    return uniq


def _parse_text_tool_calls(text: str) -> list[dict]:
    results = []
    # 1) Явные обёртки — разбираются без эвристик.
    for m in re.finditer(r'<tool_call>\s*(\{[\s\S]*?\})\s*</tool_call>', text):
        try:
            obj = json.loads(m.group(1))
            if "name" in obj:
                args = obj.get("arguments", {})
                if _call_args_documentation(str(obj.get("name", "")), args):
                    continue
                results.append({"function": {
                    "name": obj["name"],
                    "arguments": args
                }})
        except Exception:
            pass
    for m in re.finditer(
        r'<\|tool_call_start\|>call:(\w+)\s*(\{[\s\S]*?\})\s*<\|tool_call_end\|>', text
    ):
        name, raw_args = m.group(1), m.group(2)
        try:    args = json.loads(raw_args)
        except Exception: args = {}
        results.append({"function": {"name": name, "arguments": args}})
    for m in re.finditer(r'```tool_call\s*\n(\w+)\s*\n([\s\S]*?)```', text):
        name, raw_args = m.group(1).strip(), m.group(2).strip()
        try:    args = json.loads(raw_args)
        except Exception: args = {}
        results.append({"function": {"name": name, "arguments": args}})
    if results:
        return _dedupe_calls(results)

    # 1b) Блок в кодовой ограде ```json { ... } ``` (язык может быть любым
    # или отсутствовать). Модели — особенно кванты, обученные на
    # tool-call-форматах, — часто обкладывают вызов пояснениями:
    # «Сейчас выполню поиск… ```json {"name": "search", …}```». Раньше
    # такой вызов ОТВЕРГАЛСЯ эвристикой п.2 (JSON занимал <50% текста), и
    # получалось ровно то, что видит пользователь: модель пишет, что
    # вызывает поиск, но вызов не распознаётся и не выполняется. Ограда
    # делает намерение однозначным — принимаем вызов с известным именем
    # без требований к доле текста.
    for m in _FENCED_BLOCK_RE.finditer(text):
        blob = m.group(1).strip()
        if not blob.startswith("{"):
            continue
        # Подводка-цитирование («например:», «for example», «шаблон» и т.п.)
        # ПЕРЕД оградой означает, что блок — пример из документации, а не
        # настоящий вызов (та же защита, что и для «голого» JSON в п.2).
        # Без неё объясняющий текст «формат вызова такой, например:
        # ```json {...}```» выполнялся бы как реальный вызов инструмента.
        if _EXAMPLE_CUE_RE.search(text[max(0, m.start() - 40):m.start()]):
            continue
        try:
            obj = json.loads(blob)
        except Exception:
            continue
        call = _json_call_from_object(obj)
        if call is not None and not _call_args_documentation(
                call["function"]["name"], call["function"]["arguments"]):
            results.append(call)
    if results:
        return _dedupe_calls(results)

    # 2) Эвристика последней очереди: JSON-объект вида {"name":...,"arguments":...}
    # или {"function": {...}} прямо в тексте ответа (без ограды).
    # Принимается, если объект составляет основную часть текста, ЛИБО если
    # имя — известный инструмент (история: модель с валидным вызовом и
    # длинной подводкой на «текстовые» модели получала отказ из-за правила
    # ≥50% и просто НЕ вызывала инструмент, сообщая пользователю, что
    # «поиск выполнен»). Отвергается всегда, если перед объектом есть
    # подводка «например:» / «for example» — это цитирование документации,
    # а не вызов.
    stripped_len = max(len(text.strip()), 1)
    # Ограждённые блоки — монополия секции 1b (там подводка «например:»
    # проверяется относительно НАЧАЛА ограды). Сканер «голого» JSON не
    # должен вторично обрабатывать содержимое оград: иначе документационный
    # пример, отвергнутый в 1b из-за подводки «например:\n```json {...}»,
    # принимался бы здесь повторно — от самого брейса подводка уже не видна
    # (окно before кончается маркером ограды «```json\n», и regex подводки,
    # требующий конца строки, на нём не срабатывает).
    fenced_spans = [(m.start(), m.end()) for m in _FENCED_BLOCK_RE.finditer(text)]
    i, n = 0, len(text)
    while i < n:
        if text[i] != "{":
            i += 1
            continue
        if any(s <= i < e for s, e in fenced_spans):
            i += 1
            continue
        obj, end = _balanced_json_from(text, i)
        if obj is None:
            i += 1
            continue
        candidate = text[i:end]
        before = text[:i]
        dominates_text = len(candidate.strip()) >= 0.5 * stripped_len
        looks_like_example = bool(_EXAMPLE_CUE_RE.search(before[-40:]))
        if not looks_like_example:
            call = _json_call_from_object(obj)
            if call is not None and (dominates_text
                                     or call["function"]["name"] in _KNOWN_TOOL_NAMES) \
                    and not _call_args_documentation(call["function"]["name"],
                                     call["function"]["arguments"]):
                results.append(call)
        i = end
    if results:
        return _dedupe_calls(results)

    # 3) Родной формат DeepSeek/Qwen (<｜tool▁name｜>ИМЯ … <｜tool▁input｜>{…}):
    # модель печатает спецтокены как обычный текст, когда tools в запросе
    # не было (текстовый режим). Имя берём после токена tool▁name,
    # аргументы — первый сбалансированный JSON после него.
    for m in _DEEPSEEK_NAME_RE.finditer(text):
        brace = text.find("{", m.end())
        obj, _end = _balanced_json_from(text, brace)
        if not isinstance(obj, dict):
            obj = {}
        if _call_args_documentation(m.group(1), obj):
            continue
        results.append({"function": {"name": m.group(1), "arguments": obj}})
    return _dedupe_calls(results)


def _parse_xml_tag_tool_calls(text: str) -> list[dict]:
    """Распознаёт вызов инструмента, оформленный моделью как
    XML/HTML-подобный тег вместо ожидаемого построчного синтаксиса
    "SCRAPE: <url>", например:

        <SCRAPE, url="https://example.com">
        </SCRAPE>

    или самозакрывающийся <SCRAPE url="https://example.com"/>.

    Модель иногда придумывает такой формат сама (насмотревшись на
    JSON/XML tool-call протоколы где-то в обучении), хотя в системном
    промпте для текстового режима описан только построчный формат
    KEYWORD: значение. Раньше подобные теги не ловились ни
    _parse_simple_text_tools, ни _parse_text_tool_calls и молча
    оставались текстом ответа — реального вызова инструмента не
    происходило, хотя модель была уверена, что вызвала его (тот же баг,
    что был найден и исправлен в LLM-Chat/core/tool_parsing.py на
    экспорте чата с анализом "AMD Eng Sample").

    Как и _parse_simple_text_tools, за один раунд разбирается только
    ПЕРВЫЙ подходящий тег — остальные (если есть) модель допишет в
    следующих раундах, получив результат первого.
    """
    for m in re.finditer(_XML_TOOL_TAG_RE, text):
        name = m.group("name").upper()
        mapped = _XML_TAG_TOOL_MAP.get(name)
        if not mapped:
            continue
        tool_name, arg_keys = mapped

        attrs = {}
        for am in _XML_ATTR_RE.finditer(m.group("attrs") or ""):
            key = (am.group(1) or am.group(3) or "").lower()
            val = am.group(2) if am.group(2) is not None else am.group(4)
            if key:
                attrs[key] = (val or "").strip()

        content = (m.group("content") or "").strip()

        args = {}
        for key in arg_keys:
            if attrs.get(key):
                args[key] = attrs[key]
        # Однопараметровые теги (SCRAPE/SEARCH/LINKS/META/READ_FILE/
        # READ_PDF/SCRAPEMULTI) без атрибута — используем текст между
        # тегами: <SEARCH>какой-то запрос</SEARCH>.
        primary = arg_keys[0]
        if len(arg_keys) == 1 and primary not in args and content:
            args[primary] = content

        if primary not in args:
            # Без основного параметра вызов бессмысленный — это не тот
            # тег, продолжаем искать следующее совпадение.
            continue

        if _call_args_documentation(tool_name, args):
            # Цитата формата в виде тега (<SCRAPE url="<url>"/>) — не вызов.
            continue

        if tool_name == "scrape_multiple" and isinstance(args.get("urls"), str):
            args["urls"] = [u.strip() for u in args["urls"].split(",") if u.strip()]

        return [{"function": {"name": tool_name, "arguments": args}}]

    return []


def _parse_argkv_tool_calls(text: str) -> list[dict]:
    """Распознаёт вызов в стиле GLM:

        SEARCH<arg_key>query</arg_key><arg_value>где родился Ленин</arg_value>

    (имя — псевдоним из _XML_TAG_TOOL_MAP либо настоящее имя инструмента;
    пар ключ/значение может быть несколько; допускается обёртка
    <tool_call>...</tool_call>). Как и соседние парсеры, за раунд
    разбирается только ПЕРВЫЙ подходящий вызов. Если модель придумала
    своё имя ключа для инструмента с единственным параметром (например
    <arg_key>q</arg_key>), значение берётся как основной параметр.
    """
    for m in _ARGKV_CALL_RE.finditer(text):
        tool_name = _argkv_resolve(m.group("name"))
        if not tool_name:
            continue
        pairs = _ARGKV_PAIR_FIND_RE.findall(m.group("body"))
        args = {}
        for k, v in pairs:
            k = k.strip().lower()
            if k:
                args[k] = v.strip()

        keys = _ARGKV_TOOL_KEYS.get(tool_name, [])
        primary = keys[0] if keys else None
        if not primary:
            continue
        # Придуманное моделью имя ключа (<arg_key>q</arg_key>) подменяем основным
        # параметром только у инструментов с ОДНИМ параметром (search, scrape_url...).
        if len(keys) == 1 and primary not in args and len(args) == 1:
            args = {primary: next(iter(args.values()))}
        # memory_read: все параметры необязательны (пусто = прочитать всю память)
        if tool_name != "memory_read" and not args.get(primary):
            continue
        # Цитата формата с плейсхолдерными значениями — не вызов
        # (у memory_read пустые параметры легитимны, его не проверяем).
        if tool_name != "memory_read" and _call_args_documentation(tool_name, args):
            continue

        if tool_name == "scrape_multiple" and isinstance(args.get("urls"), str):
            raw = args["urls"]
            urls = None
            if raw.startswith("["):
                try:
                    urls = [str(u).strip() for u in json.loads(raw)]
                except Exception:
                    urls = None
            if urls is None:
                urls = [u.strip() for u in re.split(r'[,\n]', raw) if u.strip()]
            args["urls"] = urls

        return [{"function": {"name": tool_name, "arguments": args}}]
    # Вызов без единого аргумента: <tool_call>memory_read</tool_call>
    if re.search(r'<tool_call>\s*memory_read\s*</tool_call>', text, re.IGNORECASE):
        return [{"function": {"name": "memory_read", "arguments": {}}}]
    return []


def _build_spark_tools_instruction(use_search: bool, enable_files: bool,
                                   enable_memory: bool, enable_write: bool,
                                   enable_terminal: bool = False,
                                   after_result: bool = False) -> str:
    """Компактная инструкция для Spark-X2.x в ЕЁ родном формате вызова
    (<tool_call>имя + пары <arg_key>/<arg_value>), без JSON-схем.
    Разбирается _parse_argkv_tool_calls. Имена инструментов — настоящие
    (search, scrape_url, ...), а не псевдонимы SEARCH:/SCRAPE: текстового режима."""
    tools = []   # (имя, [параметры], описание)
    if use_search:
        tools += [
            ("search", ["query", "time_range"],
             "поиск в интернете; time_range необязателен: none|day|week|month|year"),
            ("scrape_url", ["url"], "текст страницы со списком ссылок"),
            ("extract_links", ["url"], "все ссылки страницы"),
            ("extract_metadata", ["url"], "title/description страницы"),
            ("search_page", ["url", "query"], "поиск фразы внутри страницы"),
            ("scrape_multiple", ["urls"], "2–5 страниц сразу, URL через запятую"),
        ]
    if enable_files:
        tools += [
            ("read_file", ["path"], "прочитать локальный текстовый файл (абсолютный путь)"),
            ("read_pdf", ["path"], "прочитать локальный PDF (абсолютный путь)"),
        ]
    if enable_memory:
        tools += [
            ("memory_write", ["category", "key", "value"],
             "запомнить; category: preference|correction|personal|workflow|note"),
            ("memory_read", ["category", "key"], "прочитать память; пустые поля — вся память"),
            ("memory_delete", ["category", "key"], "удалить запись из памяти"),
        ]
    if enable_write:
        tools += [
            ("write_text_file", ["suggested_name", "content", "target_format"],
             "сохранить готовый документ отдельным файлом, не переписывая оригинал; "
             "target_format: md|docx|pdf"),
        ]
    if enable_terminal:
        tools += [
            ("execute_terminal_command", ["command", "timeout"],
             "выполнить команду bash и вернуть её вывод; timeout необязателен "
             "(сек, по умолчанию 30); команда одной строкой"),
        ]
    if not tools:
        return ""

    ex_name, ex_params, _ = tools[0]
    ex_pairs = "".join(
        f"<arg_key>{prm}</arg_key><arg_value>значение</arg_value>"
        for prm in ex_params[:1]
    )
    out = [
        "",
        "[Инструменты]",
        "Чтобы вызвать инструмент, выведи ровно один блок такого вида и остановись — "
        "результат придёт следующим сообщением:",
        f"<tool_call>{ex_name}",
        ex_pairs,
        "</tool_call>",
        "Имя инструмента — на первой строке после <tool_call>, каждый параметр — парой "
        "<arg_key>имя</arg_key><arg_value>значение</arg_value>. После </tool_call> ничего не пиши.",
        "Доступные инструменты (параметры в скобках):",
    ]
    for name, params, desc in tools:
        out.append(f"- {name}({', '.join(params)}) — {desc}")
    if after_result:
        # Результат инструмента уже в диалоге. Без этого абзаца правило «сначала
        # вызови search» из системного промпта срабатывало в КАЖДОМ раунде, и
        # модель повторно искала, хотя в её же рассуждении ответ уже был найден.
        out.append(
            "Результаты вызовов уже получены — они в сообщениях «[Результат …]». "
            "Если их достаточно для ответа, отвечай пользователю сразу и НЕ вызывай "
            "инструмент повторно с тем же или похожим запросом. Новый вызов — только "
            "если результатов явно не хватает."
        )
    elif use_search:
        out.append(
            "ВАЖНО: если вопрос касается конкретных фактов, дат, имён, событий, чисел или "
            "другой проверяемой информации — сначала вызови search, даже если тебе кажется, "
            "что ты знаешь ответ. Не отвечай по памяти на такие вопросы без поиска."
        )
    return "\n".join(out) + "\n"


def _build_text_tools_instruction(use_search: bool = False,
                                  enable_files: bool = False,
                                  enable_memory: bool = False,
                                  enable_write: bool = False,
                                  enable_terminal: bool = False) -> str:
    """Компактная инструкция «экономного текстового режима» (однострочные
    вызовы SEARCH:/SCRAPE:/EXEC_CMD:/...). ЕДИНЫЙ источник для обоих
    проектов: раньше одинаковые блоки поддерживались вручную в каждом
    core/worker.py и разъехались.

    Против «зацикливания» на инструкциях (тест journalctl, ноябрь 2026):
      - правило SEARCH ограничено сведениями из интернета — локальные задачи
        (терминал/файлы/система) явно выведены из-под него;
      - формат результата объяснён заранее с ПОЛНЫМ именем инструмента
        («[Результат execute_terminal_command]»);
      - few-shot примеры — главный рычаг для моделей ≤2B (диагностика
        LFM3, ноябрь 2026: без примеров модель имитировала результат
        («[Результат …]: …» сама) и портила маркер («СЕARCH»/«CEARCH»)).
        Примеры — только для ВКЛЮЧЁННЫХ инструментов, иначе в files-only
        инструкции появился бы «SEARCH:» (ломает
        test_text_instruction_per_flag_blocks)."""
    if not (use_search or enable_files or enable_memory
            or enable_write or enable_terminal):
        return ""
    instr = "\n[Инструменты доступны в текстовом режиме]\n"
    if use_search:
        instr += (
            "Чтобы выполнить поиск, напиши строкой: SEARCH: <запрос>\n"
            "Чтобы извлечь страницу: SCRAPE: <url>\n"
            "Чтобы получить ссылки: LINKS: <url>\n"
            "Чтобы метаданные: META: <url>\n"
            "Поиск по странице: SEARCHPAGE: <url> | <запрос>\n"
            "Пакетное извлечение: SCRAPEMULTI: <url1>, <url2>, ...\n"
            "SEARCH — только для сведений из интернета (новости, версии, цены, "
            "события в мире): если такие данные нужны, сначала сделай SEARCH, "
            "а не отвечай по памяти. Локальные задачи (файлы, терминал, железо, "
            "система) решай другими инструментами, без поиска.\n"
        )
    if enable_files:
        instr += (
            "Чтобы прочитать текстовый файл: READ_FILE: <абсолютный_путь>\n"
            "Чтобы прочитать PDF файл: READ_PDF: <абсолютный_путь>\n"
        )
    if enable_memory:
        instr += (
            "Сохранить в память: MEMORY_WRITE: <категория> | <ключ> | <значение>\n"
            "Прочитать память: MEMORY_READ: <категория> | <ключ>\n"
            "Удалить из памяти: MEMORY_DELETE: <категория> | <ключ>\n"
        )
    if enable_write:
        instr += (
            "Чтобы сохранить готовый документ отдельным файлом (не переписывая "
            "оригинал), вызови:\n"
            '{"name": "write_text_file", "arguments": '
            '{"suggested_name": "<имя_файла.md>", "content": "<полный текст документа>", '
            '"target_format": "md|docx|pdf"}}\n'
        )
    if enable_terminal:
        instr += (
            "Чтобы выполнить команду в терминале пользователя (Linux, bash) "
            "и получить её вывод: EXEC_CMD: <команда>\n"
            "Команда одной строкой; несколько действий соединяй через && или ;. "
            "Интерактивные программы запрещены: вместо htop — ps aux, "
            "journalctl — только с --no-pager. sudo не работает — не используй "
            "его; деструктивные команды тоже блокируются.\n"
        )
    instr += (
        "Когда нужен инструмент, выведи в этом ходе ТОЛЬКО строку вызова в одном "
        "из форматов выше и остановись — результат придёт следующим сообщением в "
        "виде «[Результат <имя_инструмента>]: …» (результат твоего EXEC_CMD "
        "обозначен полным именем: «[Результат execute_terminal_command]»). "
        "Не описывай вызов словами («сейчас выполню поиск…») — без реальной "
        "строки вызова инструмент не запустится.\n"
        "Важно: результат вызова пишет СИСТЕМА, а не ты. Никогда не пиши строки "
        "вида «[Результат …]: …» сам — это признак сломанного ответа, инструмент "
        "при этом не запускается. Строку вызова пиши одной строкой, без скобок "
        "[...] и без кавычек.\n"
    )
    if enable_terminal:
        instr += (
            "Пример: пользователь спрашивает «какое время установлено в системе?» — "
            "твой ВЕСЬ ответ в этом ходе: EXEC_CMD: date\n"
        )
    if use_search:
        instr += (
            "Пример: пользователь спрашивает «где родился Пушкин?» — твой ВЕСЬ ответ "
            "в этом ходе: SEARCH: Пушкин место рождения\n"
        )
    return instr


# Дописка к каждому сообщению-результату инструмента в текстовых режимах
# (результат приходит как user-сообщение «[Результат …]», а раунд с самим
# вызовом в историю НЕ попадает). Без неё модель видит результат «из ниоткуда»:
# не связывает его со своим вызовом и тратит тысячи токенов размышлений на
# вопрос «вызывать ли инструмент ещё раз или уже отвечать?» (тот же тест
# journalctl: второй блок размышлений был ровно об этом).
_TOOL_RESULT_NOTE = (
    "\n\n(Это результат твоего вызова из предыдущего хода. Если данных "
    "достаточно — сразу ответь пользователю и не вызывай инструмент повторно "
    "с теми же аргументами; новый вызов — только для следующего шага.)"
)


def _is_spark_model(model_name: str) -> bool:
    """Spark-X2.x (SparkLLM / iFlytek). Обучена вызывать инструменты в формате
    <tool_call>имя<arg_key>..</arg_key><arg_value>..</arg_value></tool_call>
    (см. карточку модели и vLLM-парсер spark25)."""
    return bool(re.search(r'spark[-_ ]?x?\d', (model_name or "").lower()))

def _is_lfm2_model(model_name: str) -> bool:
    n = model_name.lower()
    return ("lfm2" in n) or ("lfm-2" in n) or ("liquid" in n and "lfm" in n)

def _parse_pythonic_kwargs(s: str) -> dict:
    args = {}
    i = 0
    while i < len(s):
        while i < len(s) and s[i] in (" ", "\t", "\n", ","):
            i += 1
        if i >= len(s): break
        km = re.match(r'(\w+)\s*=\s*', s[i:])
        if not km:
            i += 1
            continue
        key = km.group(1)
        i += km.end()
        if i >= len(s):
            args[key] = None
            break
        val, consumed = _read_value(s, i)
        args[key] = val
        i += consumed
    return args

def _read_value(s: str, i: int):
    if i >= len(s): return None, 0
    ch = s[i]
    if ch in ('"', "'"):
        q = ch
        j = i + 1
        buf = ""
        while j < len(s):
            c = s[j]
            if c == "\\" and j + 1 < len(s):
                buf += s[j + 1]
                j += 2
            elif c == q:
                j += 1
                break
            else:
                buf += c
                j += 1
        return buf, j - i
    if ch in ("[", "{"):
        depth, in_str, str_ch, j = 1, False, "", i + 1
        while j < len(s) and depth > 0:
            c = s[j]
            if in_str:
                if c == "\\" and j + 1 < len(s):
                    j += 2
                    continue
                if c == str_ch:
                    in_str = False
            else:
                if c in ('"', "'"):
                    in_str, str_ch = True, c
                elif c in ("[", "{"):
                    depth += 1
                elif c in ("]", "}"):
                    depth -= 1
            j += 1
        raw = s[i:j]
        try:
            return json.loads(raw), j - i
        except Exception:
            return raw, j - i
    j = i
    while j < len(s) and s[j] not in (",", ")", "\n"):
        j += 1
    token = s[i:j].strip()
    if token == "True": return True, j - i
    if token == "False": return False, j - i
    if token == "None": return None, j - i
    try: return int(token), j - i
    except ValueError: pass
    try: return float(token), j - i
    except ValueError: pass
    return token, j - i

def _parse_lfm2_pythonic(raw: str) -> list[dict]:
    results = []
    raw = raw.strip()
    if raw.startswith("[") and raw.endswith("]"):
        inner = raw[1:-1].strip()
    else:
        inner = raw
    calls_raw = []
    depth, in_str, str_ch, buf, i = 0, False, "", "", 0
    while i < len(inner):
        ch = inner[i]
        if in_str:
            buf += ch
            if ch == "\\" and i + 1 < len(inner):
                i += 1
                buf += inner[i]
            elif ch == str_ch:
                in_str = False
        else:
            if ch in ('"', "'"):
                in_str, str_ch = True, ch
                buf += ch
            elif ch == "(":
                depth += 1
                buf += ch
            elif ch == ")":
                depth -= 1
                buf += ch
                if depth == 0:
                    calls_raw.append(buf.strip())
                    buf = ""
                    j = i + 1
                    while j < len(inner) and inner[j] in (" ", "\t", "\n", ","):
                        j += 1
                    i = j
                    continue
            else:
                buf += ch
        i += 1
    if not calls_raw and buf.strip():
        calls_raw = [buf.strip()]
    for call in calls_raw:
        m = re.match(r'^(\w+)\s*\(([\s\S]*)\)\s*$', call, re.DOTALL)
        if not m: continue
        func_name = m.group(1)
        args_raw  = m.group(2).strip()
        args      = _parse_pythonic_kwargs(args_raw)
        results.append({"function": {"name": func_name, "arguments": args}})
    return results

def _parse_lfm2_tool_calls(text: str) -> list[dict]:
    text = text.replace('&lt;', '<').replace('&gt;', '>')
    results = []
    for m in re.finditer(
        r'<\|tool_call_start\|>([\s\S]*?)<\|tool_call_end\|>',
        text
    ):
        raw = m.group(1).strip()
        if not raw: continue
        probe = raw.lstrip("[").lstrip()
        if probe and re.match(r'^\w+\s*\(', probe):
            calls = _parse_lfm2_pythonic(raw)
            calls = [c for c in calls if c["function"]["name"] in _KNOWN_TOOL_NAMES]
            if calls:
                results.extend(calls)
                continue
        try:
            parsed = json.loads(raw)
        except json.JSONDecodeError:
            continue
        if isinstance(parsed, list):
            for item in parsed:
                if isinstance(item, dict) and isinstance(item.get("name"), str):
                    results.append({
                        "function": {
                            "name":      item["name"],
                            "arguments": item.get("arguments", {}) if isinstance(item.get("arguments"), dict) else {}
                        }
                    })
        elif isinstance(parsed, dict) and isinstance(parsed.get("name"), str):
            results.append({
                "function": {
                    "name":      parsed["name"],
                    "arguments": parsed.get("arguments", {}) if isinstance(parsed.get("arguments"), dict) else {}
                }
            })
    return results

def _build_lfm2_tools_block(tools: list[dict]) -> str:
    schemas = []
    for t in tools:
        if t.get("type") == "function" and isinstance(t.get("function"), dict):
            schemas.append(t["function"])
        elif isinstance(t.get("name"), str):
            schemas.append(t)
    return json.dumps(schemas, ensure_ascii=False, indent=2)

