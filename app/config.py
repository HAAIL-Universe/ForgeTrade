"""ForgeTrade — application configuration.

Loads .env variables into a typed config object.
Validates required variables on startup.
"""

import os
from dataclasses import dataclass

from dotenv import load_dotenv


_REQUIRED_VARS = [
    "OANDA_ACCOUNT_ID",
    "OANDA_API_TOKEN",
    "OANDA_ENVIRONMENT",
]


@dataclass(frozen=True)
class Config:
    """Typed configuration loaded from environment variables."""

    oanda_account_id: str
    oanda_api_token: str
    oanda_environment: str  # "practice" or "live"
    trade_pair: str
    risk_per_trade_pct: float
    max_drawdown_pct: float
    session_start_utc: int
    session_end_utc: int
    db_path: str
    log_level: str
    health_port: int

    @property
    def oanda_base_url(self) -> str:
        """Return the OANDA v20 API base URL based on environment."""
        if self.oanda_environment == "live":
            return "https://api-fxtrade.oanda.com"
        return "https://api-fxpractice.oanda.com"


def load_config(env_path: str | None = None) -> Config:
    """Load configuration from environment variables.

    Raises ``ValueError`` with a message naming the missing variable when a
    required variable is absent.
    """
    load_dotenv(dotenv_path=env_path)

    missing = [v for v in _REQUIRED_VARS if not os.environ.get(v)]
    if missing:
        raise ValueError(
            f"Missing required environment variable(s): {', '.join(missing)}"
        )

    return Config(
        oanda_account_id=os.environ["OANDA_ACCOUNT_ID"],
        oanda_api_token=os.environ["OANDA_API_TOKEN"],
        oanda_environment=os.environ.get("OANDA_ENVIRONMENT", "practice"),
        trade_pair=os.environ.get("TRADE_PAIR", "EUR_USD"),
        risk_per_trade_pct=float(os.environ.get("RISK_PER_TRADE_PCT", "1.0")),
        max_drawdown_pct=float(os.environ.get("MAX_DRAWDOWN_PCT", "10.0")),
        session_start_utc=int(os.environ.get("SESSION_START_UTC", "7")),
        session_end_utc=int(os.environ.get("SESSION_END_UTC", "21")),
        db_path=os.environ.get("DB_PATH", "data/forgetrade.db"),
        log_level=os.environ.get("LOG_LEVEL", "INFO"),
        health_port=int(os.environ.get("HEALTH_PORT", "8080")),
    )
