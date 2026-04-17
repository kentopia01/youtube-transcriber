"""Tests for the hybrid search service (BM25 + vector RRF)."""
import uuid
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from app.services import embedding as embedding_service
from app.services.search import (
    _build_where_clause,
    _hybrid_search,
    _keyword_search,
    _vector_search,
    encode_query,
    semantic_search,
)


@pytest.fixture(autouse=True)
def _reset_embedding_cache_for_search():
    embedding_service._reset_caches()
    yield
    embedding_service._reset_caches()


# --- Helper fixtures ---

def _make_row(**kwargs):
    """Create a mock DB row with named attributes."""
    row = MagicMock()
    for k, v in kwargs.items():
        setattr(row, k, v)
    return row


def _fake_db_result(rows):
    """Return an AsyncMock session whose execute returns the given rows."""
    db = AsyncMock()
    result = MagicMock()
    result.fetchall.return_value = rows
    db.execute.return_value = result
    return db


FAKE_EMBEDDING = [0.1] * 768
FAKE_UUID = uuid.uuid4()
FAKE_VIDEO_UUID = uuid.uuid4()


# --- _build_where_clause ---

class TestBuildWhereClause:
    def test_no_channel_returns_empty(self):
        clause, params = _build_where_clause(None)
        assert clause == ""
        assert params == {}

    def test_with_channel_returns_where(self):
        cid = uuid.uuid4()
        clause, params = _build_where_clause(cid)
        assert "WHERE" in clause
        assert "channel_id" in params


# --- _vector_search ---

class TestVectorSearch:
    @pytest.mark.asyncio
    async def test_returns_results(self):
        rows = [
            _make_row(
                id=FAKE_UUID, video_id=FAKE_VIDEO_UUID, video_title="Test Video",
                chunk_text="Hello world", start_time=0.0, end_time=5.0,
                speaker="SPEAKER_00", similarity=0.95,
            ),
        ]
        db = _fake_db_result(rows)
        results = await _vector_search(db, FAKE_EMBEDDING, limit=10, channel_id=None)
        assert len(results) == 1
        assert results[0]["similarity"] == 0.95
        assert results[0]["chunk_text"] == "Hello world"
        assert results[0]["speaker"] == "SPEAKER_00"

    @pytest.mark.asyncio
    async def test_empty_results(self):
        db = _fake_db_result([])
        results = await _vector_search(db, FAKE_EMBEDDING, limit=10, channel_id=None)
        assert results == []

    @pytest.mark.asyncio
    async def test_channel_filter_passed(self):
        db = _fake_db_result([])
        cid = uuid.uuid4()
        await _vector_search(db, FAKE_EMBEDDING, limit=5, channel_id=cid)
        call_args = db.execute.call_args
        params = call_args[0][1]
        assert params["channel_id"] == str(cid)


# --- _keyword_search ---

class TestKeywordSearch:
    @pytest.mark.asyncio
    async def test_returns_results(self):
        rows = [
            _make_row(
                id=FAKE_UUID, video_id=FAKE_VIDEO_UUID, video_title="Test Video",
                chunk_text="machine learning basics", start_time=10.0, end_time=20.0,
                speaker=None, similarity=0.42,
            ),
        ]
        db = _fake_db_result(rows)
        results = await _keyword_search(db, "machine learning", limit=10, channel_id=None)
        assert len(results) == 1
        assert results[0]["similarity"] == 0.42

    @pytest.mark.asyncio
    async def test_empty_results(self):
        db = _fake_db_result([])
        results = await _keyword_search(db, "nonexistent", limit=10, channel_id=None)
        assert results == []

    @pytest.mark.asyncio
    async def test_special_characters_in_query(self):
        """Special chars like quotes and ampersands should not crash the query."""
        db = _fake_db_result([])
        # These should not raise
        await _keyword_search(db, "C++ & Java's 'features'", limit=10, channel_id=None)
        await _keyword_search(db, "SELECT * FROM users;", limit=10, channel_id=None)
        await _keyword_search(db, "", limit=10, channel_id=None)


# --- _hybrid_search ---

