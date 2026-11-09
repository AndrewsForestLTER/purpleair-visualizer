# PurpleAir Visualizer

[![DOI](https://zenodo.org/badge/DOI/10.5281/zenodo.15367109.svg)](https://doi.org/10.5281/zenodo.15367109)

A desktop app for exploring data from [PurpleAir](https://www2.purpleair.com/) air quality sensors. Open a CSV file from any sensor to preview it, plot it over time, convert PM2.5 to the EPA Air Quality Index (AQI), find and fill gaps, convert temperature units and check the range of every column.

New here? Follow the **[Quickstart](docs/QUICKSTART.md)**. It takes about five minutes and includes a sample file.

## Features

| Tab | What it does |
|-----|--------------|
| **Data Preview** | Shows the first 100 rows of the file. |
| **Plot** | Plots any columns over time on one axis or as stacked subplots, draws PM2.5 as AQI colored by category, and saves a 300 dpi PNG. |
| **Fill Gaps** | Detects the reporting interval, lists missing timesteps and saves a copy with blank rows added. Existing rows and values are not changed. |
| **Temperature** | Converts one column between Fahrenheit and Celsius and saves a copy. |
| **Column Bounds** | Shows the minimum, maximum and range of each column, with optional mean, median and standard deviation. |

The app works with any averaging interval and any set of fields. Your original file is never modified.

## Install

**Windows:** download `PurpleAirVisualizer.exe` from the [latest release](https://github.com/AndrewsForestLTER/purpleair-visualizer/releases/latest) and double-click it. Nothing else is needed.

**Windows, macOS or Linux, with Python 3.10 or later:**

```bash
git clone https://github.com/AndrewsForestLTER/purpleair-visualizer.git
cd purpleair-visualizer
python -m venv .venv
# Windows:      .venv\Scripts\activate
# macOS/Linux:  source .venv/bin/activate
pip install .
purpleair-visualizer
```

Some Linux systems need Tk installed separately, for example `sudo apt install python3-tk`.

## Input data

Any CSV file with a time column and at least one numeric column will work. PurpleAir's [Data Download Tool](https://community.purpleair.com/t/how-to-get-historical-sensor-data-step-by-step-using-the-data-download-tool/11934) produces files like this:

```csv
time_stamp,humidity,temperature,pressure,pm2.5_cf_1
2025-08-01 00:00:00+00:00,38,82,964.86,5.756
```

- **Time** can be text or Unix epoch seconds or milliseconds. Times without a UTC offset are treated as UTC, and plots are labeled in UTC.
- **Columns** are detected by name, and you can change the choice in each tab. A PM2.5 column is any name containing `pm2.5`, `pm25` or `pm 2.5`.

## How AQI is calculated

The default is the EPA table in [40 CFR Part 58, Appendix G](https://www.ecfr.gov/current/title-40/part-58/appendix-Appendix%20G%20to%20Part%2058), as revised in 2024. PM2.5 is truncated to one decimal place, and the AQI is rounded to the nearest whole number.

| Category | AQI | PM2.5 (µg/m³), 2024 table | PM2.5 (µg/m³), pre-2024 table |
|----------|-----|------|------|
| Good | 0-50 | 0.0-9.0 | 0.0-12.0 |
| Moderate | 51-100 | 9.1-35.4 | 12.1-35.4 |
| Unhealthy for Sensitive Groups | 101-150 | 35.5-55.4 | 35.5-55.4 |
| Unhealthy | 151-200 | 55.5-125.4 | 55.5-150.4 |
| Very Unhealthy | 201-300 | 125.5-225.4 | 150.5-250.4 |
| Hazardous | 301-500 | 225.5-325.4 | 250.5-500.4 |

Negative concentrations are treated as missing. Concentrations above the top of the table are reported as 500. Choose the pre-2024 table in the Plot tab to compare with older reports.

### Limits to keep in mind

- **Values are per reading.** Official AQI is based on 24-hour averages, or NowCast for current conditions. The app applies the table to each reading as recorded, so use a 24-hour averaged file if you want values comparable to official AQI.
- **Readings are not corrected.** Low-cost sensors need correction to match regulatory monitors. The app does not apply one. See [Barkjohn et al. (2021)](https://doi.org/10.5194/amt-14-4617-2021) for the EPA correction for PurpleAir sensors.
- **Sensor temperature runs warm** because of heat inside the housing, and the app does not adjust for this.

## Command line

```bash
purpleair-bounds my_data.csv --stats --precision 3 --save
```

## Build the Windows executable

```bash
pip install ".[build]"
python build.py
```

The file is written to `dist/`.

## Development

```bash
pip install -e ".[dev]"
pytest
```

See [CONTRIBUTING.md](CONTRIBUTING.md) and [CHANGELOG.md](CHANGELOG.md). Specifications for the PurpleAir Classic sensor are in [docs/purpleair_classic_specs.yaml](docs/purpleair_classic_specs.yaml).

## Citation

Please cite this software using its [DOI](https://doi.org/10.5281/zenodo.15367109), which always resolves to the latest version. GitHub's "Cite this repository" button uses [CITATION.cff](CITATION.cff).

## License

Dedicated to the public domain under [CC0 1.0 Universal](LICENSE).

## Acknowledgments

This material is based upon work supported by the H.J. Andrews Experimental Forest and Long Term Ecological Research (LTER) program under NSF grant LTER8 DEB-2025755. This project is not affiliated with or endorsed by PurpleAir, Inc. The file in `examples/` is synthetic and is not real sensor data. Real hourly data from sensor 115739 at the H.J. Andrews Experimental Forest is archived with [version 1.0.0 on Zenodo](https://doi.org/10.5281/zenodo.15367110).
