"""Data operations behind the app: gap filling, unit conversion and bounds."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import timezone, tzinfo

import pandas as pd

from purpleair_visualizer.data import parse_times

F_TO_C = "F_to_C"
C_TO_F = "C_to_F"
MAX_PADDED_ROWS = 5_000_000
_TEXT_LIMIT = 30


@dataclass(frozen=True)
class PadResult:
    """Outcome of filling a time series onto a regular interval."""

    data: pd.DataFrame
    interval: pd.Timedelta
    missing: pd.DatetimeIndex
    off_interval_rows: int


def infer_interval(times: pd.Series) -> pd.Timedelta:
    """Find the most common spacing in a time series.

    Args:
        times: Parsed timestamps, in any order.

    Returns:
        The most common positive difference between consecutive timestamps.

    Raises:
        ValueError: If there are too few distinct timestamps.
    """
    steps = times.dropna().sort_values().diff().dropna()
    steps = steps[steps > pd.Timedelta(0)]
    if steps.empty:
        raise ValueError("At least two different timestamps are needed to find the interval.")
    return steps.mode().iloc[0]


def pad_timesteps(
    df: pd.DataFrame,
    time_column: str,
    interval: pd.Timedelta | str | None = None,
    time_zone: tzinfo = timezone.utc,
) -> PadResult:
    """Add blank rows for timesteps missing from a regular time series.

    Every original row is kept, including rows that fall between grid points.
    Values in existing rows are not changed.

    Args:
        df: The loaded data.
        time_column: Column holding the timestamps.
        interval: Expected spacing. Detected from the data when None.
        time_zone: Zone for the output time column.

    Returns:
        The padded data with a summary of what was added.

    Raises:
        ValueError: If times are unreadable or duplicated, or the interval is
            not positive or would produce an unreasonable number of rows.
    """
    times = parse_times(df[time_column])
    unreadable = int(times.isna().sum())
    if unreadable:
        raise ValueError(f"{unreadable} value(s) in '{time_column}' are not readable times.")
    duplicates = int(times.duplicated().sum())
    if duplicates:
        raise ValueError(f"{duplicates} duplicate timestamp(s) in '{time_column}'. Resolve these first.")

    step = infer_interval(times) if interval is None else pd.Timedelta(interval)
    if step <= pd.Timedelta(0):
        raise ValueError("The interval must be greater than zero.")
    if (times.max() - times.min()) / step > MAX_PADDED_ROWS:
        raise ValueError(f"An interval of {step} would create more than {MAX_PADDED_ROWS:,} rows.")

    work = df.copy()
    for column in work.columns:
        if pd.api.types.is_integer_dtype(work[column]):
            work[column] = work[column].astype("Int64")  # integers stay integers beside blanks
    work[time_column] = times
    work = work.set_index(time_column).sort_index()

    grid = pd.date_range(work.index.min(), work.index.max(), freq=step)
    combined = grid.union(work.index)
    padded = work.reindex(combined)
    padded.index = padded.index.tz_convert(time_zone)
    padded.index.name = time_column
    return PadResult(
        data=padded.reset_index()[list(df.columns)],
        interval=step,
        missing=combined.difference(work.index),
        off_interval_rows=len(work.index.difference(grid)),
    )


def convert_temperature(
    df: pd.DataFrame, column: str, direction: str = F_TO_C, decimals: int = 2
) -> pd.DataFrame:
    """Return a copy with one temperature column converted.

    Args:
        df: The loaded data.
        column: Column to convert.
        direction: ``F_TO_C`` or ``C_TO_F``.
        decimals: Decimal places kept in the converted column.

    Returns:
        A copy of the data. Other columns are not changed.

    Raises:
        ValueError: If the column is not numeric or the direction is unknown.
    """
    if not pd.api.types.is_numeric_dtype(df[column]) or pd.api.types.is_bool_dtype(df[column]):
        raise ValueError(f"Column '{column}' is not numeric.")
    result = df.copy()
    if direction == F_TO_C:
        result[column] = ((result[column] - 32) * 5 / 9).round(decimals)
    elif direction == C_TO_F:
        result[column] = (result[column] * 9 / 5 + 32).round(decimals)
    else:
        raise ValueError(f"Unknown conversion '{direction}'.")
    return result


def compute_bounds(
    df: pd.DataFrame, include_stats: bool = False, exclude: list[str] | None = None
) -> pd.DataFrame:
    """Summarize the minimum, maximum and range of each column.

    Args:
        df: The loaded data.
        include_stats: Also report mean, median and standard deviation.
        exclude: Column names to leave out.

    Returns:
        One row per column. Non-numeric columns show their first and last
        values in sort order, ignoring blanks.
    """
    skipped = set(exclude or [])
    rows: list[dict[str, object]] = []
    for column in df.columns:
        if column in skipped:
            continue
        values = df[column]
        numeric = pd.api.types.is_numeric_dtype(values) and not pd.api.types.is_bool_dtype(values)
        if numeric:
            row: dict[str, object] = {
                "Column": column,
                "Data Type": "Numeric",
                "Min": values.min(),
                "Max": values.max(),
                "Range": values.max() - values.min(),
            }
        else:
            text = values.dropna().astype(str)
            row = {
                "Column": column,
                "Data Type": "Non-Numeric",
                "Min": text.min()[:_TEXT_LIMIT] if not text.empty else "N/A",
                "Max": text.max()[:_TEXT_LIMIT] if not text.empty else "N/A",
                "Range": "N/A",
            }
        if include_stats:
            row["Mean"] = values.mean() if numeric else "N/A"
            row["Median"] = values.median() if numeric else "N/A"
            row["Std Dev"] = values.std() if numeric else "N/A"
        rows.append(row)
    return pd.DataFrame(rows)


def format_cell(value: object, precision: int) -> str:
    """Format a bounds value for display.

    Args:
        value: A number or text value from ``compute_bounds``.
        precision: Decimal places for numbers.

    Returns:
        The display text; ``N/A`` for missing numbers.
    """
    if isinstance(value, str):
        return value
    return "N/A" if pd.isna(value) else f"{float(value):.{precision}f}"
