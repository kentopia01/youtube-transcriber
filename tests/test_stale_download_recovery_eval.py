import importlib
import os

import scripts.evaluate_stale_download_recovery as evaluation_module
from scripts.evaluate_stale_download_recovery import Candidate, classify_metadata, render_markdown


def _candidate() -> Candidate:
    return Candidate("job", "video", "youtube", "Old title", "https://youtu.be/youtube", "2026-04-01")


def test_classifies_eligible_public_long_form_video():
    result = classify_metadata(
        _candidate(),
        {"duration": 1800, "availability": "public", "live_status": "not_live", "title": "Current"},
        min_duration_seconds=600,
        max_duration_seconds=15000,
    )

    assert result.category == "eligible"
    assert result.current_title == "Current"


def test_classifies_short_unavailable_scheduled_and_over_limit():
    cases = [
        ({"duration": 100, "availability": "public"}, "short_form"),
        ({"duration": 1000, "availability": "private"}, "unavailable"),
        ({"duration": 1000, "availability": "public", "live_status": "is_upcoming"}, "live_or_scheduled"),
        ({"duration": 16000, "availability": "public"}, "duration_limit"),
    ]
    for info, expected in cases:
        result = classify_metadata(
            _candidate(), info, min_duration_seconds=600, max_duration_seconds=15000
        )
        assert result.category == expected


def test_missing_duration_requires_review_and_markdown_has_counts():
    result = classify_metadata(
        _candidate(), {"availability": "public"}, min_duration_seconds=600, max_duration_seconds=15000
    )

    assert result.category == "needs_review"
    assert "needs_review=1" in render_markdown([result])


def test_import_does_not_load_runtime_environment(monkeypatch):
    monkeypatch.delenv("WORKER_MODE", raising=False)

    importlib.reload(evaluation_module)

    assert "WORKER_MODE" not in os.environ
