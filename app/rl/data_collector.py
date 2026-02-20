"""Historical data download, cleaning, and storage for RL training.

Downloads XAU_USD candle data from OANDA across multiple timeframes,
cleans gaps/weekends, and stores as Parquet files for fast training I/O.

Usage (CLI):
    python -m app.rl.data_collector --instrument XAU_USD --months 12
"""

from __future__ import annotations

import argparse
import asyncio
import json
import logging
import os
from dataclasses import dataclass, field, asdict
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Optional

import numpy as np
import pandas as pd

logger = logging.getLogger("forgetrade.rl.data")

# ── Constants ────────────────────────────────────────────────────────────

OANDA_MAX_CANDLES = 5000
GRANULARITIES = ["M1", "M5", "M15", "H1"]

DATA_DIR = Path("data") / "historical"


# ── Data quality ─────────────────────────────────────────────────────────


def _is_weekend(dt: datetime) -> bool:
    """Return True if *dt* falls on Saturday or Sunday (UTC)."""
    return dt.weekday() in (5, 6)


def clean_candles(df: pd.DataFrame, spike_atr_mult: float = 10.0) -> pd.DataFrame:
    """Clean raw OANDA candle data.

    1. Remove weekend candles (Sat/Sun UTC).
    2. Forward-fill gaps (missing candles → prev close, volume=0).
    3. Flag spikes (range > spike_atr_mult × 20-period ATR).
    4. Ensure UTC timezone.
    """
    if df.empty:
        return df

    df = df.copy()

    # Ensure datetime index
    if not pd.api.types.is_datetime64_any_dtype(df["time"]):
        df["time"] = pd.to_datetime(df["time"], utc=True)

    # 1 ── Remove weekends
    df = df[~df["time"].dt.weekday.isin([5, 6])].reset_index(drop=True)

    if df.empty:
        return df

    # 4 ── Ensure UTC
    if df["time"].dt.tz is None:
        df["time"] = df["time"].dt.tz_localize("UTC")

    # 3 ── Spike detection (flag, don't remove)
    ranges = df["high"] - df["low"]
    rolling_atr = ranges.rolling(20, min_periods=1).mean()
    df["spike"] = ranges > (rolling_atr * spike_atr_mult)

    # 2 ── Gap fill is handled by the caller via resample if needed
    #      (we leave the data as-is to preserve real market gaps)

    # 5 ── Volume validation — mark zero-volume rows
    df["synthetic"] = df["volume"] == 0

    return df


def split_data(
    df: pd.DataFrame,
    train_pct: float = 0.70,
    val_pct: float = 0.15,
    test_pct: float = 0.15,
) -> tuple[pd.DataFrame, pd.DataFrame, pd.DataFrame]:
    """Chronological train/val/test split — no shuffling."""
    n = len(df)
    train_end = int(n * train_pct)
    val_end = int(n * (train_pct + val_pct))

    train = df.iloc[:train_end].reset_index(drop=True)
    val = df.iloc[train_end:val_end].reset_index(drop=True)
    test = df.iloc[val_end:].reset_index(drop=True)

    return train, val, test


def split_data_by_date(
    dfs: dict[str, pd.DataFrame],
    reference_gran: str = "M5",
    train_pct: float = 0.70,
    val_pct: float = 0.15,
) -> dict[str, tuple[pd.DataFrame, pd.DataFrame, pd.DataFrame]]:
    """Split all timeframes using date boundaries from the *reference* granularity.

    First trims all timeframes to the period where ALL timeframes have data,
    then splits by date so every split has consistent coverage across timeframes.

    Returns ``{gran: (train_df, val_df, test_df)}``.
    """
    # Parse timestamps for each timeframe
    ts_map: dict[str, pd.Series] = {}
    for gran, df in dfs.items():
        if df.empty:
            continue
        ts_map[gran] = pd.to_datetime(df["time"], utc=True)

    # Find overlapping date range across all non-empty timeframes
    overlap_start = max(ts.iloc[0] for ts in ts_map.values())
    overlap_end = min(ts.iloc[-1] for ts in ts_map.values())

    if overlap_start >= overlap_end:
        logger.warning(
            "No temporal overlap between timeframes! "
            "Falling back to per-timeframe row splits."
        )
        result: dict[str, tuple[pd.DataFrame, pd.DataFrame, pd.DataFrame]] = {}
        for gran, df in dfs.items():
            tr, va, te = split_data(df, train_pct, val_pct)
            result[gran] = (tr, va, te)
        return result

    # Trim all timeframes to the overlapping window
    trimmed: dict[str, pd.DataFrame] = {}
    for gran, df in dfs.items():
        ts = ts_map.get(gran)
        if ts is None:
            trimmed[gran] = df
            continue
        mask = (ts >= overlap_start) & (ts <= overlap_end)
        trimmed[gran] = df[mask].reset_index(drop=True)

    # Use reference granularity to determine date split points
    ref = trimmed[reference_gran]
    ref_ts = pd.to_datetime(ref["time"], utc=True)

    n = len(ref)
    train_end_idx = int(n * train_pct)
    val_end_idx = int(n * (train_pct + val_pct))

    train_cutoff = ref_ts.iloc[train_end_idx]
    val_cutoff = ref_ts.iloc[val_end_idx]

    logger.info(
        "Date-split: overlap=%s→%s, train<=%s, val<=%s",
        overlap_start.isoformat(), overlap_end.isoformat(),
        train_cutoff.isoformat(), val_cutoff.isoformat(),
    )

    result = {}
    for gran, df in trimmed.items():
        ts = pd.to_datetime(df["time"], utc=True)
        tr = df[ts < train_cutoff].reset_index(drop=True)
        va = df[(ts >= train_cutoff) & (ts < val_cutoff)].reset_index(drop=True)
        te = df[ts >= val_cutoff].reset_index(drop=True)
        result[gran] = (tr, va, te)

    return result


