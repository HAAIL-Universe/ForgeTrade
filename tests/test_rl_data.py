"""Tests for app.rl.data_collector — data download, cleaning, storage."""

import pandas as pd
import pytest

from app.rl.data_collector import clean_candles, split_data, save_to_parquet, load_from_parquet, generate_metadata


@pytest.fixture
def sample_df():
    """Create a sample DataFrame mimicking OANDA candle data."""
    rows = []
    base_time = pd.Timestamp("2025-06-02 08:00:00", tz="UTC")  # Monday
    for i in range(100):
        t = base_time + pd.Timedelta(minutes=5 * i)
        rows.append({
            "time": t,
            "open": 5000.0 + i * 0.1,
            "high": 5000.5 + i * 0.1,
            "low": 4999.5 + i * 0.1,
            "close": 5000.2 + i * 0.1,
            "volume": 100 + i,
        })
    return pd.DataFrame(rows)


@pytest.fixture
def weekend_df():
    """DataFrame with weekend candles that should be removed."""
    rows = []
    # Friday data
    for i in range(5):
        rows.append({
            "time": pd.Timestamp(f"2025-06-06 {10+i}:00:00", tz="UTC"),
            "open": 5000.0, "high": 5001.0, "low": 4999.0, "close": 5000.5,
            "volume": 100,
        })
    # Saturday data (should be removed)
    for i in range(3):
        rows.append({
            "time": pd.Timestamp(f"2025-06-07 {10+i}:00:00", tz="UTC"),
            "open": 5000.0, "high": 5001.0, "low": 4999.0, "close": 5000.5,
            "volume": 0,
        })
    # Sunday data (should be removed)
    for i in range(3):
        rows.append({
            "time": pd.Timestamp(f"2025-06-08 {10+i}:00:00", tz="UTC"),
            "open": 5000.0, "high": 5001.0, "low": 4999.0, "close": 5000.5,
            "volume": 0,
        })
    # Monday data
    for i in range(5):
        rows.append({
            "time": pd.Timestamp(f"2025-06-09 {10+i}:00:00", tz="UTC"),
            "open": 5000.0, "high": 5001.0, "low": 4999.0, "close": 5000.5,
            "volume": 100,
        })
    return pd.DataFrame(rows)


class TestCleanCandles:
    def test_removes_weekend_candles(self, weekend_df):
        cleaned = clean_candles(weekend_df)
        # Should have 10 (5 Friday + 5 Monday), not 16
        assert len(cleaned) == 10

    def test_no_saturday_or_sunday(self, weekend_df):
        cleaned = clean_candles(weekend_df)
        weekdays = cleaned["time"].dt.weekday
        assert not weekdays.isin([5, 6]).any()

    def test_spike_detection(self, sample_df):
        df = sample_df.copy()
        # Inject a massive spike
        df.loc[50, "high"] = 6000.0
        df.loc[50, "low"] = 4000.0
        cleaned = clean_candles(df, spike_atr_mult=5.0)
        assert cleaned["spike"].iloc[50]

    def test_utc_timezone(self, sample_df):
        cleaned = clean_candles(sample_df)
        assert cleaned["time"].dt.tz is not None

    def test_empty_dataframe(self):
        empty = pd.DataFrame(columns=["time", "open", "high", "low", "close", "volume"])
        result = clean_candles(empty)
        assert result.empty


class TestSplitData:
    def test_default_proportions(self, sample_df):
        train, val, test = split_data(sample_df)
        assert len(train) == 70
        assert len(val) == 15
        assert len(test) == 15

    def test_custom_proportions(self, sample_df):
        train, val, test = split_data(sample_df, 0.60, 0.20, 0.20)
        assert len(train) == 60
        assert len(val) == 20
        assert len(test) == 20

    def test_chronological_order(self, sample_df):
        train, val, test = split_data(sample_df)
        # First row of val should be after last row of train
        if "time" in train.columns:
            assert train["time"].iloc[-1] <= val["time"].iloc[0]
            assert val["time"].iloc[-1] <= test["time"].iloc[0]

    def test_no_overlap(self, sample_df):
        train, val, test = split_data(sample_df)
        assert len(train) + len(val) + len(test) == len(sample_df)


class TestParquetIO:
    def test_round_trip(self, sample_df, tmp_path):
        path = tmp_path / "test.parquet"
        save_to_parquet(sample_df, path)
        loaded = load_from_parquet(path)
        assert len(loaded) == len(sample_df)
        assert list(loaded.columns) == list(sample_df.columns)

    def test_creates_directories(self, sample_df, tmp_path):
        path = tmp_path / "nested" / "deep" / "test.parquet"
        save_to_parquet(sample_df, path)
        assert path.exists()

    def test_schema_preserved(self, sample_df, tmp_path):
        path = tmp_path / "test.parquet"
        save_to_parquet(sample_df, path)
        loaded = load_from_parquet(path)
        assert loaded["open"].dtype == sample_df["open"].dtype