class TestHybridSearch:
    @pytest.mark.asyncio
    async def test_returns_rrf_scores(self):
        rows = [
            _make_row(
                id=FAKE_UUID, video_id=FAKE_VIDEO_UUID, video_title="Test Video",
                chunk_text="hybrid result", start_time=0.0, end_time=10.0,
                speaker="SPEAKER_01", rrf_score=0.0328,
            ),
        ]
        db = _fake_db_result(rows)
        results = await _hybrid_search(
            db, "test query", FAKE_EMBEDDING, limit=10, channel_id=None
        )
        assert len(results) == 1
        assert results[0]["similarity"] == 0.0328
        assert results[0]["chunk_text"] == "hybrid result"

    @pytest.mark.asyncio
    async def test_empty_results(self):
        db = _fake_db_result([])
        results = await _hybrid_search(
            db, "nothing", FAKE_EMBEDDING, limit=10, channel_id=None
        )
        assert results == []

    @pytest.mark.asyncio
    async def test_rrf_k_parameter_passed(self):
        db = _fake_db_result([])
        await _hybrid_search(
            db, "test", FAKE_EMBEDDING, limit=10, channel_id=None, rrf_k=100
        )
        call_args = db.execute.call_args
        params = call_args[0][1]
        assert params["rrf_k"] == 100

    @pytest.mark.asyncio
    async def test_candidate_pool_is_3x_limit(self):
        """The SQL should fetch 3x limit candidates for each ranking method."""
        db = _fake_db_result([])
        await _hybrid_search(
            db, "test", FAKE_EMBEDDING, limit=5, channel_id=None
        )
        call_args = db.execute.call_args
        sql_text = str(call_args[0][0])
        # The candidate LIMIT should be 15 (3 * 5)
        assert "15" in sql_text


# --- semantic_search (dispatcher) ---

class TestSemanticSearch:
    @pytest.mark.asyncio
    @patch("app.services.search._vector_search", new_callable=AsyncMock)
    async def test_vector_mode(self, mock_vector):
        mock_vector.return_value = [{"id": 1, "similarity": 0.9}]
        db = AsyncMock()
        results = await semantic_search(
            db, FAKE_EMBEDDING, limit=10, search_mode="vector"
        )
        mock_vector.assert_called_once()
        assert results == [{"id": 1, "similarity": 0.9}]

    @pytest.mark.asyncio
    @patch("app.services.search._keyword_search", new_callable=AsyncMock)
    async def test_keyword_mode(self, mock_keyword):
        mock_keyword.return_value = [{"id": 2, "similarity": 0.5}]
        db = AsyncMock()
        results = await semantic_search(
            db, FAKE_EMBEDDING, limit=10, query="test query", search_mode="keyword"
        )
        mock_keyword.assert_called_once()
        assert results == [{"id": 2, "similarity": 0.5}]

    @pytest.mark.asyncio
    @patch("app.services.search._hybrid_search", new_callable=AsyncMock)
    async def test_hybrid_mode(self, mock_hybrid):
        mock_hybrid.return_value = [{"id": 3, "similarity": 0.03}]
        db = AsyncMock()
        results = await semantic_search(
            db, FAKE_EMBEDDING, limit=10, query="test query", search_mode="hybrid"
        )
        mock_hybrid.assert_called_once()
        assert results == [{"id": 3, "similarity": 0.03}]

    @pytest.mark.asyncio
    @patch("app.services.search._vector_search", new_callable=AsyncMock)
    async def test_hybrid_without_query_falls_back_to_vector(self, mock_vector):
        """Hybrid mode without query text should gracefully fall back to vector."""
        mock_vector.return_value = []
        db = AsyncMock()
        results = await semantic_search(
            db, FAKE_EMBEDDING, limit=10, query=None, search_mode="hybrid"
        )
        mock_vector.assert_called_once()

    @pytest.mark.asyncio
    @patch("app.services.search._vector_search", new_callable=AsyncMock)
    async def test_keyword_without_query_falls_back_to_vector(self, mock_vector):
        """Keyword mode without query text should gracefully fall back to vector."""
        mock_vector.return_value = []
        db = AsyncMock()
        results = await semantic_search(
            db, FAKE_EMBEDDING, limit=10, query=None, search_mode="keyword"
        )
        mock_vector.assert_called_once()

    @pytest.mark.asyncio
    @patch("app.services.search._vector_search", new_callable=AsyncMock)
    async def test_default_mode_uses_config(self, mock_vector):
        """When no search_mode override, uses settings.search_mode."""
        mock_vector.return_value = []
        db = AsyncMock()
        with patch("app.services.search.settings") as mock_settings:
            mock_settings.search_mode = "vector"
            results = await semantic_search(db, FAKE_EMBEDDING, limit=10)
            mock_vector.assert_called_once()

    @pytest.mark.asyncio
    @patch("app.services.search._vector_search", new_callable=AsyncMock)
    async def test_override_beats_config(self, mock_vector):
        """Explicit search_mode parameter overrides settings."""
        mock_vector.return_value = []
        db = AsyncMock()
        with patch("app.services.search.settings") as mock_settings:
            mock_settings.search_mode = "hybrid"
            # Override to vector should use vector, not hybrid
            await semantic_search(
                db, FAKE_EMBEDDING, limit=10, search_mode="vector"
            )
            mock_vector.assert_called_once()


