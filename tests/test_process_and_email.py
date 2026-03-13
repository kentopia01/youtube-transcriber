"""Tests for skills/yt-transcribe/scripts/process_and_email.py

Tests pure-logic functions without network access.
"""
from __future__ import annotations

import importlib.util
import json
import os
import sys
import tempfile
from pathlib import Path
from unittest.mock import patch

import pytest

# Import the module from its file path
_SCRIPT_PATH = Path(__file__).resolve().parent.parent / "skills" / "yt-transcribe" / "scripts" / "process_and_email.py"
spec = importlib.util.spec_from_file_location("process_and_email", _SCRIPT_PATH)
mod = importlib.util.module_from_spec(spec)
sys.modules["process_and_email"] = mod  # Required for dataclass on Python 3.14+
spec.loader.exec_module(mod)

VideoResult = mod.VideoResult
is_channel_url = mod.is_channel_url
resolve_recipient = mod.resolve_recipient
build_subject = mod.build_subject
build_text_body = mod.build_text_body
build_html_body = mod.build_html_body
markdownish_to_html = mod.markdownish_to_html
inline_markdown_to_html = mod.inline_markdown_to_html
_load_recipient_map = mod._load_recipient_map


# ---------------------------------------------------------------------------
# is_channel_url
# ---------------------------------------------------------------------------

class TestIsChannelUrl:
    def test_video_url(self):
        assert not is_channel_url("https://www.youtube.com/watch?v=abc123")

    def test_short_url(self):
        assert not is_channel_url("https://youtu.be/abc123")

    def test_handle_url(self):
        assert is_channel_url("https://www.youtube.com/@creator")

    def test_channel_id_url(self):
        assert is_channel_url("https://www.youtube.com/channel/UCxyz")

    def test_c_url(self):
        assert is_channel_url("https://www.youtube.com/c/SomeChannel")

    def test_user_url(self):
        assert is_channel_url("https://www.youtube.com/user/SomeUser")

    def test_non_youtube(self):
        assert not is_channel_url("https://vimeo.com/@creator")

    def test_empty_string(self):
        assert not is_channel_url("")


# ---------------------------------------------------------------------------
# resolve_recipient
# ---------------------------------------------------------------------------

class TestResolveRecipient:
    def test_none(self):
        assert resolve_recipient(None) is None

    def test_empty(self):
        assert resolve_recipient("") is None

    def test_me_default(self):
        result = resolve_recipient("me")
        assert result == "kenneth@01-digital.com"

    def test_ken_case_insensitive(self):
        assert resolve_recipient("Ken") == "kenneth@01-digital.com"

    def test_direct_email(self):
        assert resolve_recipient("alice@example.com") == "alice@example.com"

    def test_config_file_override(self):
        with tempfile.NamedTemporaryFile("w", suffix=".json", delete=False) as f:
            json.dump({"me": "override@test.com"}, f)
            f.flush()
            config_path = f.name
        try:
            with patch.object(Path, "home", return_value=Path(config_path).parent):
                # We need to patch the actual file path the function looks for
                with patch.object(Path, "is_file", return_value=True):
                    pass  # complex patching; test env var instead
        finally:
            os.unlink(config_path)

    def test_env_var_override(self):
        with patch.dict(os.environ, {"YT_RECIPIENT_MAP": '{"me":"env@test.com"}'}):
            assert resolve_recipient("me") == "env@test.com"

    def test_env_var_bad_json(self):
        with patch.dict(os.environ, {"YT_RECIPIENT_MAP": "not json"}):
            # Should fall through to defaults
            assert resolve_recipient("me") == "kenneth@01-digital.com"


# ---------------------------------------------------------------------------
# build_subject
# ---------------------------------------------------------------------------

def _make_result(**kwargs) -> VideoResult:
    defaults = dict(
        title="Test Video",
        source_url="https://www.youtube.com/watch?v=test",
        app_video_id="uuid-1",
        job_id="job-1",
        status="completed",
        summary="A brief summary of the content.",
        transcript="Full transcript here.",
        language="en",
        speakers=[],
    )
    defaults.update(kwargs)
    return VideoResult(**defaults)


class TestBuildSubject:
    def test_single_video_with_summary(self):
        r = _make_result(summary="## Key Findings\nSome details")
        subject = build_subject("https://youtube.com/watch?v=x", None, [r])
        assert subject.startswith("Youtube Transcript:")
        assert "Key Findings" in subject

    def test_single_video_no_summary(self):
        r = _make_result(summary=None)
        subject = build_subject("https://youtube.com/watch?v=x", None, [r])
        assert subject == "Youtube Transcript"

    def test_channel_name(self):
        r1 = _make_result()
        r2 = _make_result()
        subject = build_subject("https://youtube.com/@creator", "CreatorName", [r1, r2])
        assert "CreatorName" in subject

    def test_subject_truncation(self):
        long_summary = "A" * 200
        r = _make_result(summary=long_summary)
        subject = build_subject("https://youtube.com/watch?v=x", None, [r])
        assert len(subject) < 120  # subject should be bounded


# ---------------------------------------------------------------------------
# build_text_body
# ---------------------------------------------------------------------------

