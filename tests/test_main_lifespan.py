"""Tests for the FastAPI lifespan startup hook that warms the embedding model."""

import sys
from unittest.mock import MagicMock

import pytest
from fastapi.testclient import TestClient

from app import main as app_main
from app.services import embedding as embedding_service


@pytest.fixture(autouse=True)
def _reset_embedding_cache():
    embedding_service._reset_caches()
    yield
    embedding_service._reset_caches()


class TestWarmEmbeddingModel:
    def test_warm_invokes_loader(self, monkeypatch):
        calls = {"n": 0}

        class FakeST:
            def __init__(self, *a, **kw):
                calls["n"] += 1

        fake_module = MagicMock()
        fake_module.SentenceTransformer = FakeST
        monkeypatch.setitem(sys.modules, "sentence_transformers", fake_module)
        monkeypatch.setattr(embedding_service, "get_torch_device", lambda: "cpu")

        app_main._warm_embedding_model()

        assert calls["n"] == 1

    def test_warm_swallows_import_error(self, monkeypatch):
        # Simulate sentence-transformers missing
        monkeypatch.setitem(sys.modules, "sentence_transformers", None)
        sys.modules.pop("sentence_transformers", None)

        real_import = __builtins__["__import__"] if isinstance(__builtins__, dict) else __builtins__.__import__

        def fake_import(name, *args, **kwargs):
            if name == "sentence_transformers":
                raise ImportError("missing extra")
            return real_import(name, *args, **kwargs)

        monkeypatch.setattr("builtins.__import__", fake_import)

        # Must not raise
        app_main._warm_embedding_model()

    def test_warm_swallows_runtime_error(self, monkeypatch):
        class BoomST:
            def __init__(self, *a, **kw):
                raise RuntimeError("model download failed")

        fake_module = MagicMock()
        fake_module.SentenceTransformer = BoomST
        monkeypatch.setitem(sys.modules, "sentence_transformers", fake_module)
        monkeypatch.setattr(embedding_service, "get_torch_device", lambda: "cpu")

        # Must not raise
        app_main._warm_embedding_model()


class TestLifespanRunsOnStartup:
    def test_lifespan_warms_model(self, monkeypatch):
        calls = {"n": 0}

        def fake_warm():
            calls["n"] += 1

        monkeypatch.setattr(app_main, "_warm_embedding_model", fake_warm)

        app = app_main.create_app()
        with TestClient(app):
            pass

        assert calls["n"] == 1