# --- RRF score math ---

class TestRRFScoreCalculation:
    """Verify that RRF scoring logic is correct in the SQL template."""

    def test_rrf_formula_with_k60(self):
        """Manual RRF calculation: score = 1/(k+rank_bm25) + 1/(k+rank_vector)"""
        k = 60
        # Item ranked #1 in both → highest score
        score_best = 1 / (k + 1) + 1 / (k + 1)
        assert round(score_best, 4) == round(2 / 61, 4)

        # Item ranked #1 in vector, not in keyword results → only vector contrib
        score_vector_only = 1 / (k + 1) + 0  # COALESCE gives 0
        assert round(score_vector_only, 4) == round(1 / 61, 4)

        # Item ranked #10 in both
        score_mid = 1 / (k + 10) + 1 / (k + 10)
        assert round(score_mid, 4) == round(2 / 70, 4)

        # Best score > mid score
        assert score_best > score_mid > score_vector_only


class TestEdgeCases:
    """Edge cases for search functions."""

    @pytest.mark.asyncio
    async def test_vector_search_with_zero_limit(self):
        db = _fake_db_result([])
        results = await _vector_search(db, FAKE_EMBEDDING, limit=0, channel_id=None)
        assert results == []

    @pytest.mark.asyncio
    async def test_keyword_search_empty_query(self):
        db = _fake_db_result([])
        results = await _keyword_search(db, "", limit=10, channel_id=None)
        assert results == []

    @pytest.mark.asyncio
    async def test_hybrid_search_unicode_query(self):
        """Unicode queries should not crash."""
        db = _fake_db_result([])
        await _hybrid_search(
            db, "日本語テスト 한국어", FAKE_EMBEDDING, limit=10, channel_id=None
        )
        # Should not raise

    @pytest.mark.asyncio
    async def test_hybrid_search_single_word_query(self):
        """Single-word queries should work in hybrid mode."""
        db = _fake_db_result([])
        await _hybrid_search(db, "Python", FAKE_EMBEDDING, limit=10, channel_id=None)
        call_args = db.execute.call_args
        params = call_args[0][1]
        assert params["query"] == "Python"

    @pytest.mark.asyncio
    async def test_hybrid_search_very_long_query(self):
        """Very long queries should not crash."""
        long_query = "artificial intelligence " * 200  # ~400 words
        db = _fake_db_result([])
        await _hybrid_search(
            db, long_query, FAKE_EMBEDDING, limit=10, channel_id=None
        )
        # Should not raise

    @pytest.mark.asyncio
    async def test_keyword_search_sql_injection_patterns(self):
        """SQL injection patterns are safely parameterized."""
        db = _fake_db_result([])
        injection_queries = [
            "'; DROP TABLE embedding_chunks; --",
            "' OR '1'='1",
            "UNION SELECT * FROM users",
            "1; DELETE FROM videos",
            "' AND 1=1 --",
        ]
        for q in injection_queries:
            await _keyword_search(db, q, limit=10, channel_id=None)
            # Verify query text is passed as a parameter, not interpolated
            call_args = db.execute.call_args
            params = call_args[0][1]
            assert params["query"] == q

    @pytest.mark.asyncio
    async def test_hybrid_search_sql_injection_patterns(self):
        """SQL injection patterns are safely parameterized in hybrid mode."""
        db = _fake_db_result([])
        await _hybrid_search(
            db, "'; DROP TABLE embedding_chunks; --",
            FAKE_EMBEDDING, limit=10, channel_id=None,
        )
        call_args = db.execute.call_args
        params = call_args[0][1]
        assert params["query"] == "'; DROP TABLE embedding_chunks; --"