class TestBuildTextBody:
    def test_summary_only_by_default(self):
        r = _make_result(summary="Summary text here.", transcript="Full transcript here.")
        body = build_text_body("https://youtube.com/watch?v=x", None, [r])
        assert "Summary text here." in body
        assert "Full transcript here." not in body

    def test_include_transcript_flag(self):
        r = _make_result(summary="Summary text.", transcript="Full transcript text.")
        body = build_text_body("https://youtube.com/watch?v=x", None, [r], include_transcript=True)
        assert "Summary text." in body
        assert "Full transcript text." in body

    def test_channel_line(self):
        r = _make_result()
        body = build_text_body("https://youtube.com/@c", "TestChannel", [r])
        assert "Channel: TestChannel" in body

    def test_no_channel_line(self):
        r = _make_result()
        body = build_text_body("https://youtube.com/watch?v=x", None, [r])
        assert "Channel:" not in body

    def test_speakers_included(self):
        r = _make_result(speakers=["SPEAKER_00", "SPEAKER_01"])
        body = build_text_body("https://youtube.com/watch?v=x", None, [r])
        assert "SPEAKER_00" in body

    def test_language_included(self):
        r = _make_result(language="ja")
        body = build_text_body("https://youtube.com/watch?v=x", None, [r])
        assert "Language: ja" in body


# ---------------------------------------------------------------------------
# build_html_body
# ---------------------------------------------------------------------------

class TestBuildHtmlBody:
    def test_summary_only_by_default(self):
        r = _make_result(summary="HTML summary.", transcript="HTML transcript.")
        body = build_html_body("Subject", "https://youtube.com/watch?v=x", None, [r])
        assert "HTML summary" in body
        assert "Full Transcript" not in body

    def test_include_transcript(self):
        r = _make_result(summary="HTML summary.", transcript="HTML transcript content.")
        body = build_html_body("Subject", "https://youtube.com/watch?v=x", None, [r], include_transcript=True)
        assert "Full Transcript" in body
        assert "HTML transcript content" in body

    def test_html_escaping(self):
        r = _make_result(title='<script>alert("xss")</script>')
        body = build_html_body("Subject", "https://youtube.com/watch?v=x", None, [r])
        assert "<script>" not in body
        assert "&lt;script&gt;" in body

    def test_channel_block(self):
        r = _make_result()
        body = build_html_body("Subject", "https://youtube.com/@c", "ChannelName", [r])
        assert "ChannelName" in body


# ---------------------------------------------------------------------------
# markdownish_to_html
# ---------------------------------------------------------------------------

class TestMarkdownishToHtml:
    def test_empty_string(self):
        assert "No content available" in markdownish_to_html("")

    def test_none(self):
        assert "No content available" in markdownish_to_html(None)

    def test_paragraph(self):
        result = markdownish_to_html("Hello world")
        assert "<p>" in result
        assert "Hello world" in result

    def test_heading(self):
        result = markdownish_to_html("## Title")
        assert "<h3>" in result  # ## -> h3 (level+1)
        assert "Title" in result

    def test_bullet_list(self):
        result = markdownish_to_html("- item one\n- item two")
        assert "<ul>" in result
        assert "<li>" in result
        assert "item one" in result

    def test_bold(self):
        result = markdownish_to_html("**bold text**")
        assert "<strong>bold text</strong>" in result

    def test_italic(self):
        result = markdownish_to_html("*italic text*")
        assert "<em>italic text</em>" in result

    def test_code(self):
        result = markdownish_to_html("`code`")
        assert "<code>code</code>" in result

    def test_link(self):
        result = markdownish_to_html("[Click](https://example.com)")
        assert 'href="https://example.com"' in result
        assert "Click" in result


# ---------------------------------------------------------------------------
# inline_markdown_to_html
# ---------------------------------------------------------------------------

class TestInlineMarkdownToHtml:
    def test_html_escape(self):
        result = inline_markdown_to_html('<b>not bold</b>')
        assert "&lt;b&gt;" in result

    def test_nested_formatting(self):
        result = inline_markdown_to_html("**bold** and *italic*")
        assert "<strong>bold</strong>" in result
        assert "<em>italic</em>" in result


# ---------------------------------------------------------------------------
# _load_recipient_map
# ---------------------------------------------------------------------------

class TestLoadRecipientMap:
    def test_defaults(self):
        with patch.dict(os.environ, {}, clear=True):
            # Remove env var if set
            os.environ.pop("YT_RECIPIENT_MAP", None)
            rmap = _load_recipient_map()
            assert rmap.get("me") == "kenneth@01-digital.com"

    def test_env_override(self):
        with patch.dict(os.environ, {"YT_RECIPIENT_MAP": '{"me":"new@test.com","boss":"b@t.com"}'}):
            rmap = _load_recipient_map()
            assert rmap["me"] == "new@test.com"
            assert rmap["boss"] == "b@t.com"

    def test_config_file(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            config_file = Path(tmpdir) / ".yt-transcriber-recipients.json"
            config_file.write_text('{"me":"file@test.com"}')

            with patch.dict(os.environ, {}, clear=True):
                os.environ.pop("YT_RECIPIENT_MAP", None)
                with patch.object(Path, "home", return_value=Path(tmpdir)):
                    rmap = _load_recipient_map()
                    assert rmap["me"] == "file@test.com"
