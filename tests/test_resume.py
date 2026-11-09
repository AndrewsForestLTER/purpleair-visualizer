"""Tests for continuing a record from an earlier download."""

from pathlib import Path

import pandas as pd

from purpleair_visualizer.data import PST
from purpleair_visualizer.resume import combine_downloads, read_previous_download

# PurpleAir's own download tool writes ISO times ending in Z.
OLD_EXPORT = (
    "time_stamp,humidity,temperature,pressure,pm2.5_cf_1\n"
    "2025-09-29T21:00:00Z,63,18.3,962.6,0.1\n"
    "2025-09-29T22:00:00Z,63,18.3,962.69,0.2\n"
    "2025-09-29T23:00:00Z,65,18.3,962.8,0.1\n"
)


def write(path: Path, text: str) -> Path:
    path.write_text(text)
    return path


def test_reads_purpleair_export(tmp_path: Path) -> None:
    previous = read_previous_download(write(tmp_path / "115739 2023-01-01 2025-09-30 60-Minute Average.csv", OLD_EXPORT))
    assert previous.sensor_index == 115739
    assert previous.average == "1 hour"
    assert previous.zone == "UTC"
    assert previous.fields == ("humidity", "temperature", "pressure", "pm2.5_cf_1")
    assert previous.last_time == pd.Timestamp("2025-09-29 23:00", tz="UTC")


def test_reads_app_download_in_pst(tmp_path: Path) -> None:
    text = "time_stamp,humidity\n2025-01-01 00:00:00-08:00,1\n2025-01-01 00:10:00-08:00,2\n"
    previous = read_previous_download(write(tmp_path / "115739_2025-01-01_PST.csv", text))
    assert previous.sensor_index == 115739
    assert previous.average == "10 minutes"
    assert previous.zone == "PST (UTC-8, no daylight saving)"


def test_unknown_settings_are_left_blank(tmp_path: Path) -> None:
    text = "time_stamp,v\n2025-01-01 00:00:00+05:30,1\n2025-01-01 00:07:00+05:30,2\n"
    previous = read_previous_download(write(tmp_path / "mine.csv", text))
    assert (previous.sensor_index, previous.average, previous.zone) == (None, None, None)


def test_sensor_column_supplies_index(tmp_path: Path) -> None:
    text = "time_stamp,sensor_index,v\n2025-01-01T00:00:00Z,42,1\n2025-01-01T01:00:00Z,42,2\n"
    previous = read_previous_download(write(tmp_path / "data.csv", text))
    assert previous.sensor_index == 42
    assert previous.fields == ("v",)


def test_combine_keeps_new_rows_where_they_overlap() -> None:
    old = pd.DataFrame({"time_stamp": ["2025-01-01T00:00:00Z", "2025-01-01T01:00:00Z"], "v": [1.0, 2.0]})
    new = pd.DataFrame(
        {"time_stamp": ["2024-12-31 17:00:00-08:00", "2024-12-31 18:00:00-08:00"], "v": [2.5, 3.0], "w": [7, 8]}
    )
    combined = combine_downloads(old, new, "time_stamp", PST)
    assert combined["time_stamp"].tolist() == [
        "2024-12-31 16:00:00-08:00",
        "2024-12-31 17:00:00-08:00",
        "2024-12-31 18:00:00-08:00",
    ]
    assert combined["v"].tolist() == [1.0, 2.5, 3.0]
    assert list(combined.columns) == ["time_stamp", "v", "w"]
    assert pd.isna(combined["w"].iloc[0])
