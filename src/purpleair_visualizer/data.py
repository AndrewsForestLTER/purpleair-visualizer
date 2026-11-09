"""Load sensor CSV files and work out which columns hold time and PM2.5."""

from __future__ import annotations

import re
from datetime import timedelta, timezone, tzinfo
from pathlib import Path

import pandas as pd

ENCODINGS = ("utf-8-sig", "cp1252", "latin-1")
PST = timezone(timedelta(hours=-8), "PST")
TIME_ZONES: dict[str, tzinfo] = {
    "PST (UTC-8, no daylight saving)": PST,
    "UTC": timezone.utc,
}
DEFAULT_TIME_ZONE = "PST (UTC-8, no daylight saving)"
EPOCH_SECONDS_MIN = 1e8
EPOCH_MILLISECONDS_MIN = 1e11

_EXACT_TIME_NAMES = ("time_stamp", "timestamp", "datetime", "date_time")
_TIME_WORD = re.compile(r"(^|[^a-z])(time|date)([^a-z]|$)")
_PM25_NAME = re.compile(r"pm[ _]?2[._]?5")


def load_csv(path: str | Path) -> pd.DataFrame:
    """Read a CSV file, trying common encodings in turn.

    Args:
        path: Location of the CSV file.

    Returns:
        The file contents.

    Raises:
        OSError: If the file cannot be read.
        ValueError: If the file has no parseable rows or columns.
    """
    last_error: UnicodeDecodeError | None = None
    for encoding in ENCODINGS:
        try:
            return pd.read_csv(Path(path), encoding=encoding)
        except UnicodeDecodeError as error:
            last_error = error
    raise ValueError(f"Could not decode {path}: {last_error}")


def is_time_name(name: str) -> bool:
    """Return True if a column name looks like a time or date column."""
    lowered = name.lower()
    return lowered in _EXACT_TIME_NAMES or _TIME_WORD.search(lowered) is not None


def detect_time_column(df: pd.DataFrame) -> str | None:
    """Pick the most likely time column.

    Args:
        df: The loaded data.

    Returns:
        The column name, or None if nothing looks like time.
    """
    for column in df.columns:
        if str(column).lower() in _EXACT_TIME_NAMES:
            return column
    for column in df.columns:
        if is_time_name(str(column)):
            return column
    return None


def detect_pm25_column(df: pd.DataFrame) -> str | None:
    """Pick the first column that looks like PM2.5.

    Args:
        df: The loaded data.

    Returns:
        The column name, or None if no column looks like PM2.5.
    """
    for column in df.columns:
        if _PM25_NAME.search(str(column).lower()):
            return column
    return None


def numeric_columns(df: pd.DataFrame) -> list[str]:
    """List numeric columns, leaving out booleans and time-like columns."""
    return [
        column
        for column in df.columns
        if pd.api.types.is_numeric_dtype(df[column])
        and not pd.api.types.is_bool_dtype(df[column])
        and not is_time_name(str(column))
    ]


def parse_times(values: pd.Series) -> pd.Series:
    """Parse a column to UTC timestamps.

    Text without a UTC offset is taken to be UTC, which is what PurpleAir
    exports use. Numbers are read as Unix epoch seconds or milliseconds.

    Args:
        values: The raw time column.

    Returns:
        UTC timestamps, with NaT where a value could not be parsed.

    Raises:
        ValueError: If a numeric column is too small to be an epoch time.
    """
    if pd.api.types.is_numeric_dtype(values) and not pd.api.types.is_bool_dtype(values):
        magnitude = values.abs().median()
        if pd.isna(magnitude) or magnitude < EPOCH_SECONDS_MIN:
            raise ValueError(f"Column '{values.name}' is numeric but does not look like a time.")
        unit = "ms" if magnitude >= EPOCH_MILLISECONDS_MIN else "s"
        return pd.to_datetime(values, unit=unit, utc=True, errors="coerce")
    return pd.to_datetime(values, utc=True, format="mixed", errors="coerce")


def zone_name(zone: tzinfo) -> str:
    """Return a short label for a time zone, such as PST or UTC."""
    return zone.tzname(None) or str(zone)


def format_times(times: pd.Series, zone: tzinfo) -> pd.Series:
    """Write timestamps as text in a time zone, keeping the UTC offset.

    Args:
        times: Time-zone-aware timestamps.
        zone: The zone to express them in.

    Returns:
        Text such as ``2022-12-31 16:00:00-08:00``.
    """
    return times.dt.tz_convert(zone).dt.strftime("%Y-%m-%d %H:%M:%S%z").str.replace(
        r"([+-]\d{2})(\d{2})$", r"\1:\2", regex=True
    )


def sorted_by_time(df: pd.DataFrame, time_column: str) -> tuple[pd.DataFrame, int]:
    """Return a copy with parsed times, sorted, without unparseable rows.

    Args:
        df: The loaded data.
        time_column: Column holding the timestamps.

    Returns:
        The sorted data and the number of rows dropped for unparseable times.

    Raises:
        ValueError: If no value in the column can be parsed as a time.
    """
    result = df.copy()
    result[time_column] = parse_times(result[time_column])
    valid = result[time_column].notna()
    if not valid.any():
        raise ValueError(f"Column '{time_column}' contains no readable times.")
    dropped = int((~valid).sum())
    return result[valid].sort_values(time_column, kind="stable").reset_index(drop=True), dropped
