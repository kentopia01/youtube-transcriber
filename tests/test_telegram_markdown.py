"""Tests for the formatter-output → Telegram HTML renderer."""

from app.services.telegram_markdown import markdown_to_telegram_html as to_html


class TestBold:
    def test_simple_bold(self):
        assert to_html("**Heading**") == "<b>Heading</b>"

    def test_bold_in_paragraph(self):
        out = to_html("Text **bold** more text.")
        assert out == "Text <b>bold</b> more text."

    def test_multiple_bolds(self):
        out = to_html("**A** and **B**")
        assert out == "<b>A</b> and <b>B</b>"


class TestLinks:
    def test_simple_link(self):
        out = to_html("[click](https://example.com)")
        assert out == '<a href="https://example.com">click</a>'

    def test_link_with_formatter_chip(self):
        md = "[▶ Ep 1 · 19:07](https://youtu.be/abc?t=1147)"
        out = to_html(md)
        assert 'href="https://youtu.be/abc?t=1147"' in out
        assert "▶ Ep 1 · 19:07" in out

    def test_multiple_links_in_paragraph(self):
        md = "See [A](u1) and [B](u2)"
        out = to_html(md)
        assert '<a href="u1">A</a>' in out
        assert '<a href="u2">B</a>' in out


class TestEscaping:
    def test_ampersand_escaped(self):
        assert to_html("Tom & Jerry") == "Tom &amp; Jerry"

    def test_less_than_greater_than(self):
        assert to_html("a<b>c") == "a&lt;b&gt;c"

    def test_escape_does_not_hit_inside_tags(self):
        out = to_html("**rich & text**")
        assert out == "<b>rich &amp; text</b>"


class TestFullResponse:
    def test_perplexity_shaped_paragraph_renders_cleanly(self):
        md = (
            "Answer-first paragraph.\n\n"
            "**Why it matters**\n"
            "Prose with [▶ Ep 1 · 0:42](https://youtu.be/abc?t=42) citation.\n\n"
            "Related: follow up?"
        )
        out = to_html(md)
        assert "<b>Why it matters</b>" in out
        assert '<a href="https://youtu.be/abc?t=42">▶ Ep 1 · 0:42</a>' in out
        # Plain paragraph text preserved
        assert "Answer-first paragraph." in out
        assert "Related:" in out


class TestRobustness:
    def test_empty_input(self):
        assert to_html("") == ""

    def test_no_markdown_passes_through(self):
        assert to_html("Just plain text.") == "Just plain text."

    def test_unclosed_bold_left_alone(self):
        # Not ideal but we shouldn't crash — the pattern is non-matching.
        out = to_html("**not closed")
        assert "**not closed" in out

    def test_link_with_quote_stripped_from_url(self):
        md = '[x](http://a"b.com)'
        out = to_html(md)
        assert '"' not in out.split('href=')[1].split('>')[0].strip('"')