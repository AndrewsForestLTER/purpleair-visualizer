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

The app downloads directly from the PurpleAir API. Your sensor's readings are stored by PurpleAir, so the sensor doesn't need to be nearby.

1. Create an account and an API read key at [PurpleAir Develop](https://develop.purpleair.com/). The **How do I get a key?** button in the Download tab walks you through it.
2. In the app's **Download** tab, paste in your key and click **Test Key**. Tick **Remember key** if you don't want to enter it each time.
3. Enter your sensor's index number and choose dates (in UTC), an averaging period and fields. The usual fields are ticked for you. To find the index, click the sensor on the [PurpleAir map](https://map.purpleair.com/) and look for `select=` followed by a number in the page address, or use the **How do I find this?** button.
4. Click **Download and Open**. The app saves a CSV to the folder shown and opens it, ready to plot.

Downloads use API points from your PurpleAir account, and the app asks first before a very large download. Private sensors also need their own read key. See PurpleAir's [API overview](https://community.purpleair.com/t/about-the-purpleair-api/7145) for details on points. CSV files from PurpleAir's own Data Download Tool also work: use **Open CSV...**.

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
| "PurpleAir rejected the API key" | Copy the read key again from PurpleAir Develop. A write key won't work. |
| "PurpleAir has no data" | Check the sensor index, and that the sensor was reporting on those dates. |
| "Cannot read time column" | Choose the correct **Time column** in the Plot tab. |
| AQI option has no effect | Choose a column in **PM2.5 column**. It is blank if no column name looks like PM2.5. |
| "duplicate timestamp(s)" in Fill Gaps | The file has repeated times, often from joining downloads. Remove the repeats and open it again. |
| Fill Gaps shows many rows between interval steps | The automatic interval may be wrong. Choose the right one from **Interval**. |
| "No module named tkinter" on Linux | Run `sudo apt install python3-tk`. |

Found a bug? Please [open an issue](https://github.com/AndrewsForestLTER/purpleair-visualizer/issues).
