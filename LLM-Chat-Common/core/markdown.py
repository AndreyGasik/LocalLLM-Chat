# core/markdown.py
import re
try:
    from pygments import lex
    from pygments.lexers import get_lexer_by_name, TextLexer
    PYGMENTS_OK = True
except ImportError:
    PYGMENTS_OK = False


def _escape(text: str) -> str:
    return text.replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;")


_RE_CODEBLOCK   = re.compile(r'```(\w*)\s*\n([\s\S]*?)```')
_RE_INLINE_CODE = re.compile(r'`([^`\n]+)`')
_RE_BLOCK_SPLIT = re.compile(r'\n{2,}')
_RE_CB_PLACEHOLDER = re.compile(r'^\x00CB(\d+)\x00$')
_RE_HR          = re.compile(r'^(\-{3,}|\*{3,}|_{3,})$')
_RE_HEADING     = re.compile(r'^(#{1,6})\s+(.+)$')
_RE_UL_LINE     = re.compile(r'^[\-\*\+]\s+', re.MULTILINE)
_RE_UL_HR       = re.compile(r'^(\-{3,}|\*{3,})$')
_RE_UL_ITEMS    = re.compile(r'^[\-\*\+]\s+(.+)$', re.MULTILINE)
_RE_OL_LINE     = re.compile(r'^\d+\.\s+', re.MULTILINE)
_RE_OL_ITEMS    = re.compile(r'^\d+\.\s+(.+)$', re.MULTILINE)
_RE_CB_SPLIT    = re.compile(r'(\x00CB\d+\x00)')
_RE_BOLD   = re.compile(r'\*\*(.+?)\*\*')
_RE_BOLD2  = re.compile(r'__(.+?)__')
_RE_ITALIC = re.compile(r'(?<!\w)\*([^\*\n]+?)\*(?!\w)')
_RE_ITALIC2 = re.compile(r'(?<!\w)_([^_\n]+?)_(?!\w)')
_RE_LINK   = re.compile(r'\[([^\]]+)\]\(([^)]+)\)')
_RE_TABLE_ROW = re.compile(r'^\|(.+)\|$')
_RE_TABLE_SEP = re.compile(r'^\|[\s\-:|]+\|$')
_RE_TASK_DONE = re.compile(r'^([ \t]*)[\-\*\+]\s+\[[xX]\]\s+(.*)$')
_RE_TASK_TODO = re.compile(r'^([ \t]*)[\-\*\+]\s+\[ \]\s+(.*)$')
_RE_UL_ITEM_INDENT = re.compile(r'^([ \t]*)[\-\*\+]\s+(.+)$')
_RE_OL_ITEM_INDENT = re.compile(r'^([ \t]*)\d+\.\s+(.+)$')


def _pg_token_color(ttype_str: str, p: dict) -> str:
    t = ttype_str
    if t.startswith("Token.Keyword"):       return p["PG_KW"]
    if t.startswith("Token.Name.Function") or t.startswith("Token.Name.Decorator"): return p["PG_FN"]
    if t.startswith("Token.Name.Class"):    return p["PG_CLS"]
    if t.startswith("Token.Name.Builtin"):  return p["PG_BI"]
    if t.startswith("Token.Name"):          return p["PG_NAME"]
    if t.startswith("Token.Literal.String"):return p["PG_STR"]
    if t.startswith("Token.Literal.Number"):return p["PG_NUM"]
    if t.startswith("Token.Comment"):       return p["PG_COM"]
    if t.startswith("Token.Operator"):      return p["PG_OP"]
    if t.startswith("Token.Error"):         return p["PG_ERR"]
    return p["CODE_FG"]

def _pygments_highlight(code: str, lexer, p: dict) -> str:
    if not PYGMENTS_OK:
        return _escape(code)
    try:
        tokens = list(lex(code, lexer))
    except Exception:
        return _escape(code)
    out = []
    for ttype, value in tokens:
        color = _pg_token_color(str(ttype), p)
        escaped = _escape(value)
        if color and color != p["CODE_FG"]:
            out.append(f'<span style="color:{color};">{escaped}</span>')
        else:
            out.append(escaped)
    return "".join(out)

