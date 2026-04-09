"""Tests for the pipeline chain construction and step toggling."""

from types import SimpleNamespace

from celery import Celery

from app.tasks import pipeline


class _FakeSig:
    def __init__(self, name, args, immutable=False):
        self.name = name
        self.args = args
        self.immutable = immutable
        self.queue = None

    def set(self, **kwargs):
        self.queue = kwargs.get("queue")
        return self


class TestPipelineChain:
    """Test that run_pipeline() builds the correct chain."""

    def test_full_pipeline_includes_all_v2_steps(self, monkeypatch):
        """Pipeline should include all 6 steps: download, transcribe, diarize, cleanup, summarize, embed."""
        captured_parts = []

        def fake_signature(name, args=None, app=None, immutable=False):
            return _FakeSig(name, args, immutable=immutable)

        class FakeChain:
            def apply_async(self):
                return SimpleNamespace(id="chain-abc")

        def fake_chain(*parts):
            captured_parts.extend(parts)
            return FakeChain()

        monkeypatch.setattr(pipeline, "signature", fake_signature)
        monkeypatch.setattr(pipeline, "chain", fake_chain)

        result_id = pipeline.run_pipeline("vid-123", job_id="job-123")

        assert result_id == "chain-abc"
        assert [p.name for p in captured_parts] == [
            "tasks.download_audio",
            "tasks.transcribe_audio",
            "tasks.diarize_and_align",
            "tasks.cleanup_transcript",
            "tasks.summarize_transcription",
            "tasks.generate_embeddings",
        ]
        assert [p.queue for p in captured_parts] == ["audio", "audio", "diarize", "post", "post", "post"]
        assert [p.immutable for p in captured_parts] == [False, True, True, True, True, True]

    def test_pipeline_step_order(self, monkeypatch):
        """Verify steps are in the correct dependency order."""
        step_order = []

        def fake_signature(name, args=None, app=None, immutable=False):
            step_order.append(name)
            return _FakeSig(name, args, immutable=immutable)

        class FakeChain:
            def apply_async(self):
                return SimpleNamespace(id="x")

        monkeypatch.setattr(pipeline, "signature", fake_signature)
        monkeypatch.setattr(pipeline, "chain", lambda *p: FakeChain())

        pipeline.run_pipeline("v1", job_id="job-1")

        assert step_order.index("tasks.download_audio") < step_order.index("tasks.transcribe_audio")
        assert step_order.index("tasks.transcribe_audio") < step_order.index("tasks.diarize_and_align")
        assert step_order.index("tasks.diarize_and_align") < step_order.index("tasks.cleanup_transcript")
        assert step_order.index("tasks.cleanup_transcript") < step_order.index("tasks.summarize_transcription")
        assert step_order.index("tasks.summarize_transcription") < step_order.index("tasks.generate_embeddings")

    def test_pipeline_passes_payload_to_each_stage(self, monkeypatch):
        """Each stage gets the same explicit payload so routing keeps the exact attempt identity."""
        calls = []

        def fake_signature(name, args=None, app=None, immutable=False):
            calls.append({"name": name, "args": args, "immutable": immutable})
            return _FakeSig(name, args, immutable=immutable)

        class FakeChain:
            def apply_async(self):
                return SimpleNamespace(id="x")

        monkeypatch.setattr(pipeline, "signature", fake_signature)
        monkeypatch.setattr(pipeline, "chain", lambda *p: FakeChain())

        pipeline.run_pipeline("my-video", job_id="job-9")

        for index, call in enumerate(calls):
            assert call["args"] == [{"video_id": "my-video", "job_id": "job-9"}]
            assert call["immutable"] is (index > 0)

    def test_pipeline_chain_uses_immutable_downstream_signatures(self, monkeypatch):
        app = Celery("pipeline-test", broker="memory://", backend="cache+memory://")
        app.conf.task_always_eager = True

        stage_calls = []

        @app.task(name="tests.pipeline.stage1")
        def stage1(payload):
            stage_calls.append(("stage1", payload))
            return {"stage": "one"}

        @app.task(name="tests.pipeline.stage2")
        def stage2(payload):
            stage_calls.append(("stage2", payload))
            return payload

        monkeypatch.setattr(pipeline, "celery", app)
        monkeypatch.setattr(
            pipeline,
            "PIPELINE_TASKS",
            ["tests.pipeline.stage1", "tests.pipeline.stage2"],
        )
        monkeypatch.setattr(pipeline, "get_queue_for_task", lambda _task_name: "test")

        pipeline.run_pipeline("vid-immutable", job_id="job-immutable")

        assert stage_calls == [
            ("stage1", {"video_id": "vid-immutable", "job_id": "job-immutable"}),
            ("stage2", {"video_id": "vid-immutable", "job_id": "job-immutable"}),
        ]

    def test_pipeline_returns_async_result_id(self, monkeypatch):
        def fake_signature(name, args=None, app=None, immutable=False):
            return _FakeSig(name, args, immutable=immutable)

        class FakeChain:
            def apply_async(self):
                return SimpleNamespace(id="result-42")

        monkeypatch.setattr(pipeline, "signature", fake_signature)
        monkeypatch.setattr(pipeline, "chain", lambda *p: FakeChain())

        assert pipeline.run_pipeline("v", job_id="job-v") == "result-42"


