# LLM-Chat-Common/core/api_messages.py
#
# Единая сборка сообщений для API обеих версий чата (Ollama и llama.cpp).
# Формат результата инструмента — ЕДИНСТВЕННОЕ различие бэкендов:
#   • Ollama понимает нативные tool-сообщения (native_tool_messages=True);
#   • llama.cpp в текстовом режиме — user-сообщение с заголовком
#     «[Результат <имя_инструмента>]: …» (модель учат этому формату в
#     инструкции инструментов, см. _build_text_tools_instruction).
from pathlib import Path


def _build_api_messages(history: list[dict], ctx_limit: int,
                        sys_content: str, read_files_directly: bool = False,
                        native_tool_messages: bool = False) -> list[dict]:
    msgs = [{"role": "system", "content": sys_content}]
    for m in history[-ctx_limit:]:
        role    = m.get("role", "user")
        content = m.get("content", "")
        files   = m.get("files", [])
        if files and role == "user":
            parts = []
            if content:
                parts.append(content)
            for f in files:
                ext = Path(f).suffix.lower()
                if read_files_directly:
                    try:
                        if ext == ".pdf":
                            try:
                                import pypdf
                                reader = pypdf.PdfReader(f)
                                pdf_text = "\n".join(page.extract_text() or "" for page in reader.pages)
                                parts.append(f"--- Содержимое PDF {f} ---\n{pdf_text}")
                            except ImportError:
                                parts.append(f"Ошибка: pypdf не установлен для чтения {f}")
                            except Exception as e:
                                parts.append(f"Ошибка чтения PDF {f}: {e}")
                        else:
                            file_text = Path(f).read_text(encoding="utf-8", errors="ignore")
                            parts.append(f"--- Содержимое файла {f} ---\n{file_text}")
                    except Exception as e:
                        parts.append(f"Ошибка чтения файла {f}: {e}")
                else:
                    if ext == ".pdf":
                        parts.append(f"Прочитай PDF файл и проанализируй: {f}")
                    else:
                        parts.append(f"Прочитай текстовый файл и проанализируй: {f}")
            content = "\n".join(parts)

        if role == "tool":
            if native_tool_messages:
                msg = {"role": "tool", "content": content}
                if "name" in m:
                    msg["name"] = m["name"]
                msgs.append(msg)
            else:
                tool_name = m.get("name", "инструмент")
                msgs.append({"role": "user",
                             "content": f"[Результат {tool_name}]:\n{content}"})
        elif role == "assistant" and "tool_calls" in m:
            msgs.append({"role": "assistant", "content": content, "tool_calls": m["tool_calls"]})
        else:
            msgs.append({"role": role, "content": content})
    return msgs