def _render_table(rows: list, p: dict) -> str:
    data_rows = [r for r in rows if not _RE_TABLE_SEP.match(r)]
    if not data_rows:
        return ""
    parsed = []
    for r in data_rows:
        cells = [c.strip() for c in r.strip().strip('|').split('|')]
        parsed.append(cells)
    ncols = max(len(r) for r in parsed)
    html_rows = []
    for ridx, cells in enumerate(parsed):
        while len(cells) < ncols:
            cells.append("")
        is_header = (ridx == 0)
        bg = p["BOT_BG"] if is_header else (p["BG"] if ridx % 2 == 0 else p["BOT_BG"])
        cell_html = []
        for c in cells:
            content = _inline_render(c, p)
            if is_header:
                cell_html.append(
                    f'<th style="padding:6px 10px;text-align:left;border:1px solid {p["BORDER"]};'
                    f'color:{p["HEADING"]};font-weight:bold;">{content}</th>'
                )
            else:
                cell_html.append(
                    f'<td style="padding:6px 10px;text-align:left;border:1px solid {p["BORDER"]};">'
                    f'{content}</td>'
                )
        html_rows.append(f'<tr style="background:{bg};">' + "".join(cell_html) + '</tr>')
    return (
        f'<table style="border-collapse:collapse;margin:8px 0;font-size:12px;'
        f'border:1px solid {p["BORDER"]};">' + "".join(html_rows) + '</table>'
    )

def _render_code_block(lang: str, code: str, p: dict) -> str:
    label = (
        f'<div style="color:{p["DIM"]};font-size:10px;font-family:monospace;'
        f'margin-bottom:4px;letter-spacing:0.5px;text-transform:uppercase;">'
        f'{_escape(lang) if lang else "text"}</div>'
    )
    if PYGMENTS_OK and lang:
        try:
            lexer = get_lexer_by_name(lang, stripall=True)
        except Exception:
            lexer = TextLexer()
        highlighted = _pygments_highlight(code, lexer, p)
    else:
        highlighted = _escape(code)
    return (
        f'<div style="background:{p["CODE_BG"]};border-left:3px solid {p["CODE_BR"]};'
        f'padding:10px 12px;margin:8px 0;border-radius:4px;font-family:monospace;'
        f'font-size:12px;white-space:pre-wrap;word-break:break-word;color:{p["CODE_FG"]};">'
        f'{label}{highlighted}</div>'
    )

def _inline_render(text: str, p: dict) -> str:
    placeholders = []

    def repl_bold(m):
        placeholders.append(f'<strong style="color:{p["STRONG"]};font-weight:600;">{_escape(m.group(1))}</strong>')
        return f"\x00PH{len(placeholders)-1}\x00"

    def repl_italic(m):
        placeholders.append(f'<em style="color:{p["EM"]};font-style:italic;">{_escape(m.group(1))}</em>')
        return f"\x00PH{len(placeholders)-1}\x00"

    def repl_link(m):
        # Экранируем URL так же полно, как обычный текст (не только кавычки) —
        # приложение скрапит веб-страницы (MCPScraper/do_search), и если модель
        # процитирует markdown-ссылку на URL с "грязными" символами из внешней
        # страницы, неполное экранирование позволило бы выйти за пределы
        # атрибута href и исказить разметку в чате.
        url = _escape(m.group(2)).replace('"', '&quot;')
        placeholders.append(f'<a href="{url}" style="color:{p["LINK"]};text-decoration:underline;">{_escape(m.group(1))}</a>')
        return f"\x00PH{len(placeholders)-1}\x00"

    text = _RE_BOLD.sub(repl_bold, text)
    text = _RE_BOLD2.sub(repl_bold, text)
    text = _RE_ITALIC.sub(repl_italic, text)
    text = _RE_ITALIC2.sub(repl_italic, text)
    text = _RE_LINK.sub(repl_link, text)

    text = _escape(text)

    for i, ph in enumerate(placeholders):
        text = text.replace(f"\x00PH{i}\x00", ph)

    return text

