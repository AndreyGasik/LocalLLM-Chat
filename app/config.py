# app/config.py — единая конфигурация приложения с двумя бэкендами.
# Данные — в ОДНОЙ папке repo_root/data (общая память и история чатов для
# обоих бэкендов).
from pathlib import Path

BASE_DIR = Path(__file__).resolve().parent.parent   # repo root
DATA_DIR = BASE_DIR / "data"
DATA_DIR.mkdir(parents=True, exist_ok=True)

HISTORY_FILE  = DATA_DIR / "history.json"
MEMORY_FILE   = DATA_DIR / "memory.db"
CHAT_HISTORY_DIR = DATA_DIR / "chats"
CHAT_INDEX_FILE  = CHAT_HISTORY_DIR / "index.json"
GENERATED_FILES_DIR = DATA_DIR / "output"

OLLAMA_API  = "http://localhost:11434/api/chat"
OLLAMA_TAGS = "http://localhost:11434/api/tags"
SEARXNG_URL = "http://localhost:8080/search"

MAX_TOOL_ITER = 5
MAX_LOOP_ITER = 4
MAX_TITLE_LEN = 40
DEFAULT_CHAT_TITLE = "Новый чат"

# ── llama.cpp ──
# Путь к llama-server выбирается в UI («Модель и Сервер» → папка сервера,
# бинарник всегда <папка>/bin/llama-server); дефолтного пути нет.
DEFAULT_SERVER_PORT = 8089
DEFAULT_SERVER_THREADS = 4
DEFAULT_SERVER_NGL = 99
DEFAULT_SERVER_NP = 1
DEFAULT_CTX = 8192
DEFAULT_MTP_DRAFT_N = 2
SIDEBAR_WIDTH = 340
