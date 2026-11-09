# Quickstart

This guide takes you from nothing to your first air quality plot. You don't need to know how to program.

## 1. Get the app

**Windows:** download `PurpleAirVisualizer.exe` from the [latest release](https://github.com/AndrewsForestLTER/purpleair-visualizer/releases/latest) and double-click it. If Windows SmartScreen warns about an unrecognized app, choose **More info**, then **Run anyway**.

**macOS or Linux:** install Python 3.10 or later, then follow the steps under [Install](../README.md#install) in the README.

## 2. Try the sample file

Download [`sample_purpleair.csv`](https://raw.githubusercontent.com/AndrewsForestLTER/purpleair-visualizer/main/examples/sample_purpleair.csv). It holds two weeks of made-up hourly data with a smoke event and a few gaps.

1. Click **Open CSV...** and choose the file. The **Data Preview** tab shows the first rows.
2. Open the **Plot** tab. The time column and PM2.5 column are already chosen.
3. Untick everything under **Columns**, tick **Plot PM2.5 as AQI**, and click **Create Plot**. The line changes color with AQI category, and the smoke event stands out.
4. Use the toolbar under the plot to zoom and pan. Click **Save as PNG** to keep the image.

## 3. Get data from your own sensor

PurpleAir provides historical data through its Data Download Tool, which uses the PurpleAir API. The older CSV download from the map has been discontinued.

1. Create a PurpleAir Develop account and an API read key.
2. Install the Data Download Tool and paste in your key.
3. Enter your sensor's index number and choose dates, an averaging period and fields. Include `humidity`, `temperature` and `pm2.5_cf_1` to match the sample.
4. Download the CSV and open it in this app.

Requests use API points, and private sensors also need their own read key. PurpleAir's [step-by-step guide](https://community.purpleair.com/t/how-to-get-historical-sensor-data-step-by-step-using-the-data-download-tool/11934) has current details.

## 4. Clean up the data (optional)

Each of these saves a new file, and the file you opened is not changed.

- **Fill Gaps:** click **Find Gaps** to see which timesteps are missing, then **Save Filled CSV** to get a copy with a blank row for each one. Blank rows show gaps honestly in plots and analysis. If your interval isn't detected correctly, pick it from the list.
- **Temperature:** PurpleAir reports Fahrenheit. Choose the direction and click **Convert**, then **Save Converted CSV**.
- **Column Bounds:** check minimums and maximums to spot impossible values, such as humidity over 100.

To use a saved file, open it with **Open CSV...**.

## Reading the AQI plot

The app uses the current EPA categories, revised in 2024. Two things matter when you interpret the numbers:

- Official AQI uses 24-hour averages, but the app calculates a value for each reading. An hourly spike can look worse than the official daily AQI for that day.
- Raw PurpleAir readings are usually higher than regulatory monitors. Treat the plot as a way to explore patterns, not as a health advisory. For that, see [AirNow](https://www.airnow.gov/).

See [How AQI is calculated](../README.md#how-aqi-is-calculated) for details.

## Troubleshooting

| Problem | What to do |
|---------|------------|
| "Cannot read time column" | Choose the correct **Time column** in the Plot tab. |
| AQI option has no effect | Choose a column in **PM2.5 column**. It is blank if no column name looks like PM2.5. |
| "duplicate timestamp(s)" in Fill Gaps | The file has repeated times, often from joining downloads. Remove the repeats and open it again. |
| Fill Gaps shows many rows between interval steps | The automatic interval may be wrong. Choose the right one from **Interval**. |
| "No module named tkinter" on Linux | Run `sudo apt install python3-tk`. |

Found a bug? Please [open an issue](https://github.com/AndrewsForestLTER/purpleair-visualizer/issues).
