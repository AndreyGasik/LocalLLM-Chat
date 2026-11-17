# Портативная сборка (Portable binary)

[English below](#portable-binary-english)

## Русский

Помимо запуска из исходников, проект распространяется как **один исполняемый файл** `llm-chat` — то же приложение, но без Python, без зависимостей и без репозитория. Файл можно взять в [Releases](../../releases) и положить куда угодно.

### Первый запуск

При первом запуске рядом с файлом создаётся папка `data/` — в ней хранятся история чатов, память, настройки и лог сервера. Переносите бинарник вместе с `data/`, если нужно перевезти и чаты.

```
somewhere/
├── llm-chat        # бинарник
└── data/           # появляется после первого запуска
```

### Что нужно на системе

Всё тяжёлое уже внутри файла (включая PyQt6). Из системы берутся только стандартные вещи:

- графическая среда X11 или Wayland, шрифты, OpenSSL;
- `llama-server` — если пользуетесь бэкендом llama.cpp (путь к нему выбирается в интерфейсе: «Модель и Сервер» → папка сервера);
- `Ollama` — если пользуетесь этим бэкендом;
- SearXNG — для веб-поиска (необязательно).

### Совместимость

Бинарник собран в контейнере с glibc 2.28, поэтому работает на большинстве современных дистрибутивов: Ubuntu 20.04+, Debian 10+, Fedora 30+, Mint 20+, openSUSE Leap 15.2+, Arch/CachyOS. Размер ~59 МБ.

---

## Portable binary (English)

Besides running from source, the project ships as a **single executable** `llm-chat` — the same application, but without Python, dependencies, or the repository. Grab it from [Releases](../../releases) and put it anywhere.

### First run

On first launch a `data/` folder appears next to the file — chats, memory, settings and the server log live there. Move the binary together with `data/` to carry the chats along.

### What it needs from the system

Everything heavy is inside the file (PyQt6 included). Only standard things come from the system: X11/Wayland, fonts, OpenSSL; `llama-server` (for the llama.cpp backend — path is picked in the UI), `Ollama` for that backend, and optionally SearXNG for web search.

### Compatibility

Built against glibc 2.28, so it runs on most current distros: Ubuntu 20.04+, Debian 10+, Fedora 30+, Mint 20+, openSUSE Leap 15.2+, Arch/CachyOS. Size ~59 MB.
