"""Tests for the AQI conversion."""

import math

import pandas as pd
import pytest

from purpleair_visualizer.aqi import BREAKPOINTS, aqi_color, pm25_to_aqi, series_to_aqi


@pytest.mark.parametrize(
    ("pm", "expected"),
    [(0.0, 0), (9.0, 50), (9.1, 51), (12.0, 56), (35.4, 100), (35.5, 101), (55.4, 150),
     (55.5, 151), (125.4, 200), (125.5, 201), (130.0, 205), (225.4, 300), (225.5, 301), (325.4, 500)],
)
def test_2024_table(pm: float, expected: int) -> None:
    assert pm25_to_aqi(pm) == expected


@pytest.mark.parametrize(("pm", "expected"), [(12.0, 50), (12.1, 51), (150.4, 200), (250.4, 300), (500.4, 500)])
def test_pre_2024_table(pm: float, expected: int) -> None:
    assert pm25_to_aqi(pm, "pre-2024") == expected


@pytest.mark.parametrize("table", list(BREAKPOINTS))
def test_values_between_bands_truncate_into_a_band(table: str) -> None:
    upper = BREAKPOINTS[table][1].conc_high
    assert pm25_to_aqi(upper + 0.05, table) == pm25_to_aqi(upper, table)


@pytest.mark.parametrize("pm", [-3.0, float("nan"), None])
def test_invalid_concentrations_are_missing(pm: float | None) -> None:
    assert math.isnan(pm25_to_aqi(pm))


@pytest.mark.parametrize("pm", [325.5, 700.0, 5000.0])
def test_values_above_scale_are_capped(pm: float) -> None:
    assert pm25_to_aqi(pm) == 500


def test_series_handles_text_and_blanks() -> None:
    result = series_to_aqi(pd.Series([9.0, "bad", None]))
    assert result.iloc[0] == 50
    assert result.iloc[1:].isna().all()


def test_colors_follow_categories() -> None:
    assert aqi_color(50) == "#00E400"
    assert aqi_color(51) == "#FFFF00"
    assert aqi_color(301) == "#7E0023"
    assert aqi_color(float("nan")) == "#808080"