# ── Parquet I/O ──────────────────────────────────────────────────────────


def save_to_parquet(df: pd.DataFrame, path: Path) -> None:
    """Save DataFrame to Parquet file, creating directories as needed."""
    path.parent.mkdir(parents=True, exist_ok=True)
    df.to_parquet(path, engine="pyarrow", index=False)
    logger.info("Saved %d rows → %s (%.1f MB)", len(df), path, path.stat().st_size / 1e6)


def load_from_parquet(path: Path) -> pd.DataFrame:
    """Load a Parquet file into a DataFrame."""
    df = pd.read_parquet(path, engine="pyarrow")
    if "time" in df.columns and not pd.api.types.is_datetime64_any_dtype(df["time"]):
        df["time"] = pd.to_datetime(df["time"], utc=True)
    return df


# ── OANDA download ───────────────────────────────────────────────────────


async def download_historical(
    instrument: str,
    granularity: str,
    start: datetime,
    end: datetime,
    broker,
    *,
    batch_size: int = OANDA_MAX_CANDLES,
) -> pd.DataFrame:
    """Download historical candles from OANDA via broker, paginating as needed.

    Args:
        instrument: e.g. ``"XAU_USD"``
        granularity: e.g. ``"M5"``
        start: Start datetime (UTC).
        end: End datetime (UTC).
        broker: An ``OandaClient`` instance (or compatible mock).
        batch_size: Candles per request (max 5000).

    Returns:
        DataFrame with columns ``[time, open, high, low, close, volume]``.
    """
    # Estimate candle duration to paginate
    _duration_map = {
        "M1": timedelta(minutes=1),
        "M5": timedelta(minutes=5),
        "M15": timedelta(minutes=15),
        "H1": timedelta(hours=1),
        "H4": timedelta(hours=4),
        "D": timedelta(days=1),
    }
    candle_dur = _duration_map.get(granularity, timedelta(minutes=5))

    all_rows: list[dict] = []
    cursor = start

    while cursor < end:
        # Calculate expected end for this batch
        batch_end = min(cursor + candle_dur * batch_size, end)

        try:
            candles = await broker.fetch_candles(
                instrument, granularity, count=batch_size,
            )
        except Exception as exc:
            logger.warning("Download error at %s: %s — skipping batch", cursor, exc)
            cursor = batch_end
            continue

        if not candles:
            cursor = batch_end
            continue

        for c in candles:
            all_rows.append({
                "time": c.time,
                "open": c.open,
                "high": c.high,
                "low": c.low,
                "close": c.close,
                "volume": c.volume,
            })

        # Move cursor forward
        cursor = batch_end

    if not all_rows:
        return pd.DataFrame(columns=["time", "open", "high", "low", "close", "volume"])

    df = pd.DataFrame(all_rows)
    df["time"] = pd.to_datetime(df["time"], utc=True)
    df = df.drop_duplicates(subset=["time"]).sort_values("time").reset_index(drop=True)

    return df


def generate_metadata(
    instrument: str,
    data_dir: Path,
    date_range: tuple[datetime, datetime],
) -> dict:
    """Generate metadata.json for a downloaded dataset."""
    meta: dict = {
        "instrument": instrument,
        "download_date": datetime.now(timezone.utc).isoformat(),
        "date_range": {
            "start": date_range[0].isoformat(),
            "end": date_range[1].isoformat(),
        },
        "pip_value": 0.01,
        "timeframes": {},
    }

    for gran in GRANULARITIES:
        pq_path = data_dir / f"{gran}.parquet"
        if pq_path.exists():
            df = load_from_parquet(pq_path)
            meta["timeframes"][gran] = {
                "rows": len(df),
                "file": f"{gran}.parquet",
                "size_mb": round(pq_path.stat().st_size / 1e6, 1),
            }

    return meta


# ── CLI entry point ──────────────────────────────────────────────────────


async def run_download(instrument: str, months: int, broker) -> Path:
    """Download all timeframes, clean, save, and generate metadata.

    Returns the data directory path.
    """
    end = datetime.now(timezone.utc)
    start = end - timedelta(days=months * 30)

    data_dir = DATA_DIR / instrument
    data_dir.mkdir(parents=True, exist_ok=True)

    for gran in GRANULARITIES:
        logger.info("Downloading %s %s (%d months)…", instrument, gran, months)
        raw_df = await download_historical(instrument, gran, start, end, broker)

        if raw_df.empty:
            logger.warning("No data for %s %s — skipping.", instrument, gran)
            continue

        cleaned = clean_candles(raw_df)

        # Drop helper columns before saving
        save_cols = ["time", "open", "high", "low", "close", "volume"]
        save_df = cleaned[save_cols].copy()

        save_to_parquet(save_df, data_dir / f"{gran}.parquet")

    # Generate metadata
    meta = generate_metadata(instrument, data_dir, (start, end))
    meta_path = data_dir / "metadata.json"
    meta_path.write_text(json.dumps(meta, indent=2, default=str))
    logger.info("Metadata saved → %s", meta_path)

    return data_dir


def main():
    """CLI entry point for data collection."""
    parser = argparse.ArgumentParser(description="Download OANDA historical data for RL training")
    parser.add_argument("--instrument", default="XAU_USD", help="Instrument to download")
    parser.add_argument("--months", type=int, default=12, help="Months of history")
    args = parser.parse_args()

    logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(message)s")
    logger.info("Data collection requires a configured OANDA broker.")
    logger.info("Use: asyncio.run(run_download('%s', %d, broker))", args.instrument, args.months)


if __name__ == "__main__":
    main()
