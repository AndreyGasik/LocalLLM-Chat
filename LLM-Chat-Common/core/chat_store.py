# core/chat_store.py
import json
from pathlib import Path
from datetime import datetime

from config import CHAT_HISTORY_DIR, CHAT_INDEX_FILE

class ChatStore:

    @staticmethod
    def _path(chat_id: str) -> Path:
        CHAT_HISTORY_DIR.mkdir(parents=True, exist_ok=True)
        return CHAT_HISTORY_DIR / f"{chat_id}.json"

    @staticmethod
    def new_id() -> str:
        return datetime.now().strftime("%Y%m%d-%H%M%S-%f")

    @staticmethod
    def load_index() -> list:
        if CHAT_INDEX_FILE.exists():
            try:
                data = json.loads(CHAT_INDEX_FILE.read_text(encoding="utf-8"))
                return data.get("chats", [])
            except Exception:
                pass
        return []

    @staticmethod
    def save_index(chats: list):
        try:
            CHAT_HISTORY_DIR.mkdir(parents=True, exist_ok=True)
            CHAT_INDEX_FILE.write_text(
                json.dumps({"chats": chats}, ensure_ascii=False, indent=2),
                encoding="utf-8"
            )
        except Exception:
            pass

    @staticmethod
    def load_chat(chat_id: str) -> dict:
        try:
            return json.loads(ChatStore._path(chat_id).read_text(encoding="utf-8"))
        except Exception:
            return {}

    @staticmethod
    def save_chat(chat_id: str, data: dict):
        try:
            ChatStore._path(chat_id).write_text(
                json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8"
            )
        except Exception:
            pass

    @staticmethod
    def delete_chat(chat_id: str):
        try:
            p = ChatStore._path(chat_id)
            if p.exists():
                p.unlink()
        except Exception:
            pass
