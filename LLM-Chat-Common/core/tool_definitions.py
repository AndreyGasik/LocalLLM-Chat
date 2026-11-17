# core/tool_definitions.py

SEARCH_TOOL = {
    "type": "function",
    "function": {
        "name": "search",
        "description": (
            "Поиск актуальной информации в интернете через SearXNG. "
            "Используй когда нужны свежие данные, новости, факты которых нет в обучающих данных."
        ),
        "parameters": {
            "type": "object",
            "properties": {
                "query":       {"type": "string",  "description": "Поисковый запрос"},
                "num_results": {"type": "integer", "description": "Количество результатов (1–10)"},
                "time_range":  {
                    "type": "string",
                    "enum": ["none", "day", "week", "month", "year"],
                    "description": "Фильтр по времени. По умолчанию 'none' (без фильтра). Для самых свежих новостей используй 'day' или 'week'."
                }
            },
            "required": ["query"]
        }
    }
}

FETCH_TOOLS = [
    {
        "type": "function",
        "function": {
            "name": "scrape_url",
            "description": (
                "Загружает страницу и возвращает её читаемый текст ВМЕСТЕ со списком ссылок. "
                "Используй для чтения статей или главной страницы сайта."
            ),
            "parameters": {
                "type": "object",
                "properties": {"url": {"type": "string", "description": "Полный URL (с https://)"}},
                "required": ["url"]
            }
        }
    },
    {
        "type": "function",
        "function": {
            "name": "extract_links",
            "description": "Возвращает все ссылки страницы [{text, url}].",
            "parameters": {
                "type": "object",
                "properties": {"url": {"type": "string"}},
                "required": ["url"]
            }
        }
    },
    {
        "type": "function",
        "function": {
            "name": "extract_metadata",
            "description": "Извлекает метаданные страницы: title, description, og-теги.",
            "parameters": {
                "type": "object",
                "properties": {"url": {"type": "string"}},
                "required": ["url"]
            }
        }
    },
    {
        "type": "function",
        "function": {
            "name": "search_page",
            "description": "Ищет строку/фразу в тексте страницы и возвращает совпадения.",
            "parameters": {
                "type": "object",
                "properties": {
                    "url":   {"type": "string"},
                    "query": {"type": "string"}
                },
                "required": ["url", "query"]
            }
        }
    },
    {
        "type": "function",
        "function": {
            "name": "scrape_multiple",
            "description": "Загружает 2–5 страниц одновременно. Максимум 5 URL.",
            "parameters": {
                "type": "object",
                "properties": {
                    "urls": {
                        "type": "array",
                        "items": {"type": "string"},
                        "description": "Список URL (максимум 5)"
                    }
                },
                "required": ["urls"]
            }
        }
    }
]

FILE_TOOLS = [
    {
        "type": "function",
        "function": {
            "name": "read_file",
            "description": "Прочитать содержимое локального текстового файла.",
            "parameters": {
                "type": "object",
                "properties": {"path": {"type": "string", "description": "Абсолютный путь к файлу"}},
                "required": ["path"]
            }
        }
    },
    {
        "type": "function",
        "function": {
            "name": "read_pdf",
            "description": "Извлечь текст из локального PDF.",
            "parameters": {
                "type": "object",
                "properties": {"path": {"type": "string", "description": "Абсолютный путь к PDF"}},
                "required": ["path"]
            }
        }
    },
]

# Инструменты долговременной памяти вынесены отдельно от FILE_TOOLS: они
# добавляются в список доступных модели инструментов, только когда в текущем
# сообщении пользователя явно распознано намерение работать с памятью
# (см. _wants_memory_tool в core/memory_db.py). Без этого намерения модель
# их вообще не видит — не раздуваем промпт тремя лишними схемами.
MEMORY_WRITE_TOOL = {
    "type": "function",
    "function": {
        "name": "memory_write",
        "description": (
            "Сохранить факт, предпочтение или заметку в долговременную память. "
            "Категории: preference, correction, personal, workflow, note. "
            "Используй, только если пользователь явно попросил что-то запомнить."
        ),
        "parameters": {
            "type": "object",
            "properties": {
                "category": {
                    "type": "string",
                    "enum": ["preference", "correction", "personal", "workflow", "note"]
                },
                "key":   {"type": "string"},
                "value": {"type": "string"}
            },
            "required": ["category", "key", "value"]
        }
    }
}

