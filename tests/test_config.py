"""Tests for app.config — environment variable loading and validation."""

import os

import pytest

from app.config import Config, load_config


@pytest.fixture(autouse=True)
def _clean_env(monkeypatch):
    """Ensure OANDA env vars are cleared between tests."""
    for var in [
        "OANDA_ACCOUNT_ID",
        "OANDA_API_TOKEN",
        "OANDA_ENVIRONMENT",
        "TRADE_PAIR",
        "RISK_PER_TRADE_PCT",
        "MAX_DRAWDOWN_PCT",
        "SESSION_START_UTC",
        "SESSION_END_UTC",
        "DB_PATH",
        "LOG_LEVEL",
        "HEALTH_PORT",
    ]:
        monkeypatch.delenv(var, raising=False)


def _set_required(monkeypatch):
    """Set the minimum required environment variables."""
    monkeypatch.setenv("OANDA_ACCOUNT_ID", "101-001-12345678-001")
    monkeypatch.setenv("OANDA_API_TOKEN", "test-token-abc123")
    monkeypatch.setenv("OANDA_ENVIRONMENT", "practice")


class TestLoadConfig:
    def test_loads_required_vars(self, monkeypatch):
        _set_required(monkeypatch)
        cfg = load_config()
        assert cfg.oanda_account_id == "101-001-12345678-001"
        assert cfg.oanda_api_token == "test-token-abc123"
        assert cfg.oanda_environment == "practice"

    def test_defaults(self, monkeypatch):
        _set_required(monkeypatch)
        cfg = load_config()
        assert cfg.trade_pair == "EUR_USD"
        assert cfg.risk_per_trade_pct == 1.0
        assert cfg.max_drawdown_pct == 10.0
        assert cfg.session_start_utc == 7
        assert cfg.session_end_utc == 21
        assert cfg.db_path == "data/forgetrade.db"
        assert cfg.log_level == "INFO"
        assert cfg.health_port == 8080

    def test_config_missing_var(self, monkeypatch, tmp_path):
        # Only set one of three required vars; use a non-existent env_path
        # so load_dotenv doesn't re-populate from the real .env file
        monkeypatch.setenv("OANDA_ACCOUNT_ID", "test-id")
        with pytest.raises(ValueError, match="OANDA_API_TOKEN"):
            load_config(env_path=str(tmp_path / "nonexistent.env"))

    def test_environment_switching_practice(self, monkeypatch):
        _set_required(monkeypatch)
        cfg = load_config()
        assert cfg.oanda_base_url == "https://api-fxpractice.oanda.com"

    def test_environment_switching_live(self, monkeypatch):
        _set_required(monkeypatch)
        monkeypatch.setenv("OANDA_ENVIRONMENT", "live")
        cfg = load_config()
        assert cfg.oanda_base_url == "https://api-fxtrade.oanda.com"