class TestPipelineFromPartialChain:
    """Test that run_pipeline_from() builds partial chains for smart retry."""

    def test_resume_from_diarize_skips_download_and_transcribe(self, monkeypatch):
        captured_parts = []

        def fake_signature(name, args=None, app=None, immutable=False):
            sig = _FakeSig(name, args, immutable=immutable)
            captured_parts.append(sig)
            return sig

        class FakeChain:
            def apply_async(self):
                return SimpleNamespace(id="partial-chain")

        monkeypatch.setattr(pipeline, "signature", fake_signature)
        monkeypatch.setattr(pipeline, "chain", lambda *p: FakeChain())

        result_id = pipeline.run_pipeline_from("vid-456", start_from="tasks.diarize_and_align", job_id="job-456")

        assert result_id == "partial-chain"
        assert [c.name for c in captured_parts] == [
            "tasks.diarize_and_align",
            "tasks.cleanup_transcript",
            "tasks.summarize_transcription",
            "tasks.generate_embeddings",
        ]
        for c in captured_parts:
            assert c.args == [{"video_id": "vid-456", "job_id": "job-456"}]
        assert [c.queue for c in captured_parts] == ["diarize", "post", "post", "post"]
        assert [c.immutable for c in captured_parts] == [False, True, True, True]

    def test_resume_from_embeddings_only(self, monkeypatch):
        captured_parts = []

        def fake_signature(name, args=None, app=None, immutable=False):
            captured_parts.append(name)
            return _FakeSig(name, args, immutable=immutable)

        class FakeChain:
            def apply_async(self):
                return SimpleNamespace(id="embed-only")

        monkeypatch.setattr(pipeline, "signature", fake_signature)
        monkeypatch.setattr(pipeline, "chain", lambda *p: FakeChain())

        result_id = pipeline.run_pipeline_from("vid-789", start_from="tasks.generate_embeddings", job_id="job-789")

        assert result_id == "embed-only"
        assert captured_parts == ["tasks.generate_embeddings"]

    def test_invalid_step_raises_error(self):
        import pytest

        with pytest.raises(ValueError, match="Unknown start task"):
            pipeline.run_pipeline_from("vid", start_from="tasks.nonexistent")


class TestPipelineStepSkipping:
    """Test that diarize/cleanup tasks properly skip when disabled."""

    def test_pipeline_always_has_six_steps(self, monkeypatch):
        captured = []

        def fake_signature(name, args=None, app=None, immutable=False):
            return _FakeSig(name, args, immutable=immutable)

        class FakeChain:
            def apply_async(self):
                return SimpleNamespace(id="x")

        def fake_chain(*parts):
            captured.extend(parts)
            return FakeChain()

        monkeypatch.setattr(pipeline, "signature", fake_signature)
        monkeypatch.setattr(pipeline, "chain", fake_chain)

        pipeline.run_pipeline("v1", job_id="job-1")
        assert len(captured) == 6
        assert [p.name for p in captured].count("tasks.diarize_and_align") == 1
        assert [p.name for p in captured].count("tasks.cleanup_transcript") == 1