MEMORY_READ_TOOL = {
    "type": "function",
    "function": {
        "name": "memory_read",
        "description": (
            "Прочитать долговременную память. Оставь поля пустыми для чтения всей памяти. "
            "Используй, только если пользователь явно попросил прочитать/вспомнить что-то из памяти."
        ),
        "parameters": {
            "type": "object",
            "properties": {
                "category": {"type": "string"},
                "key":      {"type": "string"}
            },
            "required": []
        }
    }
}

MEMORY_DELETE_TOOL = {
    "type": "function",
    "function": {
        "name": "memory_delete",
        "description": (
            "Удалить запись из долговременной памяти. "
            "Используй, только если пользователь явно попросил удалить что-то из памяти."
        ),
        "parameters": {
            "type": "object",
            "properties": {
                "category": {"type": "string"},
                "key":      {"type": "string"}
            },
            "required": ["category", "key"]
        }
    }
}

# Инструмент терминала подключается отдельным тумблером «Терминал» в сайдбаре
# (enable_terminal_tool у Worker). Команда выполняется реально, от имени
# пользователя, в bash; опасные команды блокируются deny-листом в
# core/worker.py::_TERMINAL_DENY_RE — но это не песочница, поэтому в
# описании сразу задаём модели безопасную манеру работы.
TERMINAL_TOOL = {
    "type": "function",
    "function": {
        "name": "execute_terminal_command",
        "description": (
            "Выполняет ОДНУ команду (или пайплайн) bash в системе пользователя "
            "(CachyOS, Arch-based) и возвращает код возврата, stdout и stderr. "
            "Используй для системных задач: просмотр файлов и железа, процессы, "
            "службы, сеть, диски, запуск и проверка кода "
            "(python script.py, node app.js, bash test.sh), сборка и тесты. "
            "НЕ используй интерактивные полноэкранные программы: вместо htop — "
            "'ps aux' или 'top -bn1', journalctl — только с --no-pager. "
            "Текущие дату и время узнавай командой 'date' — не бери их из вывода "
            "uname. Для размеров каталогов используй "
            "'du -h --max-depth=1 ПУТЬ | sort -rh | head' (флаг -s несовместим "
            "с --max-depth и даёт только итоговую строку). "
            "НЕ используй sudo — он заблокирован. Деструктивные команды "
            "(rm -rf по системным путям и маскам, mkfs/dd по устройствам, "
            "shutdown/reboot и т.п.) блокируются. Длинный вывод обрезается; "
            "не повторяй ту же команду повторно."
        ),
        "parameters": {
            "type": "object",
            "properties": {
                "command": {
                    "type": "string",
                    "description": (
                        "Команда для выполнения, например 'ls -la ~/'. "
                        "Несколько действий соединяй через && или ; в одной строке."
                    )
                },
                "timeout": {
                    "type": "integer",
                    "description": (
                        "Лимит времени в секундах, 5–300. По умолчанию 30. "
                        "Увеличивай (до 300) для медленных команд вроде сборки."
                    )
                }
            },
            "required": ["command"]
        }
    }
}

_KNOWN_TOOL_NAMES = {
    "search", "scrape_url", "extract_links",
    "extract_metadata", "search_page", "scrape_multiple",
    "read_file", "read_pdf",
    "memory_write", "memory_read", "memory_delete",
    "write_text_file",  # фича из эталона (core/write_tool_definitions.py), добавлена на шаге 6.1
    # Терминал: имя должно совпадать с _KNOWN_TOOL_NAMES в общем модуле
    # LLM-Chat-Common/tool_parsing.py — иначе фильтр «name in _KNOWN_TOOL_NAMES»
    # в core/worker.py молча выкинул бы вызов execute_terminal_command,
    # распарсенный общим модулем (рассинхрон проектов на общей папке).
    "execute_terminal_command",
}
