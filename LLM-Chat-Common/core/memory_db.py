# core/memory_db.py
import sqlite3
from pathlib import Path
from datetime import datetime
from config import MEMORY_FILE

class MemoryDB:
    CATEGORIES = ("preference", "correction", "personal", "workflow", "note")

    def __init__(self, path: Path = MEMORY_FILE):
        self.path = path
        self._init_db()

    def _conn(self):
        return sqlite3.connect(str(self.path))

    def _init_db(self):
        with self._conn() as con:
            con.execute("""
                CREATE TABLE IF NOT EXISTS memory (
                    id        INTEGER PRIMARY KEY AUTOINCREMENT,
                    category  TEXT    NOT NULL,
                    key       TEXT    NOT NULL,
                    value     TEXT    NOT NULL,
                    created   TEXT    NOT NULL,
                    updated   TEXT    NOT NULL,
                    UNIQUE(category, key)
                )
            """)
            con.execute("CREATE INDEX IF NOT EXISTS idx_cat ON memory(category)")

    def write(self, category: str, key: str, value: str) -> str:
        if category not in self.CATEGORIES:
            return f"Ошибка: категория '{category}' неизвестна. Допустимые: {', '.join(self.CATEGORIES)}"
        now = datetime.now().isoformat(timespec="seconds")
        con = self._conn()
        try:
            with con:
                con.execute("""
                    INSERT INTO memory (category, key, value, created, updated)
                    VALUES (?, ?, ?, ?, ?)
                    ON CONFLICT(category, key)
                    DO UPDATE SET value=excluded.value, updated=excluded.updated
                """, (category, key, value, now, now))
        finally:
            con.close()
        return f"✓ Сохранено [{category}] {key}"

    def read(self, category: str | None = None, key: str | None = None) -> list[dict]:
        con = self._conn()
        try:
            with con:
                if category and key:
                    rows = con.execute(
                        "SELECT category, key, value, updated FROM memory WHERE category=? AND key=?",
                        (category, key)
                    ).fetchall()
                elif category:
                    rows = con.execute(
                        "SELECT category, key, value, updated FROM memory WHERE category=? ORDER BY updated DESC",
                        (category,)
                    ).fetchall()
                elif key:
                    rows = con.execute(
                        "SELECT category, key, value, updated FROM memory WHERE key LIKE ? ORDER BY updated DESC",
                        (f"%{key}%",)
                    ).fetchall()
                else:
                    rows = con.execute(
                        "SELECT category, key, value, updated FROM memory ORDER BY category, updated DESC"
                    ).fetchall()
        finally:
            con.close()
        return [{"category": r[0], "key": r[1], "value": r[2], "updated": r[3]} for r in rows]

    def delete(self, category: str, key: str) -> str:
        con = self._conn()
        try:
            with con:
                n = con.execute(
                    "DELETE FROM memory WHERE category=? AND key=?", (category, key)
                ).rowcount
        finally:
            con.close()
        return f"✓ Удалено {n} запись" if n else "Запись не найдена"


# Инструменты долговременной памяти (MEMORY_WRITE/MEMORY_READ/MEMORY_DELETE)
# описываются модели и разрешены к исполнению только тогда, когда в ТЕКУЩЕМ
# сообщении пользователя явно есть намерение поработать с памятью — иначе
# модель вообще не узнаёт, что такая возможность существует в этом раунде.
_MEMORY_INTENT_KEYWORDS = (
    "запомни", "запиши в память", "сохрани в память", "сохрани это в память",
    "занеси в память", "положи в память", "в базу памяти", "в базе памяти",
    "из базы памяти", "из памяти", "что ты помнишь", "что в памяти",
    "прочти память", "прочитай память", "прочти из базы", "прочитай из базы",
    "вспомни", "удали из памяти", "очисти память", "стёр из памяти",
    "remember this", "save to memory", "recall from memory",
    "what do you remember", "read from memory", "clear memory",
)


def _wants_memory_tool(text: str) -> bool:
    """True, только если пользователь явно просит сохранить/прочитать/
    удалить что-то из долговременной памяти в этом конкретном сообщении."""
    if not text:
        return False
    t = text.lower()
    return any(kw in t for kw in _MEMORY_INTENT_KEYWORDS)
