"""ForgeTrade — application entry point.

Boots the FastAPI internal server and provides the CLI entry point for
paper, live, and backtest modes.
"""

import logging
import os

from fastapi import FastAPI
from fastapi.responses import RedirectResponse
from fastapi.staticfiles import StaticFiles

from app.api.routers import router

app = FastAPI(title="ForgeTrade Internal API", version="0.1.0")
app.include_router(router)

# ── Static files (dashboard) ────────────────────────────────────────────

_static_dir = os.path.join(os.path.dirname(__file__), "static")
if os.path.isdir(_static_dir):
    app.mount("/dashboard", StaticFiles(directory=_static_dir), name="dashboard")

logger = logging.getLogger("forgetrade")


@app.get("/health")
async def health():
    """Health check required by Forge verification gates."""
    return {"status": "ok"}


@app.get("/")
async def root_redirect():
    """Redirect root to the dashboard."""
    return RedirectResponse(url="/dashboard/index.html", status_code=307)


def warn_if_live(mode: str) -> bool:
    """Log a prominent warning when running in live mode.

    Returns ``True`` if *mode* is ``"live"``.
    """
    if mode == "live":
        logger.warning(
            "LIVE TRADING MODE — Real money at risk! Starting in 5 seconds..."
        )
        return True
    return False


# ── CLI ──────────────────────────────────────────────────────────────────


def _run_cli() -> None:
    """Parse CLI arguments and dispatch to the appropriate mode."""
    import argparse
    import asyncio
    import time

    from app.broker.oanda_client import OandaClient
    from app.config import load_config, load_streams
    from app.engine_manager import EngineManager
    from app.repos.db import init_db

    parser = argparse.ArgumentParser(description="ForgeTrade trading bot")
    parser.add_argument(
        "--mode",
        choices=["paper", "live", "backtest"],
        default="paper",
        help="Trading mode (default: paper)",
    )
    parser.add_argument("--start", help="Backtest start date (YYYY-MM-DD)")
    parser.add_argument("--end", help="Backtest end date (YYYY-MM-DD)")
    args = parser.parse_args()

    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
    )

    config = load_config()
    init_db(config.db_path)

    if warn_if_live(args.mode):
        time.sleep(5)

    broker = OandaClient(config)

    streams = load_streams()
    manager = EngineManager(config=config, broker=broker, streams=streams)
    manager.build_engines()

    # Inject broker into routers for /positions endpoint
    from app.api.routers import configure_routers, update_bot_status
    from app.repos.trade_repo import TradeRepo

    trade_repo = TradeRepo(config.db_path)
    configure_routers(trade_repo=trade_repo, broker=broker)

    # Push initial status so the dashboard shows streams immediately
    for sname in manager.stream_names:
        eng = manager.engines[sname]
        update_bot_status(
            stream_name=sname,
            mode=args.mode,
            pair=eng.instrument,
            running=False,
        )

    import signal

    def handle_shutdown(signum, frame):
        logger.info("Shutdown signal received — stopping gracefully.")
        manager.stop_all()

    signal.signal(signal.SIGINT, handle_shutdown)

    if args.mode == "backtest":
        _run_backtest(config, broker, args.start, args.end)
    else:
        asyncio.run(_run_engine_manager(manager, args.mode))


async def _run_engine_manager(manager, mode: str, port: int = 8080) -> None:
    """Start the API server and all trading streams concurrently."""
    import asyncio
    import uvicorn

    logger.info("Starting ForgeTrade in %s mode with %d stream(s).",
                mode, len(manager.stream_names))

    uvi_config = uvicorn.Config(
        app,
        host="0.0.0.0",
        port=port,
        log_level="info",
    )
    server = uvicorn.Server(uvi_config)

    async def _run_server():
        await server.serve()

    async def _run_engines():
        await manager.run_all()

    logger.info("Dashboard available at http://localhost:%d", port)
    results = await asyncio.gather(
        _run_server(),
        _run_engines(),
        return_exceptions=True,
    )
    logger.info("ForgeTrade stopped. Results: %s", results)


def _run_backtest(config, broker, start_date, end_date) -> None:
    """Fetch historical candles and run a backtest."""
    import asyncio

    from app.backtest.engine import BacktestEngine
    from app.backtest.stats import calculate_stats
    from app.repos.backtest_repo import BacktestRepo
    from app.strategy.models import CandleData

    async def _fetch_and_run():
        daily_raw = await broker.fetch_candles(config.trade_pair, "D", count=500)
        h4_raw = await broker.fetch_candles(config.trade_pair, "H4", count=5000)
        daily = [
            CandleData(c.time, c.open, c.high, c.low, c.close, c.volume)
            for c in daily_raw
        ]
        h4 = [
            CandleData(c.time, c.open, c.high, c.low, c.close, c.volume)
            for c in h4_raw
        ]
        bt = BacktestEngine(config)
        result = bt.run(daily, h4)
        stats = calculate_stats(result["trades"])
        repo = BacktestRepo(config.db_path)
        repo.insert_run(
            pair=config.trade_pair,
            start_date=start_date or "unknown",
            end_date=end_date or "unknown",
            stats=stats,
        )
        logger.info(
            "Backtest complete: %d trades, PnL: $%.2f, Win rate: %.1f%%",
            stats["total_trades"],
            stats["net_pnl"],
            stats["win_rate"] * 100,
        )

    asyncio.run(_fetch_and_run())


if __name__ == "__main__":
    _run_cli()
