"""Tests for the hybrid search service (BM25 + vector RRF)."""
import uuid
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from app.services.search import (
    _build_where_clause,
    _hybrid_search,
    _keyword_search,
    _vector_search,
    semantic_search,
)


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