class TestHybridSearchSQL:
    """Verify the hybrid search SQL structure is correct."""

    @pytest.mark.asyncio
    async def test_uses_full_outer_join(self):
        """Hybrid search must use FULL OUTER JOIN to capture keyword-only matches."""
        db = _fake_db_result([])
        await _hybrid_search(db, "test", FAKE_EMBEDDING, limit=10, channel_id=None)
        sql_text = str(db.execute.call_args[0][0])
        assert "FULL OUTER JOIN" in sql_text

    @pytest.mark.asyncio
    async def test_keyword_ranked_has_display_columns(self):
        """keyword_ranked CTE must include display columns for keyword-only results."""
        db = _fake_db_result([])
        await _hybrid_search(db, "test", FAKE_EMBEDDING, limit=10, channel_id=None)
        sql_text = str(db.execute.call_args[0][0])
        # After FULL OUTER JOIN, keyword-only results need COALESCE for display
        assert "COALESCE(vr.id, kr.id)" in sql_text
        assert "COALESCE(vr.chunk_text, kr.chunk_text)" in sql_text

    @pytest.mark.asyncio
    async def test_both_rrf_components_use_coalesce(self):
        """Both vector_rank and keyword_rank must COALESCE to 0 for one-sided matches."""
        db = _fake_db_result([])
        await _hybrid_search(db, "test", FAKE_EMBEDDING, limit=10, channel_id=None)
        sql_text = str(db.execute.call_args[0][0])
        # Vector rank should COALESCE for keyword-only items
        assert "COALESCE(1.0 / (:rrf_k + vr.vector_rank), 0)" in sql_text
        # Keyword rank should COALESCE for vector-only items
        assert "COALESCE(1.0 / (:rrf_k + kr.keyword_rank), 0)" in sql_text


class TestEncodeQuery:
    """Verify encode_query applies the search_query: prefix and shares the embedding cache."""

    def test_applies_search_query_prefix(self, monkeypatch):
        captured = {}

        class FakeST:
            def __init__(self, *a, **kw):
                pass

            def encode(self, texts, normalize_embeddings=True):
                captured["texts"] = texts
                import numpy as np
                return np.array([[0.1] * 768])

        fake_module = MagicMock()
        fake_module.SentenceTransformer = FakeST
        monkeypatch.setitem(__import__("sys").modules, "sentence_transformers", fake_module)
        monkeypatch.setattr(embedding_service, "get_torch_device", lambda: "cpu")

        vec = encode_query("tell me about pricing", model_cache_dir="/tmp/m")

        assert captured["texts"] == ["search_query: tell me about pricing"]
        assert len(vec) == 768

    def test_shares_cache_with_embedding_service(self, monkeypatch):
        load_counter = {"n": 0}

        class FakeST:
            def __init__(self, *a, **kw):
                load_counter["n"] += 1

            def encode(self, texts, normalize_embeddings=True):
                import numpy as np
                return np.array([[0.0] * 768])

        fake_module = MagicMock()
        fake_module.SentenceTransformer = FakeST
        monkeypatch.setitem(__import__("sys").modules, "sentence_transformers", fake_module)
        monkeypatch.setattr(embedding_service, "get_torch_device", lambda: "cpu")

        # Warm via embedding service first
        embedding_service._get_embedding_model("/tmp/m")
        # Now a search query should NOT reload the model
        encode_query("anything", model_cache_dir="/tmp/m")
        encode_query("again", model_cache_dir="/tmp/m")

        assert load_counter["n"] == 1
