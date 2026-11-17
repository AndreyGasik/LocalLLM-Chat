# LLM-Chat-Common/core/tool_exec.py
#
# Единое исполнение вызовов инструментов для обоих бэкендов.
#
# Миксин ожидает у владельца:
#   • атрибуты: use_search (или search_enabled), enable_file_tools,
#     enable_memory_tools, enable_write_tools, enable_terminal_tool,
#     memory, memory_intent, scraper, num_results (алиас num_res),
#     default_time_range, _running;
#   • сигналы: tool_called(str, str), tool_result(str, str),
#     file_ready(str, str);
#   • метод _running() → bool (лямбда для мгновенного Stop терминала).
import json
from pathlib import Path

from core.file_writer import stage_markdown, convert_with_pandoc
from core.search import do_search


class ToolExecutorMixin:
    def _do_search(self, query: str, num_results: int, time_range: str):
        # Косвенный вызов через метод: тесты патчат do_search на уровне
        # модуля worker'а (monkeypatch.setattr(W, "do_search", fake)) —
        # подклассы переопределяют hook, читая модульную ссылку в момент
        # вызова.
        return do_search(query, num_results, time_range)

    def _tool_num_results(self, args):
        """База из UI с тихим fallback: слабые модели передают num_results
        мусором (строкой, float, dict) — int() раньше убивал весь раунд."""
        base = getattr(self, "num_results", None)
        if base is None:
            base = getattr(self, "num_res", 5)
        try:
            return int(args.get("num_results", base))
        except (TypeError, ValueError):
            return base

    def _exec_tool(self, name: str, args: dict, executed_calls: set) -> str:
        """Выполнить ОДИН вызов инструмента. Возвращает строку-результат
        для истории; сигналы tool_called/tool_result/file_ready выводятся
        здесь же (набор сигналов идентичен у обеих версий)."""
        if name in ("search", "scrape_url", "extract_links", "extract_metadata",
                    "search_page", "scrape_multiple") and not getattr(
                        self, "use_search", getattr(self, "search_enabled", False)):
            # Если кнопка поиска выключена, вызов, сгенерированный «по
            # инерции» из истории, не выполняется.
            self.tool_called.emit(name, "(заблокировано)")
            result = "Ошибка: поиск в интернете отключён пользователем."
            self.tool_result.emit("Поиск: доступ заблокирован", result)

        elif name == "write_text_file" and not self.enable_write_tools:
            self.tool_called.emit(name, "(заблокировано)")
            result = "Ошибка: создание файлов отключено пользователем."
            self.tool_result.emit("Запись файлов: доступ заблокирован", result)

        elif name == "search":
            query = str(args.get("query", "") or "")
            num_results = self._tool_num_results(args)
            time_range = str(args.get("time_range")
                             or getattr(self, "default_time_range", "none"))
            self.tool_called.emit(name, query)
            results = self._do_search(query, num_results, time_range)
            result = json.dumps(results, ensure_ascii=False)
            full_detail = json.dumps(results, ensure_ascii=False, indent=2)
            if results and "error" in results[0]:
                self.tool_result.emit(f"Ошибка поиска: {results[0]['error']}", full_detail)
            else:
                self.tool_result.emit(f"Найдено {len(results)} результатов", full_detail)

        elif name in ("scrape_url", "extract_links", "extract_metadata",
                      "search_page", "scrape_multiple"):
            if name == "scrape_multiple":
                urls = args.get("urls", [])
                self.tool_called.emit(name, ", ".join(str(u) for u in urls[:3]))
                result = self.scraper.call_tool(name, {"urls": urls})
                self.tool_result.emit(f"Обработано {len(urls)} страниц", result[:2000])
            elif name == "search_page":
                url = str(args.get("url", ""))
                query = str(args.get("query", ""))
                self.tool_called.emit(name, f"{url}: {query}")
                result = self.scraper.call_tool(name, {"url": url, "query": query})
                self.tool_result.emit(f"Найден текст ({len(result)} зн.)", result[:2000])
            else:
                url = str(args.get("url", ""))
                self.tool_called.emit(name, url)
                result = self.scraper.call_tool(name, {"url": url})
                summary = (
                    f"Извлечён текст ({len(result)} зн.)"
                    if name == "scrape_url" else "Операция выполнена"
                )
                self.tool_result.emit(summary, result[:2000])

        elif name in ("read_file", "read_pdf") and not self.enable_file_tools:
            # Модель могла сгенерировать READ_FILE:/READ_PDF: по инерции из
            # истории чата даже после выключения тумблера — инструмент
            # физически не выполняется.
            self.tool_called.emit(name, "(заблокировано)")
            result = "Ошибка: чтение файлов отключено пользователем."
            self.tool_result.emit("Файлы: доступ заблокирован", result)

        elif name == "read_file":
            path = str(args.get("path", ""))
            self.tool_called.emit(name, path)
            try:
                result = Path(path).read_text(encoding="utf-8", errors="ignore")
                self.tool_result.emit(f"Файл прочитан ({len(result)} зн.)", result[:2000])
            except Exception as e:
                result = f"Ошибка чтения файла: {e}"
                self.tool_result.emit("Ошибка чтения", result)

        elif name == "read_pdf":
            path = str(args.get("path", ""))
            self.tool_called.emit(name, path)
            try:
                import pypdf
                reader = pypdf.PdfReader(path)
                text = ""
                for page in reader.pages:
                    t = page.extract_text()
                    if t:
                        text += t + "\n"
                result = text if text.strip() else "PDF пуст или без извлекаемого текста."
                self.tool_result.emit(f"PDF прочитан ({len(result)} зн.)", result[:2000])
            except ImportError:
                result = "pypdf не установлен. Выполните: pip install pypdf"
                self.tool_result.emit("pypdf отсутствует", result)
            except Exception as e:
                result = f"Ошибка PDF: {e}"
                self.tool_result.emit("Ошибка PDF", result)

        elif name in ("memory_write", "memory_read", "memory_delete") and not (
                self.enable_memory_tools and self.memory_intent):
            # Блокируется в двух случаях: пользователь выключил кнопку
            # "Память", ЛИБО модель сама (по инерции из истории) сгенерировала
            # MEMORY_* без явной просьбы в сообщении пользователя.
            self.tool_called.emit(name, "(заблокировано)")
            result = (
                "Ошибка: операции с долговременной памятью либо отключены "
                "пользователем, либо доступны только когда пользователь явно "
                "попросил сохранить/прочитать/удалить что-то из памяти в своём "
                "сообщении."
            )
            self.tool_result.emit("Память: доступ заблокирован", result)

        elif name in ("memory_write", "memory_read", "memory_delete") and not self.memory:
            result = "Ошибка: база памяти не инициализирована."
            self.tool_result.emit("Память недоступна", result)

        elif name == "memory_write":
            cat = args.get("category", "note")
            key = str(args.get("key", ""))
            value = str(args.get("value", ""))
            self.tool_called.emit("memory_write", f"[{cat}] {key}")
            result = self.memory.write(cat, key, value)
            self.tool_result.emit(result, result)

        elif name == "memory_read":
            cat = args.get("category") or None
            key = args.get("key") or None
            self.tool_called.emit("memory_read", f"{cat or '*'} / {key or '*'}")
            rows = self.memory.read(cat, key)
            if rows:
                result = json.dumps(rows, ensure_ascii=False, indent=2)
                self.tool_result.emit(f"Прочитано {len(rows)} записей", result)
            else:
                result = "Память пуста или записи не найдены."
                self.tool_result.emit("Записей не найдено", result)

        elif name == "memory_delete":
            cat = args.get("category", "")
            key = str(args.get("key", ""))
            self.tool_called.emit("memory_delete", f"[{cat}] {key}")
            result = self.memory.delete(cat, key)
            self.tool_result.emit(result, result)

        elif name == "execute_terminal_command" and not self.enable_terminal_tool:
            # Вызов «по инерции» из истории после выключения тумблера.
            self.tool_called.emit(name, "(заблокировано)")
            result = "Ошибка: выполнение команд в терминале отключено пользователем."
            self.tool_result.emit("Терминал: доступ заблокирован", result)

        elif name == "execute_terminal_command":
            from core.terminal import _execute_command_safe
            command = args.get("command", "")
            if not isinstance(command, str):
                # Слабые модели передают command мусором (dict/list) —
                # str(dict) в shell выполнять нельзя.
                command = None
            if not command or not command.strip():
                self.tool_called.emit(name, "(пустая команда)")
                result = "Ошибка: аргумент 'command' пуст или не является строкой."
                self.tool_result.emit("Терминал: неверный аргумент", result)
            else:
                # timeout может прийти строкой/мусором — как query у search.
                try:
                    timeout = int(float(args.get("timeout") or 30))
                except (TypeError, ValueError):
                    timeout = 30
                self.tool_called.emit(
                    name, command.replace("\n", " ").strip()[:120])
                result = _execute_command_safe(
                    command, timeout,
                    is_running=lambda: self._running,
                )
                ok = result.startswith("Код возврата: 0")
                self.tool_result.emit(
                    "Терминал: выполнено" if ok
                    else "Терминал: ошибка выполнения",
                    result[:2000])

        elif name == "write_text_file":
            suggested_name = str(args.get("suggested_name", "документ.md"))
            content = args.get("content", "")
            target_format = args.get("target_format", "md")
            self.tool_called.emit(name, suggested_name)
            try:
                md_path = stage_markdown(suggested_name, content)
                final_path = md_path
                if target_format in ("docx", "pdf"):
                    converted = convert_with_pandoc(md_path, f".{target_format}")
                    if converted:
                        final_path = converted
                        result = f"Черновик сохранён: {final_path.name}"
                    else:
                        result = (
                            f"Черновик сохранён как {md_path.name} "
                            f"(конвертация в {target_format} недоступна — "
                            f"не найден pandoc, оставлен markdown)"
                        )
                else:
                    result = f"Черновик сохранён: {final_path.name}"
                self.tool_result.emit(result, str(final_path))
                self.file_ready.emit(str(final_path), str(target_format))
            except Exception as e:
                result = f"Ошибка сохранения черновика: {e}"
                self.tool_result.emit("Ошибка сохранения", result)

        else:
            result = f"Инструмент {name} не поддерживается."

        return result
