# core/write_tool_definitions.py
WRITE_TOOLS = [
    {
        "type": "function",
        "function": {
            "name": "write_text_file",
            "description": (
                "Сохраняет ПОЛНОЕ новое/исправленное содержимое документа как "
                "отдельный черновик. НИКОГДА не перезаписывает оригинал — "
                "черновик сохраняется отдельно, а пользователь сам решает через "
                "кнопку «Сохранить как», переносить ли его поверх исходного файла. "
                "Используй, когда просят исправить пунктуацию/орфографию, "
                "сократить, составить справку/саммари и т.п. и отдать результат "
                "готовым файлом, а не текстом в чате. Всегда передавай content "
                "ЦЕЛИКОМ — весь документ, даже если правка касалась одной фразы."
            ),
            "parameters": {
                "type": "object",
                "properties": {
                    "suggested_name": {
                        "type": "string",
                        "description": "Короткое желаемое имя файла БЕЗ пути, например 'справка.md' или 'документ_испр.md'"
                    },
                    "content": {
                        "type": "string",
                        "description": "Полный новый текст документа целиком (markdown/plain text)"
                    },
                    "target_format": {
                        "type": "string",
                        "enum": ["md", "docx", "pdf"],
                        "description": "В каком виде документ в итоге нужен пользователю"
                    }
                },
                "required": ["suggested_name", "content", "target_format"]
            }
        }
    }
]

WRITE_TOOL_NAMES = {"write_text_file"}
