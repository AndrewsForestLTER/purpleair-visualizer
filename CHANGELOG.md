# Changelog

## Unreleased

### Added

- Time zone choice at the top of the window, PST (UTC-8, no daylight saving) by default or UTC, used for download dates, plots, gap filling and saved files.
- Downloads convert temperature to Celsius with one decimal by default.
- **Continue from...** in the Download tab matches the form to an earlier download, starts where it ends, and can combine both into one file without repeated times.

### Changed

- Downloaded columns follow the order the fields were chosen in, and file names include the time zone.

## 2.0.0 - 2026-11-09

First public GitHub release. AQI values differ from 1.0.0 for most concentrations above 9.0 µg/m³ (see below).

### Added

- Download tab that fetches sensor history from the PurpleAir API, splitting long date ranges automatically, then saves and opens the CSV.

### Changed

- AQI now uses the 2024 EPA PM2.5 breakpoints by default. The earlier table can be selected in the Plot tab.
- The separate tools are now one cross-platform app with tabs, installable with `pip`.
- Gap filling detects the reporting interval instead of assuming hourly data.
- Requires Python 3.10 and pandas 2.0 or later.

### Fixed

- Negative PM2.5 no longer produces a negative AQI, and values above the scale are capped at 500.
- Gap filling no longer drops rows that are not on the interval grid.
- Saved files no longer lose decimal places based on the first 10 rows.
- Gap filling works with current pandas releases.
- Column bounds no longer crash on true/false columns or text columns with blanks.
- The AQI legend is kept when other columns share the plot.
- "Plot PM2.5 as AQI" works when the PM2.5 column is not ticked.
- Unsorted files plot in time order, and Unix time columns are read correctly.
- Repeated plotting no longer leaks memory.
- `LICENSE` now contains the full CC0 1.0 legal text.

### Removed

- `read_data.py` and the standalone tool scripts, replaced by the app and the `purpleair-bounds` command.
- The bounds table's copy-single-cell menu. Select a row and press Ctrl+C to copy it.

## 1.0.0 - 2025-05-08

Initial release.
