"""Convert the formatter's CommonMark-ish output into Telegram HTML.

Telegram's "Markdown" mode uses single-asterisk bold, which conflicts with
the ``**bold**`` our response_formatter emits. HTML mode is unambiguous:

    **bold**          → <b>bold</b>
    [text](url)       → <a href="url">text</a>
    everything else   → HTML-escaped plain text

We keep newlines (Telegram preserves them). Anchors are sanitized so
a malformed URL can't break the parser.
"""

from __future__ import annotations

import re
from html import escape


_BOLD_RE = re.compile(r"\*\*(.+?)\*\*", re.DOTALL)
_LINK_RE = re.compile(r"\[([^\[\]]+?)\]\(([^()\s]+)\)")


def _render_token(text: str) -> str:
    """Escape plain text chunks. Tags are inserted by callers."""
    return escape(text, quote=False)


def markdown_to_telegram_html(md: str) -> str:
    if not md:
        return md

    parts: list[str] = []
    pos = 0
    # Scan for link or bold occurrences in order, rendering intermediates.
    pattern = re.compile(
        r"\*\*(?P<bold>.+?)\*\*"
        r"|"
        r"\[(?P<ltext>[^\[\]]+?)\]\((?P<lurl>[^()\s]+)\)",
        re.DOTALL,
    )

    for m in pattern.finditer(md):
        start, end = m.span()
        if start > pos:
            parts.append(_render_token(md[pos:start]))

        if m.group("bold") is not None:
            parts.append(f"<b>{_render_token(m.group('bold'))}</b>")
        else:
            text = _render_token(m.group("ltext"))
            url = m.group("lurl")
            # URL stays unescaped inside the href attr but we strip anything
            # that could break the attribute.
            safe_url = url.replace('"', "").replace(">", "").replace("<", "")
            parts.append(f'<a href="{safe_url}">{text}</a>')

        pos = end

    if pos < len(md):
        parts.append(_render_token(md[pos:]))

    return "".join(parts)


__all__ = ["markdown_to_telegram_html"]
