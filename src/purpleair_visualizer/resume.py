"""Continue a sensor's record from an earlier download.

Reads a previous PurpleAir CSV (from this app or PurpleAir's own download
tool) to suggest matching download settings, and combines the old and new
files into one record without repeated timestamps.
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from datetime import timedelta, tzinfo
from pathlib import Path

import pandas as pd

from purpleair_visualizer.api import AVERAGES
from purpleair_visualizer.data import TIME_ZONES, detect_time_column, format_times, load_csv, parse_times
from purpleair_visualizer.processing import infer_interval

SENSOR_COLUMN = "sensor_index"
_SENSOR_IN_NAME = re.compile(r"^(\d+)[ _]")
_UTC_OFFSET = re.compile(r"(Z|[+-]\d{2}:?\d{2})$")


@dataclass(frozen=True)
class PreviousDownload:
    """What an earlier download contains.

    Attributes:
        path: The file that was read.
        data: The file contents as loaded.
        time_column: Column holding the timestamps.
        first_time: Earliest timestamp, UTC.
        last_time: Latest timestamp, UTC.
        next_time: When the next reading after the file is due, UTC. The
            same as ``last_time`` if the spacing cannot be found.
        sensor_index: Sensor index from the file name or a column, if found.
        average: Matching key of ``AVERAGES``, if the spacing matches one.
        fields: Data columns, in file order.
        zone: Matching key of ``TIME_ZONES``, if the times carry a known offset.
    """

    path: Path
    data: pd.DataFrame
    time_column: str
    first_time: pd.Timestamp
    last_time: pd.Timestamp
    next_time: pd.Timestamp
    sensor_index: int | None
    average: str | None
    fields: tuple[str, ...]
    zone: str | None


def _sensor_index(path: Path, df: pd.DataFrame) -> int | None:
    """Find the sensor index in the file name or a sensor_index column."""
    match = _SENSOR_IN_NAME.match(path.stem)
    if match:
        return int(match.group(1))
    if SENSOR_COLUMN in df.columns:
        values = pd.to_numeric(df[SENSOR_COLUMN], errors="coerce").dropna().unique()
        if len(values) == 1:
            return int(values[0])
    return None


def _interval(times: pd.Series) -> pd.Timedelta | None:
    """Find the most common spacing, or None if there is too little data."""
    try:
        return infer_interval(times)
    except ValueError:
        return None


def _average(interval: pd.Timedelta | None) -> str | None:
    """Match a spacing to a PurpleAir average."""
    if interval is None:
        return None
    minutes = interval / pd.Timedelta(minutes=1)
    for name, average in AVERAGES.items():
        if average.minutes and average.minutes == minutes:
            return name
    return None


def _zone(values: pd.Series) -> str | None:
    """Match the UTC offset written on the first timestamp to a time zone.

    Text without an offset is taken to be UTC, as PurpleAir exports are.
    """
    first = values.dropna()
    if first.empty or pd.api.types.is_numeric_dtype(first):
        return None
    match = _UTC_OFFSET.search(str(first.iloc[0]).strip())
    if match is None or match.group(1) == "Z":
        offset = timedelta(0)
    else:
        text = match.group(1).replace(":", "")
        offset = (1 if text[0] == "+" else -1) * timedelta(hours=int(text[1:3]), minutes=int(text[3:5]))
    for name, zone in TIME_ZONES.items():
        if zone.utcoffset(None) == offset:
            return name
    return None


def read_previous_download(path: str | Path) -> PreviousDownload:
    """Read an earlier download and work out how it was made.

    Args:
        path: Location of the earlier CSV.

    Returns:
        The file contents with the settings that match it.

    Raises:
        OSError: If the file cannot be read.
        ValueError: If the file has no readable time column.
    """
    path = Path(path)
    df = load_csv(path)
    time_column = detect_time_column(df)
    if time_column is None:
        raise ValueError(f"{path.name} has no time column.")
    times = parse_times(df[time_column]).dropna()
    if times.empty:
        raise ValueError(f"{path.name} contains no readable times.")
    fields = tuple(str(column) for column in df.columns if column not in (time_column, SENSOR_COLUMN))
    interval = _interval(times)
    last_time = times.max()
    return PreviousDownload(
        path=path,
        data=df,
        time_column=time_column,
        first_time=times.min(),
        last_time=last_time,
        next_time=last_time if interval is None else last_time + interval,
        sensor_index=_sensor_index(path, df),
        average=_average(interval),
        fields=fields,
        zone=_zone(df[time_column]),
    )


def combine_downloads(
    previous: pd.DataFrame, new: pd.DataFrame, time_column: str, time_zone: tzinfo
) -> pd.DataFrame:
    """Join an earlier download and a new one into a single record.

    Where both contain the same timestamp, the new row is kept, since the
    newer download covers that period completely.

    Args:
        previous: The earlier download.
        new: The new download, with the same time column name.
        time_column: Column holding the timestamps in both.
        time_zone: Zone for the output time column.

    Returns:
        All rows sorted by time, with columns in the earlier file's order
        followed by any columns only the new file has.

    Raises:
        ValueError: If the new download lacks the time column.
    """
    if time_column not in new.columns:
        raise ValueError(f"The new download has no '{time_column}' column.")
    old = previous.assign(**{time_column: parse_times(previous[time_column])})
    fresh = new.assign(**{time_column: parse_times(new[time_column])})
    combined = (
        pd.concat([old, fresh], ignore_index=True)
        .dropna(subset=[time_column])
        .drop_duplicates(subset=[time_column], keep="last")
        .sort_values(time_column, kind="stable")
        .reset_index(drop=True)
    )
    combined[time_column] = format_times(combined[time_column], time_zone)
    columns = [*previous.columns, *[column for column in new.columns if column not in previous.columns]]
    return combined[columns]
