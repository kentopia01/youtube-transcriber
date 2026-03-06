"""Tests for hybrid search (BM25 + vector RRF) in app/services/search.py."""
import uuid
from collections import namedtuple
from unittest.mock import AsyncMock, patch

import pytest

from app.services.search import (
    _build_where_clause,
    _hybrid_search,
    _keyword_search,
    _vector_search,
    semantic_search,
)


# Helper to create mock DB rows as named tuples
def _make_row(**kwargs):
    Row = namedtuple("Row", kwargs.keys())
    return Row(**kwargs)


def _make_mock_db(rows):
    """Create a mock AsyncSession that returns given rows."""
    from unittest.mock import MagicMock
    # db.execute() is async, but result.fetchall() is sync
    mock_result = MagicMock()
    mock_result.fetchall.return_value = rows
    db = AsyncMock()
    db.execute.return_value = mock_result
    return db


class TestBuildWhereClause:
    def test_no_channel_id(self):
        clause, params = _build_where_clause(None)
        assert clause == ""
        assert params == {}

    def test_with_channel_id(self):
        cid = uuid.uuid4()
        clause, params = _build_where_clause(cid)
        assert "channel_id" in clause
        assert params["channel_id"] == str(cid)


class TestVectorSearch:
    @pytest.mark.asyncio
    async def test_returns_results(self):
        row = _make_row(
            id=uuid.uuid4(),
            video_id=uuid.uuid4(),
            video_title="Test Video",
            chunk_text="some content",
            start_time=0.0,
            end_time=5.0,
            speaker="SPEAKER_00",
            similarity=0.95,
        )
        db = _make_mock_db([row])

        results = await _vector_search(db, [0.1] * 768, limit=10, channel_id=None)
        assert len(results) == 1
        assert results[0]["video_title"] == "Test Video"
        assert results[0]["similarity"] == 0.95
        assert results[0]["speaker"] == "SPEAKER_00"

    @pytest.mark.asyncio
    async def test_with_channel_filter(self):
        db = _make_mock_db([])
        cid = uuid.uuid4()
        results = await _vector_search(db, [0.1] * 768, limit=5, channel_id=cid)
        assert results == []
        # Verify channel_id was passed in params
        call_args = db.execute.call_args
        assert str(cid) in str(call_args)


class TestKeywordSearch:
    @pytest.mark.asyncio
    async def test_returns_results(self):
        row = _make_row(
            id=uuid.uuid4(),
            video_id=uuid.uuid4(),
            video_title="Keyword Match",
            chunk_text="machine learning deep dive",
            start_time=10.0,
            end_time=20.0,
            speaker=None,
            similarity=0.42,
        )
        db = _make_mock_db([row])

        results = await _keyword_search(db, "machine learning", limit=10, channel_id=None)
        assert len(results) == 1
        assert results[0]["video_title"] == "Keyword Match"
        assert results[0]["similarity"] == 0.42

    @pytest.mark.asyncio
    async def test_sql_contains_tsquery(self):
        db = _make_mock_db([])
        await _keyword_search(db, "test query", limit=5, channel_id=None)
        sql_text = str(db.execute.call_args[0][0].text)
        assert "plainto_tsquery" in sql_text
        assert "ts_rank" in sql_text

    @pytest.mark.asyncio
    async def test_with_channel_filter(self):
        db = _make_mock_db([])
        cid = uuid.uuid4()
        await _keyword_search(db, "test", limit=5, channel_id=cid)
        sql_text = str(db.execute.call_args[0][0].text)
        assert "channel_id" in sql_text


class TestHybridSearch:
    @pytest.mark.asyncio
    async def test_returns_rrf_scored_results(self):
        row = _make_row(
            id=uuid.uuid4(),
            video_id=uuid.uuid4(),
            video_title="Hybrid Result",
            chunk_text="combined search result",
            start_time=5.0,
            end_time=15.0,
            speaker="SPEAKER_01",
            rrf_score=0.0328,
        )
        db = _make_mock_db([row])

        results = await _hybrid_search(
            db, "combined search", [0.1] * 768, limit=10, channel_id=None
        )
        assert len(results) == 1
        assert results[0]["video_title"] == "Hybrid Result"
        assert results[0]["similarity"] == 0.0328

    @pytest.mark.asyncio
    async def test_sql_contains_rrf_logic(self):
        db = _make_mock_db([])
        await _hybrid_search(db, "test", [0.1] * 768, limit=5, channel_id=None)
        sql_text = str(db.execute.call_args[0][0].text)
        assert "vector_rank" in sql_text
        assert "keyword_rank" in sql_text
        assert "rrf_k" in sql_text

    @pytest.mark.asyncio
    async def test_custom_rrf_k(self):
        db = _make_mock_db([])
        await _hybrid_search(db, "test", [0.1] * 768, limit=5, channel_id=None, rrf_k=30)
        call_params = db.execute.call_args[0][1]
        assert call_params["rrf_k"] == 30

    @pytest.mark.asyncio
    async def test_with_channel_filter(self):
        db = _make_mock_db([])
        cid = uuid.uuid4()
        await _hybrid_search(db, "test", [0.1] * 768, limit=5, channel_id=cid)
        sql_text = str(db.execute.call_args[0][0].text)
        assert "channel_id" in sql_text


