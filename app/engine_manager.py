"""EngineManager — orchestrates multiple TradingEngine streams concurrently.

Each enabled stream in ``forge.json`` (or synthesised from env) gets its own
``TradingEngine`` with an independently resolved strategy.  Streams run as
concurrent ``asyncio`` tasks and can be started / stopped individually or
en masse.
"""

import asyncio
import logging
from typing import Optional

from app.broker.oanda_client import OandaClient
from app.config import Config
from app.engine import TradingEngine
from app.models.stream_config import StreamConfig
from app.strategy.registry import get_strategy

logger = logging.getLogger("forgetrade.engine_manager")


class EngineManager:
    """Lifecycle manager for one-or-many trading streams.

    Args:
        config:  Global ``Config`` loaded from ``.env``.
        broker:  Shared ``OandaClient`` instance.
        streams: List of ``StreamConfig`` items (may already be filtered
                 for ``enabled``).
    """

    def __init__(
        self,
        config: Config,
        broker: OandaClient,
        streams: list[StreamConfig],
    ) -> None:
        self._config = config
        self._broker = broker
        self._streams = [s for s in streams if s.enabled]
        self._engines: dict[str, TradingEngine] = {}
        self._tasks: dict[str, asyncio.Task] = {}

    # ── Public API ───────────────────────────────────────────────────────

    @property
    def engines(self) -> dict[str, TradingEngine]:
        """Map of stream-name → ``TradingEngine``."""
        return dict(self._engines)

    @property
    def stream_names(self) -> list[str]:
        """Names of active (enabled) streams."""
        return list(self._engines.keys())

    def build_engines(self) -> None:
        """Instantiate a ``TradingEngine`` per enabled stream.

        Call **once** before :meth:`run_all`.  Each engine is constructed
        with the strategy resolved from the stream's ``strategy`` key via
        the strategy registry.
        """
        for stream in self._streams:
            strategy = get_strategy(stream.strategy)
            engine = TradingEngine(
                config=self._config,
                broker=self._broker,
                strategy=strategy,
                stream_config=stream,
            )
            self._engines[stream.name] = engine
            logger.info(
                "Registered stream '%s' → %s on %s",
                stream.name,
                stream.strategy,
                stream.instrument,
            )

    async def initialize_all(self) -> None:
        """Call ``initialize()`` on every engine."""
        for name, engine in self._engines.items():
            await engine.initialize()
            logger.info("Initialised stream '%s'.", name)

    async def run_all(self) -> dict[str, list[dict]]:
        """Launch all streams concurrently and wait for them to finish.

        Returns:
            ``{stream_name: [cycle_results]}`` for every stream.
        """
        if not self._engines:
            self.build_engines()

        await self.initialize_all()

        async def _run_stream(name: str, engine: TradingEngine):
            logger.info("Starting stream '%s'.", name)
            return await engine.run()

        tasks = {
            name: asyncio.create_task(_run_stream(name, eng))
            for name, eng in self._engines.items()
        }
        self._tasks = tasks

        results: dict[str, list[dict]] = {}
        for name, task in tasks.items():
            try:
                results[name] = await task
            except Exception as exc:  # pragma: no cover
                logger.error("Stream '%s' crashed: %s", name, exc)
                results[name] = [{"action": "error", "reason": str(exc)}]

        return results

    def stop_all(self) -> None:
        """Signal every engine to stop gracefully."""
        for name, engine in self._engines.items():
            engine.stop()
            logger.info("Stop signal sent to stream '%s'.", name)

    def stop_stream(self, name: str) -> None:
        """Stop a single stream by name."""
        engine = self._engines.get(name)
        if engine:
            engine.stop()
            logger.info("Stop signal sent to stream '%s'.", name)

    def get_status(self, name: Optional[str] = None) -> dict:
        """Return aggregated or per-stream status.

        Args:
            name: If given, return status for that stream only.

        Returns:
            Dict with per-stream engine metadata.
        """
        if name is not None:
            engine = self._engines.get(name)
            if engine is None:
                return {"error": f"Unknown stream: {name}"}
            return {
                "stream_name": name,
                "instrument": engine.instrument,
                "running": engine._running,
                "cycle_count": engine._cycle_count,
            }

        return {
            "streams": {
                n: {
                    "instrument": eng.instrument,
                    "running": eng._running,
                    "cycle_count": eng._cycle_count,
                }
                for n, eng in self._engines.items()
            }
        }
