"""Tests for loading files and detecting columns."""

from pathlib import Path

import pandas as pd
import pytest

from purpleair_visualizer.data import (
    detect_pm25_column,
    detect_time_column,
    load_csv,
    numeric_columns,
    parse_times,
    sorted_by_time,
)


def test_load_falls_back_to_cp1252(tmp_path: Path) -> None:
    path = tmp_path / "degrees.csv"
    path.write_bytes("temp°F\n1\n".encode("cp1252"))
    assert list(load_csv(path).columns) == ["temp°F"]


def test_detects_purpleair_columns() -> None:
    df = pd.DataFrame(columns=["sensor_uptime", "time_stamp", "humidity", "pm2.5_cf_1"])
    assert detect_time_column(df) == "time_stamp"
    assert detect_pm25_column(df) == "pm2.5_cf_1"


def test_uptime_is_not_a_time_column() -> None:
    df = pd.DataFrame({"uptime": [1], "humidity": [2]})
    assert detect_time_column(df) is None
    assert numeric_columns(df) == ["uptime", "humidity"]


def test_no_pm_column_returns_none() -> None:
    assert detect_pm25_column(pd.DataFrame(columns=["humidity"])) is None


def test_parses_mixed_text_formats_to_utc() -> None:
    result = parse_times(pd.Series(["2023-01-01 00:00:00+00:00", "2023-01-01T01:00:00Z", "2023-01-01 02:00:00"]))
    assert result.dt.hour.tolist() == [0, 1, 2]
    assert str(result.dt.tz) == "UTC"


@pytest.mark.parametrize("value", [1672531200, 1672531200000])
def test_parses_epoch_seconds_and_milliseconds(value: int) -> None:
    assert parse_times(pd.Series([value])).iloc[0] == pd.Timestamp("2023-01-01", tz="UTC")


def test_small_numbers_are_not_times() -> None:
    with pytest.raises(ValueError, match="does not look like a time"):
        parse_times(pd.Series([1, 2, 3], name="humidity"))


def test_sorted_by_time_sorts_and_counts_bad_rows() -> None:
    df = pd.DataFrame({"t": ["2023-01-02", "nonsense", "2023-01-01"], "v": [2, 9, 1]})
    result, dropped = sorted_by_time(df, "t")
    assert result["v"].tolist() == [1, 2]
    assert dropped == 1


def test_sorted_by_time_rejects_unreadable_column() -> None:
    with pytest.raises(ValueError, match="no readable times"):
        sorted_by_time(pd.DataFrame({"t": ["a", "b"]}), "t")
