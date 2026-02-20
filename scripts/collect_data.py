"""One-shot script to download historical data for ForgeAgent training.

Usage (from Forge/ directory):
    python -m scripts.collect_data --instrument XAU_USD --months 12
"""

import argparse
import asyncio
import logging
import sys
from pathlib import Path

# Ensure project root is on path
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from app.config import load_config
from app.broker.oanda_client import OandaClient
from app.rl.data_collector import run_download


async def _main(instrument: str, months: int) -> None:
    config = load_config()
    broker = OandaClient(config)
    data_dir = await run_download(instrument, months, broker)
    logging.getLogger(__name__).info("Done → %s", data_dir)


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Download OANDA data for RL training")
    parser.add_argument("--instrument", default="XAU_USD")
    parser.add_argument("--months", type=int, default=12)
    args = parser.parse_args()

    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s [%(levelname)s] %(message)s",
    )

    asyncio.run(_main(args.instrument, args.months))
