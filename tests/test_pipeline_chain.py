"""Tests for the pipeline chain construction and step toggling."""

from types import SimpleNamespace

from app.tasks import pipeline


class TestPipelineChain:
    """Test that run_pipeline() builds the correct chain."""

    def test_full_pipeline_includes_all_v2_steps(self, monkeypatch):
        """Pipeline should include all 6 steps: download, transcribe, diarize, cleanup, summarize, embed."""
        captured_parts = []

        def fake_signature(name, args=None, app=None):
            return name

        class FakeChain:
            def apply_async(self):
                return SimpleNamespace(id="chain-abc")

        def fake_chain(*parts):
            captured_parts.extend(parts)
            return FakeChain()

        monkeypatch.setattr(pipeline, "signature", fake_signature)
        monkeypatch.setattr(pipeline, "chain", fake_chain)

        result_id = pipeline.run_pipeline("vid-123")

        assert result_id == "chain-abc"
        assert captured_parts == [
            "tasks.download_audio",
            "tasks.transcribe_audio",
            "tasks.diarize_and_align",
            "tasks.cleanup_transcript",
            "tasks.summarize_transcription",
            "tasks.generate_embeddings",
        ]

    def test_pipeline_step_order(self, monkeypatch):
        """Verify steps are in the correct dependency order."""
        step_order = []

        def fake_signature(name, args=None, app=None):
            step_order.append(name)
            return name

        class FakeChain:
            def apply_async(self):
                return SimpleNamespace(id="x")

        monkeypatch.setattr(pipeline, "signature", fake_signature)
        monkeypatch.setattr(pipeline, "chain", lambda *p: FakeChain())

        pipeline.run_pipeline("v1")

        # download must come before transcribe
        assert step_order.index("tasks.download_audio") < step_order.index("tasks.transcribe_audio")
        # transcribe before diarize
        assert step_order.index("tasks.transcribe_audio") < step_order.index("tasks.diarize_and_align")
        # diarize before cleanup
        assert step_order.index("tasks.diarize_and_align") < step_order.index("tasks.cleanup_transcript")
        # cleanup before summarize
        assert step_order.index("tasks.cleanup_transcript") < step_order.index("tasks.summarize_transcription")
        # summarize before embed
        assert step_order.index("tasks.summarize_transcription") < step_order.index("tasks.generate_embeddings")

    def test_pipeline_passes_video_id_to_download(self, monkeypatch):
        """Only the download step gets the video_id arg."""
        calls = []

        def fake_signature(name, args=None, app=None):
            calls.append({"name": name, "args": args})
            return name

        class FakeChain:
            def apply_async(self):
                return SimpleNamespace(id="x")

        monkeypatch.setattr(pipeline, "signature", fake_signature)
        monkeypatch.setattr(pipeline, "chain", lambda *p: FakeChain())

        pipeline.run_pipeline("my-video")

        download_call = next(c for c in calls if c["name"] == "tasks.download_audio")
        assert download_call["args"] == ["my-video"]

        # All other steps should have args=None (they receive from chain)
        for call in calls:
            if call["name"] != "tasks.download_audio":
                assert call["args"] is None

    def test_pipeline_returns_async_result_id(self, monkeypatch):
        def fake_signature(name, args=None, app=None):
            return name

        class FakeChain:
            def apply_async(self):
                return SimpleNamespace(id="result-42")

        monkeypatch.setattr(pipeline, "signature", fake_signature)
        monkeypatch.setattr(pipeline, "chain", lambda *p: FakeChain())

        assert pipeline.run_pipeline("v") == "result-42"


class TestPipelineStepSkipping:
    """Test that diarize/cleanup tasks properly skip when disabled.

    Note: The actual skip logic is in the task implementations (diarize.py, cleanup.py),
    not in pipeline.py. The pipeline always includes all steps, and the tasks
    themselves check settings to decide whether to run or no-op.
    """

    def test_pipeline_always_has_six_steps(self, monkeypatch):
        """Even when features are disabled, pipeline has all 6 steps.
        The tasks themselves check their feature flags."""
        captured = []

        def fake_signature(name, args=None, app=None):
            return name

        class FakeChain:
            def apply_async(self):
                return SimpleNamespace(id="x")

        def fake_chain(*parts):
            captured.extend(parts)
            return FakeChain()

        monkeypatch.setattr(pipeline, "signature", fake_signature)
        monkeypatch.setattr(pipeline, "chain", fake_chain)

        pipeline.run_pipeline("v1")
        assert len(captured) == 6
        assert "tasks.diarize_and_align" in captured
        assert "tasks.cleanup_transcript" in captured
