"""Tests for gap filling, temperature conversion and bounds."""

from pathlib import Path

import numpy as np
import pandas as pd
import pytest

from purpleair_visualizer.cli import bounds_main
from purpleair_visualizer.data import PST
from purpleair_visualizer.processing import (
    C_TO_F,
    F_TO_C,
    compute_bounds,
    convert_temperature,
    format_cell,
    infer_interval,
    pad_timesteps,
)


def stamps(*values: str) -> list[str]:
    return [f"2023-01-01 {value}+00:00" for value in values]


def test_pad_adds_blank_hour() -> None:
    df = pd.DataFrame({"t": stamps("00:00:00", "01:00:00", "03:00:00"), "v": [1.5, 2.5, 3.5]})
    result = pad_timesteps(df, "t")
    assert len(result.data) == 4
    assert result.interval == pd.Timedelta("1h")
    assert result.missing.hour.tolist() == [2]
    assert pd.isna(result.data["v"].iloc[2])


def test_pad_writes_times_in_chosen_zone(tmp_path: Path) -> None:
    df = pd.DataFrame({"t": stamps("00:00:00", "02:00:00", "03:00:00"), "v": [1.0, 2.0, 3.0]})
    path = tmp_path / "pst.csv"
    pad_timesteps(df, "t", time_zone=PST).data.to_csv(path, index=False)
    assert path.read_text().splitlines()[1:3] == ["2022-12-31 16:00:00-08:00,1.0", "2022-12-31 17:00:00-08:00,"]


def test_pad_keeps_all_ten_minute_rows() -> None:
    times = pd.date_range("2023-01-01", periods=12, freq="10min", tz="UTC").astype(str)
    result = pad_timesteps(pd.DataFrame({"t": times, "v": range(12)}), "t")
    assert result.data["v"].notna().sum() == 12
    assert len(result.missing) == 0


def test_pad_keeps_rows_between_steps() -> None:
    df = pd.DataFrame({"t": stamps("00:00:00", "01:00:00", "02:07:00", "03:00:00"), "v": [1.0, 2.0, 3.0, 4.0]})
    result = pad_timesteps(df, "t", "1h")
    assert result.data["v"].notna().sum() == 4
    assert result.off_interval_rows == 1
    assert result.missing.hour.tolist() == [2]


def test_pad_preserves_precision_and_integers(tmp_path: Path) -> None:
    df = pd.DataFrame(
        {"t": stamps(*[f"{hour:02d}:00:00" for hour in (*range(11), 12)]), "pm": [0.0] * 11 + [12.345], "rh": range(12)}
    )
    path = tmp_path / "padded.csv"
    pad_timesteps(df, "t").data.to_csv(path, index=False)
    lines = path.read_text().splitlines()
    assert lines[-1].endswith(",12.345,11")
    assert lines[-2].endswith(",,")


def test_pad_sorts_and_keeps_column_order() -> None:
    df = pd.DataFrame({"v": [2.0, 1.0], "t": stamps("01:00:00", "00:00:00")})
    result = pad_timesteps(df, "t")
    assert list(result.data.columns) == ["v", "t"]
    assert result.data["v"].tolist() == [1.0, 2.0]


def test_pad_does_not_modify_input() -> None:
    df = pd.DataFrame({"t": stamps("00:00:00", "02:00:00", "03:00:00"), "v": [1, 2, 3]})
    before = df.copy()
    pad_timesteps(df, "t")
    pd.testing.assert_frame_equal(df, before)


@pytest.mark.parametrize(
    ("times", "message"),
    [
        (stamps("00:00:00", "00:00:00", "01:00:00"), "duplicate"),
        (["nonsense", "2023-01-01", "2023-01-02"], "not readable"),
    ],
)
def test_pad_rejects_bad_times(times: list[str], message: str) -> None:
    with pytest.raises(ValueError, match=message):
        pad_timesteps(pd.DataFrame({"t": times}), "t")


def test_pad_rejects_unreasonable_interval() -> None:
    df = pd.DataFrame({"t": ["2000-01-01", "2030-01-01"]})
    with pytest.raises(ValueError, match="more than"):
        pad_timesteps(df, "t", "1s")


def test_infer_interval_uses_most_common_step() -> None:
    times = pd.Series(pd.to_datetime(["2023-01-01 00:00", "2023-01-01 01:00", "2023-01-01 02:00", "2023-01-01 07:00"]))
    assert infer_interval(times) == pd.Timedelta("1h")


def test_infer_interval_needs_two_times() -> None:
    with pytest.raises(ValueError, match="two different"):
        infer_interval(pd.Series(pd.to_datetime(["2023-01-01"])))


def test_temperature_round_trip_and_other_columns_untouched() -> None:
    df = pd.DataFrame({"temperature": [32.0, 212.0, np.nan], "pm": [12.345, 0.0, 1.0]})
    celsius = convert_temperature(df, "temperature", F_TO_C)
    assert celsius["temperature"].iloc[:2].tolist() == [0.0, 100.0]
    assert celsius["pm"].tolist() == [12.345, 0.0, 1.0]
    assert convert_temperature(celsius, "temperature", C_TO_F)["temperature"].iloc[1] == 212.0
    assert df["temperature"].iloc[0] == 32.0


def test_temperature_rejects_text() -> None:
    with pytest.raises(ValueError, match="not numeric"):
        convert_temperature(pd.DataFrame({"t": ["a"]}), "t")


def test_temperature_rejects_unknown_direction() -> None:
    with pytest.raises(ValueError, match="Unknown"):
        convert_temperature(pd.DataFrame({"t": [1.0]}), "t", "K")


def test_bounds_numeric_with_stats() -> None:
    row = compute_bounds(pd.DataFrame({"v": [1.0, 3.0]}), include_stats=True).iloc[0]
    assert (row["Min"], row["Max"], row["Range"], row["Mean"]) == (1.0, 3.0, 2.0, 2.0)


@pytest.mark.parametrize("column", [[True, False], ["a", None, "b"], [None, None]])
def test_bounds_handles_awkward_columns(column: list) -> None:
    assert compute_bounds(pd.DataFrame({"c": pd.Series(column, dtype=object)}), include_stats=True).iloc[0]["Range"] == "N/A"


def test_bounds_bool_dtype_and_exclude() -> None:
    df = pd.DataFrame({"f": [True, False], "skip": [1, 2]})
    result = compute_bounds(df, exclude=["skip"])
    assert result["Column"].tolist() == ["f"]
    assert result.iloc[0]["Data Type"] == "Non-Numeric"


def test_format_cell() -> None:
    assert format_cell(1.2345, 2) == "1.23"
    assert format_cell(np.int64(3), 1) == "3.0"
    assert format_cell(np.nan, 2) == "N/A"
    assert format_cell("text", 2) == "text"


def test_cli_saves_bounds(tmp_path: Path) -> None:
    source = tmp_path / "d.csv"
    pd.DataFrame({"v": [1, 2]}).to_csv(source, index=False)
    assert bounds_main([str(source), "--stats", "--save"]) == 0
    assert (tmp_path / "d_bounds.csv").exists()


def test_cli_reports_missing_file(tmp_path: Path) -> None:
    assert bounds_main([str(tmp_path / "absent.csv")]) == 1
