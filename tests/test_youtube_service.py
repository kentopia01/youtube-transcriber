"""Tests for the YouTube service module."""
from app.services.youtube import extract_video_id, is_channel_url


class TestExtractVideoId:
    def test_standard_url(self):
        assert extract_video_id("https://www.youtube.com/watch?v=dQw4w9WgXcQ") == "dQw4w9WgXcQ"

    def test_short_url(self):
        assert extract_video_id("https://youtu.be/dQw4w9WgXcQ") == "dQw4w9WgXcQ"

    def test_embed_url(self):
        assert extract_video_id("https://www.youtube.com/embed/dQw4w9WgXcQ") == "dQw4w9WgXcQ"

    def test_shorts_url(self):
        assert extract_video_id("https://www.youtube.com/shorts/dQw4w9WgXcQ") == "dQw4w9WgXcQ"

    def test_url_with_params(self):
        assert extract_video_id("https://www.youtube.com/watch?v=dQw4w9WgXcQ&t=120") == "dQw4w9WgXcQ"

    def test_live_url(self):
        assert extract_video_id("https://www.youtube.com/live/dQw4w9WgXcQ?feature=share") == "dQw4w9WgXcQ"

    def test_raw_video_id(self):
        assert extract_video_id("dQw4w9WgXcQ") == "dQw4w9WgXcQ"

    def test_invalid_url(self):
        assert extract_video_id("https://google.com") is None

    def test_empty_string(self):
        assert extract_video_id("") is None


class TestIsChannelUrl:
    def test_channel_handle(self):
        assert is_channel_url("https://www.youtube.com/@channelname") is True

    def test_channel_id(self):
        assert is_channel_url("https://www.youtube.com/channel/UCxxxxxxxx") is True

    def test_channel_c(self):
        assert is_channel_url("https://www.youtube.com/c/channelname") is True

    def test_channel_user(self):
        assert is_channel_url("https://www.youtube.com/user/channelname") is True

    def test_video_url(self):
        assert is_channel_url("https://www.youtube.com/watch?v=dQw4w9WgXcQ") is False
