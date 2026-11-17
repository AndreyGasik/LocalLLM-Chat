# core/scraper.py
import re
import json
from urllib.parse import urljoin
from bs4 import BeautifulSoup
from http_client import _HTTP

_ALLOWED_URL_SCHEMES = ("http://", "https://")


class MCPScraper:
    _HEADERS = {
        "User-Agent": (
            "Mozilla/5.0 (X11; Linux x86_64) "
            "AppleWebKit/537.36 (KHTML, like Gecko) "
            "Chrome/124.0.0.0 Safari/537.36"
        ),
        "Accept":          "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
        "Accept-Language": "ru,en;q=0.9",
    }

    @staticmethod
    def _sanitize_url(url: str) -> str:
        """Убирает артефакты markdown/форматирования, которые модель иногда
        оставляет вокруг URL при текстовом (не-нативном) вызове инструмента,
        например: `https://example.com` )* -> https://example.com
        (приводит к 404 из-за %60%29%2A и т.п. в конце адреса)."""
        if not url:
            return url
        u = url.strip()
        # убрать обрамляющие кавычки/скобки/бэктики целиком, если строка в них обёрнута
        u = u.strip('`*_<>"\'()[]')
        # обрезать хвостовой мусор форматирования, который остаётся после strip()
        # из-за незакрытых/лишних символов (`, *, ), ], >, ", ', ., , и пробелы)
        u = re.sub(r'[`*_)\]>"\'.,;]+$', '', u).strip()
        # исправить схему с одним слэшем ("https:/example.com" -> "https://example.com"),
        # которую модель иногда выдаёт при генерации нескольких URL подряд
        u = re.sub(r'^(https?):/(?!/)', r'\1://', u, flags=re.IGNORECASE)
        # Схема проверяется здесь же, одной точкой на все 5 инструментов
        # (все они прогоняют url через _sanitize_url в call_tool) — без
        # этого модель могла бы передать file:// или другую нестандартную
        # схему, и запрос ушёл бы в requests.get() как есть.
        if u and not u.lower().startswith(_ALLOWED_URL_SCHEMES):
            raise ValueError(f"Недопустимая схема адреса: {u!r}")
        return u

    def call_tool(self, name: str, arguments: dict, timeout: int = 30) -> str:
        try:
            if   name == "scrape_url":       return self._scrape_url(self._sanitize_url(arguments.get("url", "")), timeout)
            elif name == "extract_links":    return self._extract_links(self._sanitize_url(arguments.get("url", "")), timeout)
            elif name == "extract_metadata": return self._extract_metadata(self._sanitize_url(arguments.get("url", "")), timeout)
            elif name == "search_page":      return self._search_page(self._sanitize_url(arguments.get("url", "")), arguments.get("query", ""), timeout)
            elif name == "scrape_multiple":  return self._scrape_multiple([self._sanitize_url(u) for u in arguments.get("urls", [])], timeout)
            else:                            return f"Инструмент {name} не поддерживается"
        except Exception as e:
            return f"Ошибка скрапера [{name}]: {e}"

    def _fetch(self, url: str, timeout: int):
        resp = _HTTP.get(url, headers=self._HEADERS, timeout=timeout, allow_redirects=True)
        resp.raise_for_status()
        enc  = resp.encoding or resp.apparent_encoding or "utf-8"
        html = resp.content.decode(enc, errors="ignore")
        return BeautifulSoup(html, "html.parser"), str(resp.url)

    @staticmethod
    def _clean(soup) -> str:
        for tag in soup(["script", "style", "nav", "footer", "header",
                         "aside", "form", "noscript", "iframe"]):
            tag.decompose()
        lines = [l.strip() for l in soup.get_text(separator="\n").splitlines() if l.strip()]
        return "\n".join(lines)

    def _scrape_url(self, url: str, timeout: int) -> str:
        if not url:
            return "Ошибка: не указан URL"
        soup, final_url = self._fetch(url, timeout)
        article_links, seen = [], set()
        for a in soup.find_all("a", href=True):
            href = a["href"].strip()
            if not href or href.startswith(("#", "javascript", "mailto", "tel")):
                continue
            abs_href = href if href.startswith("http") else urljoin(final_url, href)
            text = a.get_text(strip=True)
            if text and len(text) > 10 and abs_href not in seen:
                seen.add(abs_href)
                article_links.append(f"  [{text[:80]}]({abs_href})")
        text = self._clean(soup)
        if len(text) > 8000:
            text = text[:8000] + "\n… (текст обрезан)"
        if article_links:
            limit = 20 if len(text) > 6000 else 40
            text += "\n\n--- Ссылки на странице ---\n" + "\n".join(article_links[:limit])
        return text or "Не удалось извлечь текст"

    def _extract_links(self, url: str, timeout: int) -> str:
        if not url:
            return "Ошибка: не указан URL"
        soup, final_url = self._fetch(url, timeout)
        links, seen = [], set()
        for a in soup.find_all("a", href=True):
            href = a["href"].strip()
            if not href or href.startswith(("#", "javascript", "mailto", "tel")):
                continue
            abs_href = href if href.startswith("http") else urljoin(final_url, href)
            if abs_href in seen:
                continue
            seen.add(abs_href)
            links.append({"text": a.get_text(strip=True)[:80], "url": abs_href})
        return json.dumps(links[:60], ensure_ascii=False, indent=2) if links else "Ссылок не найдено"

    def _extract_metadata(self, url: str, timeout: int) -> str:
        if not url:
            return "Ошибка: не указан URL"
        soup, _ = self._fetch(url, timeout)
        meta = {"title": "", "description": "", "og_title": "", "og_image": "", "og_url": ""}
        if soup.title and soup.title.string:
            meta["title"] = soup.title.string.strip()
        for tag in soup.find_all("meta"):
            n = (tag.get("name")     or "").lower()
            p = (tag.get("property") or "").lower()
            c =  tag.get("content")  or ""
            if   n == "description": meta["description"] = c
            elif p == "og:title":    meta["og_title"]    = c
            elif p == "og:image":    meta["og_image"]    = c
            elif p == "og:url":      meta["og_url"]      = c
        return json.dumps(meta, ensure_ascii=False, indent=2)

    def _search_page(self, url: str, query: str, timeout: int) -> str:
        if not url:
            return "Ошибка: не указан URL"
        soup, _ = self._fetch(url, timeout)
        text  = self._clean(soup)
        q     = query.lower()
        lines = [l for l in text.splitlines() if q in l.lower()]
        return "\n".join(lines[:40]) if lines else "Совпадений не найдено."

    def _scrape_multiple(self, urls: list, timeout: int) -> str:
        results = []
        for u in urls[:5]:
            try:
                soup, final_url = self._fetch(u, timeout)
                results.append({"url": final_url, "text": self._clean(soup)[:3000]})
            except Exception as e:
                results.append({"url": u, "error": str(e)})
        return json.dumps(results, ensure_ascii=False, indent=2)

    def close(self):
        pass
