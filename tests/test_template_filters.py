"""Tests for Jinja2 template filters defined in app/main.py."""
from app.main import format_duration, format_timestamp


class TestFormatDuration:
    def test_none_returns_placeholder(self):
        assert format_duration(None) == "--:--"

    def test_zero_seconds(self):
        assert format_duration(0) == "0:00"

    def test_seconds_only(self):
        assert format_duration(45) == "0:45"

    def test_minutes_and_seconds(self):
        assert format_duration(125) == "2:05"

    def test_exact_minutes(self):
        assert format_duration(300) == "5:00"

    def test_hours(self):
        assert format_duration(3661) == "1:01:01"

    def test_float_seconds(self):
        assert format_duration(90.7) == "1:30"

    def test_large_duration(self):
        assert format_duration(7200) == "2:00:00"


class TestFormatTimestamp:
    def test_none_returns_zero(self):
        assert format_timestamp(None) == "0:00"

    def test_zero(self):
        assert format_timestamp(0) == "0:00"

    def test_seconds_only(self):
        assert format_timestamp(30) == "0:30"

    def test_minutes_and_seconds(self):
        assert format_timestamp(95) == "1:35"

    def test_exact_minute(self):
        assert format_timestamp(60) == "1:00"

    def test_hours(self):
        assert format_timestamp(3723) == "1:02:03"

    def test_float_input(self):
        assert format_timestamp(65.8) == "1:05"