def _hang_item(pad: int, marker: str, content_html: str, deco: str = "") -> str:
    """Строка списка с "висячим" отступом (маркер/номер слева, текст с новой
    строки выравнивается под текст первой строки). Раньше это делалось через
    padding-left + text-indent:-18px, но QTextEdit (в отличие от полноценного
    браузерного движка) некорректно считает этот сдвиг и обрезает маркер и
    первый символ текста слева. Табличная раскладка с фиксированными
    колонками не использует отрицательные отступы и рендерится в Qt стабильно."""
    spacer = pad - 18
    return (
        f'<table style="border-collapse:collapse;margin:2px 0;width:100%;{deco}" cellspacing="0" cellpadding="0">'
        f'<tr>'
        f'<td style="width:{spacer}px;padding:0;"></td>'
        f'<td style="width:18px;vertical-align:top;padding:0;">{marker}</td>'
        f'<td style="vertical-align:top;padding:0;">{content_html}</td>'
        f'</tr></table>'
    )


def _render_markdown(text: str, p: dict, depth: int = 0) -> str:
    code_blocks = []
    def _save_cb(m):
        lang = m.group(1).strip()
        code = m.group(2)
        code_blocks.append((lang, code))
        return f"\x00CB{len(code_blocks) - 1}\x00"
    text = _RE_CODEBLOCK.sub(_save_cb, text)

    inline_codes = []
    def _save_ic(m):
        inline_codes.append(m.group(1))
        return f"\x00IC{len(inline_codes) - 1}\x00"
    text = _RE_INLINE_CODE.sub(_save_ic, text)

    raw_blocks = _RE_BLOCK_SPLIT.split(text)
    html_parts = []
    for block in raw_blocks:
        block = block.strip()
        if not block:
            continue

        cbm = _RE_CB_PLACEHOLDER.match(block)
        if cbm:
            idx = int(cbm.group(1))
            lang, code = code_blocks[idx]
            html_parts.append(_render_code_block(lang, code, p))
            continue

        table_lines = [l for l in block.split('\n') if l.strip()]
        if len(table_lines) >= 2 and all(_RE_TABLE_ROW.match(l.strip()) for l in table_lines) \
                and _RE_TABLE_SEP.match(table_lines[1].strip()):
            html_parts.append(_render_table([l.strip() for l in table_lines], p))
            continue

        if _RE_HR.match(block):
            html_parts.append(
                f'<hr style="border:none;border-top:1px solid {p["HR"]};'
                f'margin:14px 0;">'
            )
            continue

        hm = _RE_HEADING.match(block)
        if hm and '\n' not in block:
            level = len(hm.group(1))
            sizes = {1: 22, 2: 18, 3: 16, 4: 14, 5: 13, 6: 12}
            content = _inline_render(hm.group(2), p)
            html_parts.append(
                f'<h{level} style="color:{p["HEADING"]};font-size:{sizes[level]}px;'
                f'font-weight:bold;margin:12px 0 6px 0;padding:0;line-height:1.3;">'
                f'{content}</h{level}>'
            )
            continue

        if block.startswith('>'):
            lines = block.split('\n')
            quote_lines = []
            for l in lines:
                if l.startswith('>'):
                    quote_lines.append(l[1:].lstrip())
                else:
                    quote_lines.append(l)
            inner_text = '\n'.join(quote_lines)
            if depth < 5:
                inner_html = _render_markdown(inner_text, p, depth + 1)
            else:
                inner_html = _inline_render(inner_text, p)
            html_parts.append(
                f'<blockquote style="margin:8px 0;padding:6px 12px;'
                f'border-left:3px solid {p["QUOTE_BR"]};color:{p["QUOTE_FG"]};'
                f'background:{p["QUOTE_BG"]};border-radius:4px;">'
                f'{inner_html}</blockquote>'
            )
            continue

        block_lines = block.split('\n')
        if any(_RE_TASK_DONE.match(l) or _RE_TASK_TODO.match(l) for l in block_lines) \
                and all(
                    _RE_TASK_DONE.match(l) or _RE_TASK_TODO.match(l) or _RE_UL_ITEM_INDENT.match(l)
                    for l in block_lines if l.strip()
                ):
            items_html = []
            for l in block_lines:
                if not l.strip():
                    continue
                tdm = _RE_TASK_DONE.match(l)
                ttm = _RE_TASK_TODO.match(l)
                if tdm:
                    indent, content = tdm.groups()
                    box, deco = "☑", "text-decoration:line-through;opacity:0.7;"
                elif ttm:
                    indent, content = ttm.groups()
                    box, deco = "☐", ""
                else:
                    um = _RE_UL_ITEM_INDENT.match(l)
                    indent, content = um.groups()
                    box, deco = "•", ""
                pad = 24 + (len(indent) // 2) * 18
                items_html.append(
                    _hang_item(pad, box, _inline_render(content, p), deco)
                )
            html_parts.append(f'<div style="margin:6px 0;">{"".join(items_html)}</div>')
            continue

        if _RE_UL_LINE.match(block) and not _RE_UL_HR.match(block):
            ul_lines = [l for l in block_lines if l.strip()]
            if all(_RE_UL_ITEM_INDENT.match(l) for l in ul_lines):
                items_html = []
                for l in ul_lines:
                    indent, content = _RE_UL_ITEM_INDENT.match(l).groups()
                    pad = 24 + (len(indent) // 2) * 18
                    items_html.append(
                        _hang_item(pad, "•", _inline_render(content, p))
                    )
                html_parts.append(f'<div style="margin:6px 0;">{"".join(items_html)}</div>')
                continue
        if _RE_UL_LINE.match(block) and not _RE_UL_HR.match(block):
            items = _RE_UL_ITEMS.findall(block)
            if items:
                items_html = ''.join(
                    f'<li style="margin:2px 0;">{_inline_render(it, p)}</li>'
                    for it in items
                )
                html_parts.append(
                    f'<ul style="margin:6px 0;padding-left:24px;">{items_html}</ul>'
                )
            continue

        if _RE_OL_LINE.match(block):
            ol_lines = [l for l in block_lines if l.strip()]
            if all(_RE_OL_ITEM_INDENT.match(l) for l in ol_lines):
                items_html = []
                for l in ol_lines:
                    indent, content = _RE_OL_ITEM_INDENT.match(l).groups()
                    num = l.strip().split(".")[0] + "."
                    pad = 24 + (len(indent) // 2) * 18
                    items_html.append(
                        _hang_item(pad, _escape(num), _inline_render(content, p))
                    )
                html_parts.append(f'<div style="margin:6px 0;">{"".join(items_html)}</div>')
                continue

        if _RE_OL_LINE.match(block):
            items = _RE_OL_ITEMS.findall(block)
            if items:
                items_html = ''.join(
                    f'<li style="margin:2px 0;">{_inline_render(it, p)}</li>'
                    for it in items
                )
                html_parts.append(
                    f'<ol style="margin:6px 0;padding-left:24px;">{items_html}</ol>'
                )
            continue

        if "\x00CB" in block:
            parts = _RE_CB_SPLIT.split(block)
            for pt in parts:
                pt = pt.strip()
                if not pt: continue
                cbm2 = _RE_CB_PLACEHOLDER.match(pt)
                if cbm2:
                    idx = int(cbm2.group(1))
                    lang, code = code_blocks[idx]
                    html_parts.append(_render_code_block(lang, code, p))
                else:
                    html_parts.append(
                        f'<p style="margin:4px 0;line-height:1.6;">'
                        f'{_inline_render(pt, p)}</p>'
                    )
            continue

        block_html = _inline_render(block, p).replace('\n', '<br>')
        html_parts.append(
            f'<p style="margin:4px 0;line-height:1.6;">{block_html}</p>'
        )

    result = "\n".join(html_parts)

    for i, code in enumerate(inline_codes):
        escaped = _escape(code)
        result = result.replace(
            f"\x00IC{i}\x00",
            f'<code style="background:{p["INLINE_BG"]};border:1px solid {p["INLINE_BR"]};'
            f'padding:1px 5px;border-radius:3px;font-family:monospace;font-size:12px;'
            f'color:{p["CODE_FG"]};">{escaped}</code>'
        )

    return result
