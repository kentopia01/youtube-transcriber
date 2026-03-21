"""Tests for the LLM cost tracker service."""
from unittest.mock import MagicMock, patch

import pytest

from app.services.cost_tracker import (
    BudgetExceededError,
    check_budget,
    estimate_cost,
    get_today_cost,
    record_usage,
)


class TestEstimateCost:
    def test_haiku_rates(self):
        cost = estimate_cost("claude-haiku-4-5", 1_000_000, 1_000_000)
        assert cost == pytest.approx(4.80)  # $0.80 + $4.00

    def test_sonnet_rates(self):
        cost = estimate_cost("claude-sonnet-4-5", 1_000_000, 1_000_000)
        assert cost == pytest.approx(18.00)  # $3.00 + $15.00

    def test_unknown_model_defaults_to_sonnet_rates(self):
        cost = estimate_cost("claude-unknown-model", 1_000_000, 1_000_000)
        assert cost == pytest.approx(18.00)

    def test_small_call_cost(self):
        # 1000 input + 200 output tokens with haiku
        cost = estimate_cost("claude-haiku-4-5", 1000, 200)
        expected = (1000 * 0.80 + 200 * 4.00) / 1_000_000
        assert cost == pytest.approx(expected)

    def test_zero_tokens(self):
        cost = estimate_cost("claude-haiku-4-5", 0, 0)
        assert cost == 0.0


class TestRecordUsage:
    def test_record_usage_inserts_row(self):
        mock_session = MagicMock()
        mock_session.__enter__ = MagicMock(return_value=mock_session)
        mock_session.__exit__ = MagicMock(return_value=False)
        mock_engine = MagicMock()
        mock_engine.connect.return_value = mock_session

        with patch("app.services.cost_tracker._get_engine") as mock_get_engine:
            mock_get_engine.return_value = mock_engine
            with patch("app.services.cost_tracker.Session") as mock_session_cls:
                mock_db = MagicMock()
                mock_session_cls.return_value.__enter__ = MagicMock(return_value=mock_db)
                mock_session_cls.return_value.__exit__ = MagicMock(return_value=False)

                record_usage("claude-haiku-4-5", 500, 100)

                mock_db.execute.assert_called_once()
                mock_db.commit.assert_called_once()

    def test_record_usage_survives_db_error(self):
        """record_usage should not raise even if the DB is unreachable."""
        with patch("app.services.cost_tracker._get_engine") as mock_get_engine:
            mock_get_engine.side_effect = Exception("DB unreachable")
            # Should not raise
            record_usage("claude-haiku-4-5", 100, 50)


class TestGetTodayCost:
    def test_returns_float_from_db(self):
        with patch("app.services.cost_tracker.Session") as mock_session_cls:
            with patch("app.services.cost_tracker._get_engine"):
                mock_db = MagicMock()
                mock_db.execute.return_value.scalar.return_value = 1.234567
                mock_session_cls.return_value.__enter__ = MagicMock(return_value=mock_db)
                mock_session_cls.return_value.__exit__ = MagicMock(return_value=False)

                result = get_today_cost()
                assert result == pytest.approx(1.234567)

    def test_returns_zero_on_db_error(self):
        with patch("app.services.cost_tracker._get_engine") as mock_get_engine:
            mock_get_engine.side_effect = Exception("DB down")
            result = get_today_cost()
            assert result == 0.0

    def test_returns_zero_when_no_rows(self):
        with patch("app.services.cost_tracker.Session") as mock_session_cls:
            with patch("app.services.cost_tracker._get_engine"):
                mock_db = MagicMock()
                mock_db.execute.return_value.scalar.return_value = None
                mock_session_cls.return_value.__enter__ = MagicMock(return_value=mock_db)
                mock_session_cls.return_value.__exit__ = MagicMock(return_value=False)

                result = get_today_cost()
                assert result == 0.0


class TestCheckBudget:
    def test_passes_when_under_budget(self):
        with patch("app.services.cost_tracker.get_today_cost", return_value=2.50):
            with patch("app.services.cost_tracker.settings") as mock_settings:
                mock_settings.daily_llm_budget_usd = 5.0
                # Should not raise
                check_budget()

    def test_raises_when_over_budget(self):
        with patch("app.services.cost_tracker.get_today_cost", return_value=5.01):
            with patch("app.services.cost_tracker.settings") as mock_settings:
                mock_settings.daily_llm_budget_usd = 5.0
                with pytest.raises(BudgetExceededError):
                    check_budget()

    def test_raises_when_exactly_at_budget(self):
        with patch("app.services.cost_tracker.get_today_cost", return_value=5.0):
            with patch("app.services.cost_tracker.settings") as mock_settings:
                mock_settings.daily_llm_budget_usd = 5.0
                with pytest.raises(BudgetExceededError):
                    check_budget()

    def test_skips_check_when_budget_is_zero(self):
        """Budget of 0 disables enforcement."""
        with patch("app.services.cost_tracker.get_today_cost", return_value=999.0):
            with patch("app.services.cost_tracker.settings") as mock_settings:
                mock_settings.daily_llm_budget_usd = 0
                # Should not raise
                check_budget()

    def test_error_message_includes_amounts(self):
        with patch("app.services.cost_tracker.get_today_cost", return_value=7.50):
            with patch("app.services.cost_tracker.settings") as mock_settings:
                mock_settings.daily_llm_budget_usd = 5.0
                with pytest.raises(BudgetExceededError, match="5.00"):
                    check_budget()
