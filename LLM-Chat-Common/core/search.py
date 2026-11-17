# core/search.py
import json
from bs4 import BeautifulSoup
from http_client import _HTTP, _NO_PROXY
from config import SEARXNG_URL

_DDG_LITE_URL = "https://lite.duckduckgo.com/lite/"
_DDG_HEADERS  = {"User-Agent": "Mozilla/5.0 (X11; Linux x86_64) LLM-Chat/1.0"}


def _do_search_searxng(query: str, num_results: int, time_range: str) -> list[dict]:
    data_form = {"q": query, "format": "json", "pageno": 1}
    if time_range and time_range != "none":
        data_form["time_range"] = time_range
    headers = {"User-Agent": "Mozilla/5.0 (X11; Linux x86_64) LLM-Chat/1.0"}
    resp = _HTTP.post(SEARXNG_URL, data=data_form, headers=headers, timeout=30, proxies=_NO_PROXY)
    resp.raise_for_status()
    try:
        data = resp.json()
    except json.JSONDecodeError:
        raise ValueError("SearXNG вернул некорректный ответ")
    results = []
    for r in data.get("results", [])[:num_results]:
        results.append({
            "title":   r.get("title", ""),
            "url":     r.get("url", ""),
            "snippet": r.get("content", "")
        })
    return results


def _do_search_duckduckgo(query: str, num_results: int) -> list[dict]:
    # Резервный путь на случай недоступности self-hosted SearXNG. Тот же
    # способ запроса (_HTTP/_NO_PROXY), что и основной, чтобы не потерять
    # обход системного прокси, который используется для SearXNG.
    # DuckDuckGo Lite -- не API, а обычная HTML-страница, поэтому парсинг
    # завязан на её текущую вёрстку и может сломаться, если DDG её изменит;
    # это ожидаемая цена резервного пути, а не повод не пробовать вовсе.
    # time_range сюда не передаётся -- Lite не поддерживает фильтр по
    # свежести так же, как SearXNG, и это только подстраховка, а не замена.
    resp = _HTTP.post(_DDG_LITE_URL, data={"q": query}, headers=_DDG_HEADERS, timeout=20, proxies=_NO_PROXY)
    resp.raise_for_status()
    soup = BeautifulSoup(resp.text, "html.parser")
    results = []
    for link in soup.select("a.result-link"):
        url = link.get("href", "")
        if not url:
            continue
        snippet = ""
        row = link.find_parent("tr")
        snippet_row = row.find_next_sibling("tr") if row else None
        if snippet_row:
            snippet_td = snippet_row.find("td", class_="result-snippet")
            if snippet_td:
                snippet = snippet_td.get_text(strip=True)
        results.append({
            "title":   link.get_text(strip=True),
            "url":     url,
            "snippet": snippet,
        })
        if len(results) >= num_results:
            break
    return results


def do_search(query: str, num_results: int = 10, time_range: str = "none") -> list[dict]:
    # Нормализация аргументов: модель,
    # особенно «обрезанные»/слабые кванты, передаёт запрос с лишними
    # переводами строк, повторными пробелами или огромной длины — SearXNG
    # и DuckDuckGo на таком мусоре либо ищут хуже, либо возвращают шум
    # («странные результаты»). Нормализуем пробелы и ограничиваем длину,
    # num_results зажимаем в допустимый диапазон, time_range проверяем по
    # белому списку, чтобы кривой аргумент из tool-call не испортил
    # поисковый путь (единственное исключение сюда не падает: do_search
    # ловит всё, но шумный результат лучше предупреждать заранее).
    query = " ".join(str(query).split())[:300]
    try:
        num_results = max(1, min(int(num_results), 10))
    except (TypeError, ValueError):
        num_results = 5
    if not isinstance(time_range, str) or time_range not in ("none", "day", "week", "month", "year"):
        time_range = "none"
    try:
        results = _do_search_searxng(query, num_results, time_range)
        if results:
            return results
        searxng_error = "результатов не найдено"
    except Exception as e:
        searxng_error = str(e)

    # SearXNG упал по исключению или честно ничего не нашёл -- пробуем
    # DuckDuckGo Lite. Вызывается ТОЛЬКО здесь, при живом SearXNG этот
    # код не выполняется вообще.
    try:
        ddg_results = _do_search_duckduckgo(query, num_results)
        if ddg_results:
            return ddg_results
        return [{"error": f"SearXNG: {searxng_error}; DuckDuckGo: результатов не найдено"}]
    except Exception as e:
        return [{"error": f"SearXNG: {searxng_error}; DuckDuckGo: {e}"}]
