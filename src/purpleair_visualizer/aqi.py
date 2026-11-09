"""PM2.5 to Air Quality Index conversion using EPA breakpoints.

The default table is the one in 40 CFR Part 58 Appendix G as revised in 2024.
The pre-2024 table is kept so results can be compared with older reports.
"""

from __future__ import annotations

import math
from typing import NamedTuple

import numpy as np
import pandas as pd


class Breakpoint(NamedTuple):
    """One row of an AQI breakpoint table."""

    conc_low: float
    conc_high: float
    aqi_low: int
    aqi_high: int


class Category(NamedTuple):
    """An AQI category with its EPA reporting color."""

    upper_aqi: float
    label: str
    color: str


BREAKPOINTS: dict[str, tuple[Breakpoint, ...]] = {
    "2024": (
        Breakpoint(0.0, 9.0, 0, 50),
        Breakpoint(9.1, 35.4, 51, 100),
        Breakpoint(35.5, 55.4, 101, 150),
        Breakpoint(55.5, 125.4, 151, 200),
        Breakpoint(125.5, 225.4, 201, 300),
        Breakpoint(225.5, 325.4, 301, 500),
    ),
    "pre-2024": (
        Breakpoint(0.0, 12.0, 0, 50),
        Breakpoint(12.1, 35.4, 51, 100),
        Breakpoint(35.5, 55.4, 101, 150),
        Breakpoint(55.5, 150.4, 151, 200),
        Breakpoint(150.5, 250.4, 201, 300),
        Breakpoint(250.5, 350.4, 301, 400),
        Breakpoint(350.5, 500.4, 401, 500),
    ),
}

CATEGORIES: tuple[Category, ...] = (
    Category(50, "Good (0-50)", "#00E400"),
    Category(100, "Moderate (51-100)", "#FFFF00"),
    Category(150, "Unhealthy for Sensitive Groups (101-150)", "#FF7E00"),
    Category(200, "Unhealthy (151-200)", "#FF0000"),
    Category(300, "Very Unhealthy (201-300)", "#8F3F97"),
    Category(math.inf, "Hazardous (301+)", "#7E0023"),
)

MISSING_COLOR = "#808080"


def pm25_to_aqi(pm: float, table: str = "2024") -> float:
    """Convert one PM2.5 concentration to an AQI value.

    The concentration is truncated to one decimal place, as EPA specifies, so
    every value falls inside a breakpoint band.

    Args:
        pm: PM2.5 concentration in micrograms per cubic meter.
        table: Key into ``BREAKPOINTS``.

    Returns:
        The AQI, capped at 500, or NaN for missing or negative concentrations.
    """
    if pm is None or pd.isna(pm) or pm < 0:
        return np.nan
    truncated = math.floor(float(pm) * 10 + 1e-9) / 10
    bands = BREAKPOINTS[table]
    if truncated > bands[-1].conc_high:
        return 500.0
    for band in bands:
        if truncated <= band.conc_high:
            slope = (band.aqi_high - band.aqi_low) / (band.conc_high - band.conc_low)
            return float(math.floor(slope * (truncated - band.conc_low) + band.aqi_low + 0.5))
    return np.nan  # unreachable: the cap above covers everything past the last band


def series_to_aqi(values: pd.Series, table: str = "2024") -> pd.Series:
    """Convert a column of PM2.5 concentrations to AQI values.

    Args:
        values: PM2.5 concentrations. Non-numeric entries become NaN.
        table: Key into ``BREAKPOINTS``.

    Returns:
        AQI values aligned to the input index.
    """
    return pd.to_numeric(values, errors="coerce").map(lambda pm: pm25_to_aqi(pm, table))


def aqi_color(aqi: float) -> str:
    """Return the EPA reporting color for an AQI value.

    Args:
        aqi: The AQI value.

    Returns:
        A hex color string; gray when the value is missing.
    """
    if pd.isna(aqi):
        return MISSING_COLOR
    for category in CATEGORIES:
        if aqi <= category.upper_aqi:
            return category.color
    return MISSING_COLOR