class TestSemanticSearchDispatch:
    """Test that semantic_search dispatches to the correct search mode."""

    @pytest.mark.asyncio
    async def test_vector_mode(self):
        db = _make_mock_db([])
        results = await semantic_search(
            db, [0.1] * 768, limit=10, search_mode="vector"
        )
        assert results == []
        # Should call db.execute with vector-only SQL (no tsquery)
        sql_text = str(db.execute.call_args[0][0].text)
        assert "plainto_tsquery" not in sql_text

    @pytest.mark.asyncio
    async def test_keyword_mode(self):
        db = _make_mock_db([])
        results = await semantic_search(
            db, [0.1] * 768, limit=10, query="test", search_mode="keyword"
        )
        assert results == []
        sql_text = str(db.execute.call_args[0][0].text)
        assert "plainto_tsquery" in sql_text
        # Should NOT contain vector distance operator
        assert "<=>" not in sql_text

    @pytest.mark.asyncio
    async def test_hybrid_mode(self):
        db = _make_mock_db([])
        results = await semantic_search(
            db, [0.1] * 768, limit=10, query="test", search_mode="hybrid"
        )
        assert results == []
        sql_text = str(db.execute.call_args[0][0].text)
        assert "vector_rank" in sql_text
        assert "keyword_rank" in sql_text

    @pytest.mark.asyncio
    async def test_hybrid_falls_back_to_vector_without_query(self):
        """Hybrid mode falls back to vector if no query text is provided."""
        db = _make_mock_db([])
        results = await semantic_search(
            db, [0.1] * 768, limit=10, search_mode="hybrid"
        )
        assert results == []
        sql_text = str(db.execute.call_args[0][0].text)
        # Should have used vector search, not hybrid
        assert "vector_rank" not in sql_text
        assert "<=>" in sql_text

    @pytest.mark.asyncio
    async def test_keyword_falls_back_to_vector_without_query(self):
        """Keyword mode falls back to vector if no query text is provided."""
        db = _make_mock_db([])
        results = await semantic_search(
            db, [0.1] * 768, limit=10, search_mode="keyword"
        )
        assert results == []
        sql_text = str(db.execute.call_args[0][0].text)
        assert "plainto_tsquery" not in sql_text

    @pytest.mark.asyncio
    @patch("app.services.search.settings")
    async def test_uses_settings_default(self, mock_settings):
        mock_settings.search_mode = "vector"
        db = _make_mock_db([])
        await semantic_search(db, [0.1] * 768, limit=10)
        sql_text = str(db.execute.call_args[0][0].text)
        assert "plainto_tsquery" not in sql_text

    @pytest.mark.asyncio
    @patch("app.services.search.settings")
    async def test_override_trumps_settings(self, mock_settings):
        mock_settings.search_mode = "vector"
        db = _make_mock_db([])
        await semantic_search(
            db, [0.1] * 768, limit=10, query="test", search_mode="keyword"
        )
        sql_text = str(db.execute.call_args[0][0].text)
        assert "plainto_tsquery" in sql_text


class TestConfigSearchMode:
    """Test search_mode config setting."""

    def test_default_is_hybrid(self):
        from app.config import Settings
        s = Settings(database_url="x", database_url_sync="x", redis_url="x")
        assert s.search_mode == "hybrid"

    def test_overridable(self):
        from app.config import Settings
        s = Settings(database_url="x", database_url_sync="x", redis_url="x", search_mode="vector")
        assert s.search_mode == "vector"

    def test_keyword_mode(self):
        from app.config import Settings
        s = Settings(database_url="x", database_url_sync="x", redis_url="x", search_mode="keyword")
        assert s.search_mode == "keyword"
