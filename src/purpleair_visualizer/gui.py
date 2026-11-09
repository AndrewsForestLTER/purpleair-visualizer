"""Tkinter desktop app: preview, plot, gap fill, convert and summarize a CSV."""

from __future__ import annotations

import logging
import queue
import sys
import threading
import tkinter as tk
import webbrowser
from collections.abc import Callable
from pathlib import Path
from tkinter import filedialog, messagebox, ttk

import numpy as np
import pandas as pd
from matplotlib.backends.backend_tkagg import FigureCanvasTkAgg, NavigationToolbar2Tk
from matplotlib.collections import LineCollection
from matplotlib.dates import AutoDateLocator, ConciseDateFormatter, date2num
from matplotlib.figure import Figure
from matplotlib.patches import Patch

from purpleair_visualizer import __version__
from purpleair_visualizer.api import (
    AVERAGES,
    DEFAULT_FIELDS,
    OPTIONAL_FIELDS,
    DownloadCancelled,
    HistoryRequest,
    PurpleAirError,
    check_key,
    download_history,
    split_range,
)
from purpleair_visualizer.aqi import BREAKPOINTS, CATEGORIES, aqi_color, series_to_aqi
from purpleair_visualizer.data import (
    detect_pm25_column,
    detect_time_column,
    load_csv,
    numeric_columns,
    sorted_by_time,
)
from purpleair_visualizer.processing import (
    C_TO_F,
    F_TO_C,
    PadResult,
    compute_bounds,
    convert_temperature,
    format_cell,
    pad_timesteps,
)
from purpleair_visualizer.settings import SETTINGS_PATH, initial_api_key, load_settings, save_settings

logger = logging.getLogger(__name__)

POLL_MILLISECONDS = 100
CONFIRM_REQUESTS = 5
PREVIEW_ROWS = 100
DEVELOP_URL = "https://develop.purpleair.com/"
API_KEY_HELP = (
    "API keys belong to your PurpleAir account, not to a sensor. One key works for any public sensor.\n\n"
    "1. Sign in at develop.purpleair.com. Sign-in uses an email linked to a Google account.\n"
    "2. Open the API Keys tab and create a READ key, or copy one you already have. A write key won't work.\n"
    "3. Paste it into the API read key box and click Test Key.\n\n"
    "Private sensors also need that sensor's own read key, entered in the Private sensor read key box.\n\n"
    "Downloads may use API points from your account. Treat your key like a password.\n\n"
    "Open develop.purpleair.com now?"
)
MISSING_LISTED = 10
AUTO_INTERVAL = "Auto-detect"
INTERVALS: dict[str, str | None] = {
    AUTO_INTERVAL: None,
    "2 minutes": "2min",
    "10 minutes": "10min",
    "30 minutes": "30min",
    "1 hour": "1h",
    "6 hours": "6h",
    "1 day": "1D",
}
AQI_NOTE = (
    "AQI is calculated for each reading as recorded. Official AQI uses 24-hour averages, "
    "and raw PurpleAir values are not EPA-corrected."
)


def make_table(parent: ttk.Frame) -> ttk.Treeview:
    """Create a table with scrollbars that fills its parent frame."""
    container = ttk.Frame(parent)
    container.pack(fill=tk.BOTH, expand=True, padx=5, pady=5)
    container.columnconfigure(0, weight=1)
    container.rowconfigure(0, weight=1)
    table = ttk.Treeview(container, show="headings")
    table.grid(row=0, column=0, sticky=tk.NSEW)
    vertical = ttk.Scrollbar(container, orient=tk.VERTICAL, command=table.yview)
    vertical.grid(row=0, column=1, sticky=tk.NS)
    horizontal = ttk.Scrollbar(container, orient=tk.HORIZONTAL, command=table.xview)
    horizontal.grid(row=1, column=0, sticky=tk.EW)
    table.configure(yscrollcommand=vertical.set, xscrollcommand=horizontal.set)
    return table


def fill_table(table: ttk.Treeview, columns: list[str], rows: list[list[str]]) -> None:
    """Replace a table's contents."""
    table.delete(*table.get_children())
    table["columns"] = columns
    for column in columns:
        table.heading(column, text=column)
        table.column(column, width=120, minwidth=50, stretch=False)
    for row in rows:
        table.insert("", tk.END, values=row)


def fill_table_from_frame(table: ttk.Treeview, df: pd.DataFrame) -> None:
    """Show the first rows of a data frame in a table."""
    rows = [["" if pd.isna(value) else str(value) for value in row] for row in df.head(PREVIEW_ROWS).to_numpy()]
    fill_table(table, [str(column) for column in df.columns], rows)


def ask_save_csv(df: pd.DataFrame, title: str) -> Path | None:
    """Prompt for a location and write a CSV file.

    Args:
        df: The data to save.
        title: The dialog title.

    Returns:
        The saved path, or None if cancelled or the write failed.
    """
    name = filedialog.asksaveasfilename(
        title=title, defaultextension=".csv", filetypes=[("CSV files", "*.csv")]
    )
    if not name:
        return None
    try:
        df.to_csv(name, index=False)
    except OSError as error:
        messagebox.showerror("Save failed", str(error))
        return None
    return Path(name)


def unique_path(path: Path) -> Path:
    """Return the path, adding a number if a file already exists there."""
    candidate = path
    number = 1
    while candidate.exists():
        candidate = path.with_name(f"{path.stem}_{number}{path.suffix}")
        number += 1
    return candidate


class DownloadTab(ttk.Frame):
    """Downloads a sensor's history from the PurpleAir API and opens it."""

    def __init__(self, parent: ttk.Notebook, app: "App") -> None:
        super().__init__(parent)
        self.app = app
        self.events: queue.Queue[tuple[str, object]] = queue.Queue()
        self.cancel = threading.Event()
        self.running = False
        saved = load_settings()

        form = ttk.Frame(self, padding=10)
        form.pack(fill=tk.X)
        form.columnconfigure(1, weight=1)

        ttk.Label(form, text="API read key:").grid(row=0, column=0, sticky=tk.W, pady=3)
        self.key_var = tk.StringVar(value=initial_api_key(saved))
        ttk.Entry(form, textvariable=self.key_var, show="*", width=50).grid(row=0, column=1, sticky=tk.EW, padx=5)
        self.test_button = ttk.Button(form, text="Test Key", command=self.test_key)
        self.test_button.grid(row=0, column=2, sticky=tk.W)
        ttk.Button(form, text="How do I get a key?", command=self.show_key_help).grid(
            row=0, column=3, sticky=tk.W, padx=5
        )
        self.remember_var = tk.BooleanVar(value=bool(saved.get("api_key")))
        ttk.Checkbutton(
            form, text=f"Remember key on this computer (stored unencrypted in {SETTINGS_PATH})", variable=self.remember_var
        ).grid(row=1, column=1, columnspan=2, sticky=tk.W, padx=5)

        ttk.Label(form, text="Sensor index:").grid(row=2, column=0, sticky=tk.W, pady=3)
        self.sensor_var = tk.StringVar(value=str(saved.get("sensor_index", "")))
        ttk.Entry(form, textvariable=self.sensor_var, width=14).grid(row=2, column=1, sticky=tk.W, padx=5)

        ttk.Label(form, text="Private sensor read key:").grid(row=3, column=0, sticky=tk.W, pady=3)
        self.read_key_var = tk.StringVar()
        ttk.Entry(form, textvariable=self.read_key_var, show="*", width=30).grid(row=3, column=1, sticky=tk.W, padx=5)

        today = pd.Timestamp.now(tz="UTC").normalize()
        ttk.Label(form, text="Start date (UTC):").grid(row=4, column=0, sticky=tk.W, pady=3)
        self.start_var = tk.StringVar(value=f"{today - pd.Timedelta(days=30):%Y-%m-%d}")
        ttk.Entry(form, textvariable=self.start_var, width=14).grid(row=4, column=1, sticky=tk.W, padx=5)
        ttk.Label(form, text="End date (UTC, included):").grid(row=5, column=0, sticky=tk.W, pady=3)
        self.end_var = tk.StringVar(value=f"{today:%Y-%m-%d}")
        ttk.Entry(form, textvariable=self.end_var, width=14).grid(row=5, column=1, sticky=tk.W, padx=5)

        ttk.Label(form, text="Average:").grid(row=6, column=0, sticky=tk.W, pady=3)
        average = saved.get("average")
        self.average_var = tk.StringVar(value=average if average in AVERAGES else "1 hour")
        ttk.Combobox(
            form, textvariable=self.average_var, values=list(AVERAGES), state="readonly", width=12
        ).grid(row=6, column=1, sticky=tk.W, padx=5)

        ttk.Label(form, text="Fields:").grid(row=7, column=0, sticky=tk.NW, pady=3)
        fields_frame = ttk.Frame(form)
        fields_frame.grid(row=7, column=1, columnspan=2, sticky=tk.W, padx=5)
        chosen = saved.get("fields") if isinstance(saved.get("fields"), list) else list(DEFAULT_FIELDS)
        self.field_vars: dict[str, tk.BooleanVar] = {}
        for index, field in enumerate((*DEFAULT_FIELDS, *OPTIONAL_FIELDS)):
            self.field_vars[field] = tk.BooleanVar(value=field in chosen)
            ttk.Checkbutton(fields_frame, text=field, variable=self.field_vars[field]).grid(
                row=index // 4, column=index % 4, sticky=tk.W, padx=(0, 15)
            )
        ttk.Label(form, text="Other fields (comma separated):").grid(row=8, column=0, sticky=tk.W, pady=3)
        self.extra_var = tk.StringVar(value=str(saved.get("extra_fields", "")))
        ttk.Entry(form, textvariable=self.extra_var).grid(row=8, column=1, sticky=tk.EW, padx=5)

        ttk.Label(form, text="Save to folder:").grid(row=9, column=0, sticky=tk.W, pady=3)
        self.folder_var = tk.StringVar(value=str(saved.get("folder") or Path.home() / "PurpleAir Downloads"))
        ttk.Entry(form, textvariable=self.folder_var).grid(row=9, column=1, sticky=tk.EW, padx=5)
        ttk.Button(form, text="Browse...", command=self.choose_folder).grid(row=9, column=2, sticky=tk.W)

        actions = ttk.Frame(self, padding=(10, 0))
        actions.pack(fill=tk.X)
        self.download_button = ttk.Button(actions, text="Download and Open", command=self.start)
        self.download_button.pack(side=tk.LEFT)
        self.cancel_button = ttk.Button(actions, text="Cancel", command=self.cancel.set, state=tk.DISABLED)
        self.cancel_button.pack(side=tk.LEFT, padx=5)
        self.progress = ttk.Progressbar(actions, mode="determinate", length=300)
        self.progress.pack(side=tk.LEFT, padx=10)
        self.message = ttk.Label(self, text="", padding=10, wraplength=900)
        self.message.pack(anchor=tk.W)
        ttk.Label(
            self,
            text="Get an API read key at develop.purpleair.com. Downloads use API points from your PurpleAir account.",
            foreground="gray",
            padding=(10, 0),
        ).pack(anchor=tk.W)

    def on_data_loaded(self) -> None:
        """Nothing here depends on the loaded file."""

    def show_key_help(self) -> None:
        """Explain how to get an API key and offer to open PurpleAir's site."""
        if messagebox.askyesno("Getting a PurpleAir API key", API_KEY_HELP):
            webbrowser.open(DEVELOP_URL)

    def choose_folder(self) -> None:
        """Ask where downloads should be saved."""
        folder = filedialog.askdirectory(title="Save downloads to")
        if folder:
            self.folder_var.set(folder)

    def _selected_fields(self) -> tuple[str, ...]:
        """Combine ticked fields and typed fields, without repeats."""
        ticked = [field for field, var in self.field_vars.items() if var.get()]
        typed = [field.strip() for field in self.extra_var.get().split(",") if field.strip()]
        return tuple(dict.fromkeys([*ticked, *typed]))

    def _build_job(self) -> HistoryRequest:
        """Validate the form.

        Returns:
            The download to run.

        Raises:
            ValueError: If an entry is missing or invalid.
        """
        api_key = self.key_var.get().strip()
        if not api_key:
            raise ValueError("Enter your PurpleAir API read key.")
        sensor = self.sensor_var.get().strip()
        if not sensor.isdigit():
            raise ValueError("The sensor index must be a whole number, such as 115739.")
        fields = self._selected_fields()
        if not fields:
            raise ValueError("Choose at least one field.")
        try:
            start = pd.Timestamp(self.start_var.get().strip(), tz="UTC")
            end = pd.Timestamp(self.end_var.get().strip(), tz="UTC") + pd.Timedelta(days=1)
        except ValueError:
            raise ValueError("Enter dates as YYYY-MM-DD.") from None
        if pd.isna(start) or pd.isna(end):
            raise ValueError("Enter dates as YYYY-MM-DD.")
        return HistoryRequest(
            sensor_index=int(sensor),
            api_key=api_key,
            start=start,
            end=end,
            average=self.average_var.get(),
            fields=fields,
            read_key=self.read_key_var.get().strip(),
        )

    def _save_choices(self) -> None:
        """Remember the form for next time. The key is kept only if asked."""
        settings = {
            "sensor_index": self.sensor_var.get().strip(),
            "average": self.average_var.get(),
            "fields": [field for field, var in self.field_vars.items() if var.get()],
            "extra_fields": self.extra_var.get().strip(),
            "folder": self.folder_var.get().strip(),
        }
        if self.remember_var.get():
            settings["api_key"] = self.key_var.get().strip()
        try:
            save_settings(settings)
        except OSError as error:
            self.app.set_status(f"Could not save settings: {error}")

    def _set_running(self, running: bool) -> None:
        """Switch the buttons between idle and working states."""
        self.running = running
        idle = tk.DISABLED if running else tk.NORMAL
        self.download_button.config(state=idle)
        self.test_button.config(state=idle)
        self.cancel_button.config(state=tk.NORMAL if running else tk.DISABLED)

    def _run_in_background(self, work: Callable[[], object], kind: str) -> None:
        """Run network work off the interface thread and report through a queue."""

        def target() -> None:
            try:
                self.events.put((kind, work()))
            except DownloadCancelled:
                self.events.put(("cancelled", None))
            except (PurpleAirError, ValueError, OSError) as error:
                self.events.put(("error", str(error)))
            except Exception:
                logger.exception("Unexpected download failure")
                self.events.put(("error", "Something unexpected went wrong during the download."))

        self.cancel.clear()
        self._set_running(True)
        threading.Thread(target=target, daemon=True).start()
        self.after(POLL_MILLISECONDS, self._poll)

    def _poll(self) -> None:
        """Handle messages from the background work."""
        finished = False
        while True:
            try:
                kind, value = self.events.get_nowait()
            except queue.Empty:
                break
            if kind == "progress":
                done, total = value
                self.progress.config(maximum=total, value=done)
                self.message.config(text=f"Finished request {done} of {total}...")
                continue
            finished = True
            self._finish(kind, value)
        if not finished:
            self.after(POLL_MILLISECONDS, self._poll)

    def _finish(self, kind: str, value: object) -> None:
        """Show the outcome of the background work."""
        self._set_running(False)
        if kind == "key":
            self.message.config(text=f"Key accepted (type: {value}).")
        elif kind == "cancelled":
            self.message.config(text="Download cancelled.")
        elif kind == "error":
            self.message.config(text=str(value))
            messagebox.showerror("PurpleAir download", str(value))
        elif kind == "saved":
            self.message.config(text=f"Saved {value}")
            self.app.load_path(value)
            self.app.notebook.select(self.app.preview)

    def test_key(self) -> None:
        """Check the API key without downloading data."""
        api_key = self.key_var.get().strip()
        if not api_key:
            messagebox.showwarning("No key", "Enter your PurpleAir API read key.")
            return
        self.message.config(text="Checking key...")
        self._run_in_background(lambda: check_key(api_key), "key")

    def start(self) -> None:
        """Validate the form and start the download."""
        if self.running:
            return
        try:
            job = self._build_job()
            count = len(split_range(job.start, job.end, job.average))
        except ValueError as error:
            messagebox.showerror("Check the form", str(error))
            return
        if count > CONFIRM_REQUESTS and not messagebox.askyesno(
            "Large download", f"This needs {count} API requests and will use points from your account. Continue?"
        ):
            return
        self._save_choices()
        folder = Path(self.folder_var.get().strip())
        name = f"{job.sensor_index} {job.start:%Y-%m-%d} {job.end - pd.Timedelta(days=1):%Y-%m-%d} {job.average}.csv"

        def work() -> Path:
            data = download_history(job, lambda done, total: self.events.put(("progress", (done, total))), self.cancel)
            folder.mkdir(parents=True, exist_ok=True)
            path = unique_path(folder / name)
            data.to_csv(path, index=False)
            return path

        self.progress.config(maximum=count, value=0)
        self.message.config(text=f"Starting {count} request(s)...")
        self._run_in_background(work, "saved")


class PreviewTab(ttk.Frame):
    """Shows the first rows of the loaded file."""

    def __init__(self, parent: ttk.Notebook, app: "App") -> None:
        super().__init__(parent)
        self.app = app
        self.table = make_table(self)

    def on_data_loaded(self) -> None:
        """Refresh after a new file is loaded."""
        fill_table_from_frame(self.table, self.app.df)


class PlotTab(ttk.Frame):
    """Plots selected columns over time, with optional AQI conversion."""

    def __init__(self, parent: ttk.Notebook, app: "App") -> None:
        super().__init__(parent)
        self.app = app
        self.column_vars: dict[str, tk.BooleanVar] = {}

        controls = ttk.Frame(self)
        controls.pack(fill=tk.X, padx=5, pady=5)

        ttk.Label(controls, text="Time column:").grid(row=0, column=0, sticky=tk.W, padx=5, pady=3)
        self.time_var = tk.StringVar()
        self.time_combo = ttk.Combobox(controls, textvariable=self.time_var, state="readonly", width=22)
        self.time_combo.grid(row=0, column=1, sticky=tk.W, padx=5)

        ttk.Label(controls, text="Layout:").grid(row=0, column=2, sticky=tk.W, padx=5)
        self.layout_var = tk.StringVar(value="Single")
        ttk.Combobox(
            controls, textvariable=self.layout_var, values=["Single", "Subplots"], state="readonly", width=10
        ).grid(row=0, column=3, sticky=tk.W, padx=5)

        self.plot_button = ttk.Button(controls, text="Create Plot", command=self.draw, state=tk.DISABLED)
        self.plot_button.grid(row=0, column=4, padx=5)
        self.save_button = ttk.Button(controls, text="Save as PNG", command=self.save, state=tk.DISABLED)
        self.save_button.grid(row=0, column=5, padx=5)

        ttk.Label(controls, text="Columns:").grid(row=1, column=0, sticky=tk.NW, padx=5, pady=3)
        holder = ttk.Frame(controls)
        holder.grid(row=1, column=1, columnspan=3, sticky=tk.EW, padx=5)
        self.columns_canvas = tk.Canvas(holder, height=100, width=340, highlightthickness=0)
        scrollbar = ttk.Scrollbar(holder, orient=tk.VERTICAL, command=self.columns_canvas.yview)
        self.columns_canvas.configure(yscrollcommand=scrollbar.set)
        scrollbar.pack(side=tk.RIGHT, fill=tk.Y)
        self.columns_canvas.pack(side=tk.LEFT, fill=tk.BOTH, expand=True)
        self.columns_frame = ttk.Frame(self.columns_canvas)
        self.columns_canvas.create_window((0, 0), window=self.columns_frame, anchor=tk.NW)
        self.columns_frame.bind(
            "<Configure>",
            lambda _: self.columns_canvas.configure(scrollregion=self.columns_canvas.bbox("all")),
        )

        aqi_frame = ttk.LabelFrame(controls, text="AQI")
        aqi_frame.grid(row=1, column=4, columnspan=2, sticky=tk.NW, padx=5)
        ttk.Label(aqi_frame, text="PM2.5 column:").grid(row=0, column=0, sticky=tk.W, padx=5, pady=2)
        self.pm_var = tk.StringVar()
        self.pm_combo = ttk.Combobox(aqi_frame, textvariable=self.pm_var, state="readonly", width=16)
        self.pm_combo.grid(row=0, column=1, padx=5)
        ttk.Label(aqi_frame, text="EPA table:").grid(row=1, column=0, sticky=tk.W, padx=5, pady=2)
        self.table_var = tk.StringVar(value="2024")
        ttk.Combobox(
            aqi_frame, textvariable=self.table_var, values=list(BREAKPOINTS), state="readonly", width=16
        ).grid(row=1, column=1, padx=5)
        self.convert_var = tk.BooleanVar(value=False)
        ttk.Checkbutton(aqi_frame, text="Plot PM2.5 as AQI", variable=self.convert_var).grid(
            row=2, column=0, columnspan=2, sticky=tk.W, padx=5, pady=2
        )

        ttk.Label(self, text=AQI_NOTE, foreground="gray").pack(anchor=tk.W, padx=10)

        figure_frame = ttk.Frame(self)
        figure_frame.pack(fill=tk.BOTH, expand=True, padx=5, pady=5)
        self.fig = Figure(figsize=(7, 4), dpi=100, layout="constrained")
        self.canvas = FigureCanvasTkAgg(self.fig, master=figure_frame)
        self.canvas.get_tk_widget().pack(side=tk.TOP, fill=tk.BOTH, expand=True)
        NavigationToolbar2Tk(self.canvas, figure_frame).update()

    def on_data_loaded(self) -> None:
        """Refresh the column choices after a new file is loaded."""
        df = self.app.df
        columns = [str(column) for column in df.columns]
        self.time_combo["values"] = columns
        self.time_var.set(detect_time_column(df) or columns[0])
        self.pm_combo["values"] = columns
        self.pm_var.set(detect_pm25_column(df) or "")

        for widget in self.columns_frame.winfo_children():
            widget.destroy()
        ticked = set(numeric_columns(df))
        self.column_vars = {}
        for row, column in enumerate(columns):
            var = tk.BooleanVar(value=column in ticked)
            ttk.Checkbutton(self.columns_frame, text=column, variable=var).grid(row=row, column=0, sticky=tk.W)
            self.column_vars[column] = var
        self.plot_button.config(state=tk.NORMAL)

    def _collect_series(self, frame: pd.DataFrame) -> list[tuple[str, pd.Series, bool]]:
        """Build the (label, values, is_aqi) list to draw."""
        convert = self.convert_var.get() and self.pm_var.get() in frame.columns
        pm_column = self.pm_var.get()
        series: list[tuple[str, pd.Series, bool]] = []
        for column, var in self.column_vars.items():
            if var.get() and column != self.time_var.get() and not (convert and column == pm_column):
                series.append((column, pd.to_numeric(frame[column], errors="coerce"), False))
        if convert:
            series.append((f"{pm_column} AQI", series_to_aqi(frame[pm_column], self.table_var.get()), True))
        return series

    @staticmethod
    def _draw_aqi(ax: object, x: np.ndarray, values: pd.Series) -> None:
        """Draw AQI as a line colored by category."""
        points = np.column_stack([x, values.to_numpy(dtype=float)])
        segments = np.stack([points[:-1], points[1:]], axis=1)
        segments = segments[np.isfinite(segments).all(axis=(1, 2))]
        colors = [aqi_color(value) for value in segments[:, :, 1].mean(axis=1)]
        ax.add_collection(LineCollection(segments, colors=colors, linewidth=2))
        ax.autoscale_view()

    @staticmethod
    def _aqi_handles() -> list[Patch]:
        """Build legend entries for the AQI categories."""
        return [Patch(color=category.color, label=category.label) for category in CATEGORIES]

    def draw(self) -> None:
        """Draw the selected columns."""
        if self.app.df is None:
            return
        try:
            frame, dropped = sorted_by_time(self.app.df, self.time_var.get())
        except ValueError as error:
            messagebox.showerror("Cannot read time column", str(error))
            return
        series = self._collect_series(frame)
        if not series:
            messagebox.showwarning("Nothing to plot", "Tick at least one column, or choose a PM2.5 column for AQI.")
            return

        x = date2num(frame[self.time_var.get()].dt.tz_localize(None).to_numpy())
        self.fig.clear()
        subplots = self.layout_var.get() == "Subplots"
        count = len(series) if subplots else 1
        axes = self.fig.subplots(count, 1, sharex=True, squeeze=False).ravel().tolist()
        any_aqi = False
        for index, (label, values, is_aqi) in enumerate(series):
            ax = axes[index if subplots else 0]
            if is_aqi:
                self._draw_aqi(ax, x, values)
                any_aqi = True
            else:
                ax.plot(x, values.to_numpy(dtype=float), label=label)
            if subplots:
                ax.set_ylabel("AQI (per reading)" if is_aqi else label)
                if is_aqi:
                    ax.legend(handles=self._aqi_handles(), loc="upper right", fontsize="x-small")

        if not subplots:
            ax = axes[0]
            only_aqi = len(series) == 1 and any_aqi
            ax.set_ylabel("AQI (per reading)" if only_aqi else "Value")
            handles = ax.get_legend_handles_labels()[0] + (self._aqi_handles() if any_aqi else [])
            ax.legend(handles=handles, loc="upper right", fontsize="x-small")

        locator = AutoDateLocator()
        for ax in axes:
            ax.grid(True)
            ax.xaxis.set_major_locator(locator)
            ax.xaxis.set_major_formatter(ConciseDateFormatter(locator))
        axes[-1].set_xlabel("Time (UTC)")
        self.fig.suptitle(self.app.source_name)
        self.canvas.draw()
        self.save_button.config(state=tk.NORMAL)
        self.app.set_status(
            f"Plotted {len(frame):,} rows" + (f"; skipped {dropped:,} with unreadable times" if dropped else "")
        )

    def save(self) -> None:
        """Save the current figure as a PNG."""
        name = filedialog.asksaveasfilename(
            title="Save plot", defaultextension=".png", filetypes=[("PNG files", "*.png")]
        )
        if not name:
            return
        try:
            self.fig.savefig(name, dpi=300)
        except OSError as error:
            messagebox.showerror("Save failed", str(error))
            return
        self.app.set_status(f"Saved {Path(name).name}")


class GapsTab(ttk.Frame):
    """Finds missing timesteps and adds blank rows for them."""

    def __init__(self, parent: ttk.Notebook, app: "App") -> None:
        super().__init__(parent)
        self.app = app
        self.result: PadResult | None = None

        controls = ttk.Frame(self)
        controls.pack(fill=tk.X, padx=5, pady=5)
        ttk.Label(controls, text="Time column:").pack(side=tk.LEFT, padx=5)
        self.time_var = tk.StringVar()
        self.time_combo = ttk.Combobox(controls, textvariable=self.time_var, state="readonly", width=22)
        self.time_combo.pack(side=tk.LEFT, padx=5)
        ttk.Label(controls, text="Interval:").pack(side=tk.LEFT, padx=5)
        self.interval_var = tk.StringVar(value=AUTO_INTERVAL)
        ttk.Combobox(
            controls, textvariable=self.interval_var, values=list(INTERVALS), state="readonly", width=12
        ).pack(side=tk.LEFT, padx=5)
        self.run_button = ttk.Button(controls, text="Find Gaps", command=self.run, state=tk.DISABLED)
        self.run_button.pack(side=tk.LEFT, padx=5)
        self.save_button = ttk.Button(controls, text="Save Filled CSV", command=self.save, state=tk.DISABLED)
        self.save_button.pack(side=tk.LEFT, padx=5)

        self.summary = tk.Text(self, height=9, wrap=tk.WORD)
        self.summary.pack(fill=tk.X, padx=10, pady=5)
        self.table = make_table(self)

    def on_data_loaded(self) -> None:
        """Refresh the column choices after a new file is loaded."""
        self.time_combo["values"] = [str(column) for column in self.app.df.columns]
        self.time_var.set(detect_time_column(self.app.df) or str(self.app.df.columns[0]))
        self.result = None
        self.summary.delete("1.0", tk.END)
        self.run_button.config(state=tk.NORMAL)
        self.save_button.config(state=tk.DISABLED)

    def run(self) -> None:
        """Find gaps in the loaded data."""
        if self.app.df is None:
            return
        try:
            self.result = pad_timesteps(self.app.df, self.time_var.get(), INTERVALS[self.interval_var.get()])
        except ValueError as error:
            messagebox.showerror("Cannot fill gaps", str(error))
            return
        missing = self.result.missing
        lines = [
            f"Interval: {self.result.interval}",
            f"Rows: {len(self.app.df):,} original, {len(self.result.data):,} after filling",
            f"Missing timesteps added as blank rows: {len(missing):,}",
        ]
        if self.result.off_interval_rows:
            lines.append(f"Rows between interval steps (kept as is): {self.result.off_interval_rows:,}")
        lines.extend(f"  {stamp:%Y-%m-%d %H:%M:%S} UTC" for stamp in missing[:MISSING_LISTED])
        if len(missing) > MISSING_LISTED:
            lines.append(f"  ... and {len(missing) - MISSING_LISTED:,} more")
        self.summary.delete("1.0", tk.END)
        self.summary.insert("1.0", "\n".join(lines))
        fill_table_from_frame(self.table, self.result.data)
        self.save_button.config(state=tk.NORMAL)

    def save(self) -> None:
        """Save the filled data."""
        if self.result is not None and (path := ask_save_csv(self.result.data, "Save filled data")):
            self.app.set_status(f"Saved {path.name}")


class TemperatureTab(ttk.Frame):
    """Converts one temperature column between Fahrenheit and Celsius."""

    def __init__(self, parent: ttk.Notebook, app: "App") -> None:
        super().__init__(parent)
        self.app = app
        self.result: pd.DataFrame | None = None

        controls = ttk.Frame(self)
        controls.pack(fill=tk.X, padx=5, pady=5)
        ttk.Label(controls, text="Column:").pack(side=tk.LEFT, padx=5)
        self.column_var = tk.StringVar()
        self.column_combo = ttk.Combobox(controls, textvariable=self.column_var, state="readonly", width=22)
        self.column_combo.pack(side=tk.LEFT, padx=5)
        self.direction_var = tk.StringVar(value=F_TO_C)
        ttk.Radiobutton(controls, text="F to C", variable=self.direction_var, value=F_TO_C).pack(side=tk.LEFT, padx=5)
        ttk.Radiobutton(controls, text="C to F", variable=self.direction_var, value=C_TO_F).pack(side=tk.LEFT, padx=5)
        ttk.Label(controls, text="Decimals:").pack(side=tk.LEFT, padx=5)
        self.decimals_var = tk.IntVar(value=2)
        ttk.Spinbox(controls, from_=0, to=6, width=4, textvariable=self.decimals_var, state="readonly").pack(side=tk.LEFT)
        self.run_button = ttk.Button(controls, text="Convert", command=self.run, state=tk.DISABLED)
        self.run_button.pack(side=tk.LEFT, padx=5)
        self.save_button = ttk.Button(controls, text="Save Converted CSV", command=self.save, state=tk.DISABLED)
        self.save_button.pack(side=tk.LEFT, padx=5)
        self.table = make_table(self)

    def on_data_loaded(self) -> None:
        """Refresh the column choices after a new file is loaded."""
        columns = numeric_columns(self.app.df)
        self.column_combo["values"] = columns
        temperature = [column for column in columns if "temp" in str(column).lower()]
        self.column_var.set(temperature[0] if temperature else (columns[0] if columns else ""))
        self.result = None
        self.run_button.config(state=tk.NORMAL)
        self.save_button.config(state=tk.DISABLED)

    def run(self) -> None:
        """Convert the chosen column, always starting from the loaded data."""
        if self.app.df is None or self.column_var.get() not in self.app.df.columns:
            messagebox.showwarning("No column", "Choose a numeric temperature column.")
            return
        try:
            self.result = convert_temperature(
                self.app.df, self.column_var.get(), self.direction_var.get(), self.decimals_var.get()
            )
        except ValueError as error:
            messagebox.showerror("Cannot convert", str(error))
            return
        fill_table_from_frame(self.table, self.result)
        self.save_button.config(state=tk.NORMAL)
        self.app.set_status(f"Converted {self.column_var.get()}; the loaded file is unchanged")

    def save(self) -> None:
        """Save the converted data."""
        if self.result is not None and (path := ask_save_csv(self.result, "Save converted data")):
            self.app.set_status(f"Saved {path.name}")


class BoundsTab(ttk.Frame):
    """Shows the minimum, maximum and range of every column."""

    def __init__(self, parent: ttk.Notebook, app: "App") -> None:
        super().__init__(parent)
        self.app = app
        self.results: pd.DataFrame | None = None

        controls = ttk.Frame(self)
        controls.pack(fill=tk.X, padx=5, pady=5)
        self.stats_var = tk.BooleanVar(value=False)
        ttk.Checkbutton(
            controls, text="Include mean, median, std dev", variable=self.stats_var, command=self.refresh
        ).pack(side=tk.LEFT, padx=5)
        ttk.Label(controls, text="Decimals:").pack(side=tk.LEFT, padx=5)
        self.precision_var = tk.IntVar(value=2)
        ttk.Spinbox(
            controls, from_=0, to=6, width=4, textvariable=self.precision_var, state="readonly", command=self.refresh
        ).pack(side=tk.LEFT)
        self.export_button = ttk.Button(controls, text="Export CSV", command=self.export, state=tk.DISABLED)
        self.export_button.pack(side=tk.LEFT, padx=10)
        self.table = make_table(self)
        self.table.bind("<Control-c>", self.copy_row)

    def on_data_loaded(self) -> None:
        """Refresh after a new file is loaded."""
        self.refresh()

    def refresh(self) -> None:
        """Recalculate and redraw the bounds table."""
        if self.app.df is None:
            return
        self.results = compute_bounds(self.app.df, include_stats=self.stats_var.get())
        precision = self.precision_var.get()
        text_columns = {"Column", "Data Type"}
        rows = [
            [str(row[column]) if column in text_columns else format_cell(row[column], precision) for column in self.results.columns]
            for _, row in self.results.iterrows()
        ]
        fill_table(self.table, list(self.results.columns), rows)
        self.export_button.config(state=tk.NORMAL)

    def copy_row(self, _event: object = None) -> None:
        """Copy the selected row as tab-separated text."""
        selection = self.table.selection()
        if selection:
            self.clipboard_clear()
            self.clipboard_append("\t".join(str(value) for value in self.table.item(selection[0])["values"]))
            self.app.set_status("Copied row")

    def export(self) -> None:
        """Export the unrounded results."""
        if self.results is not None and (path := ask_save_csv(self.results, "Export bounds")):
            self.app.set_status(f"Saved {path.name}")


class App:
    """Main window. Holds the loaded data and the tabs that use it."""

    def __init__(self, root: tk.Misc) -> None:
        self.root = root
        self.df: pd.DataFrame | None = None
        self.source_name = ""
        root.title(f"PurpleAir Visualizer {__version__}")
        root.geometry("1100x800")

        top = ttk.Frame(root, padding=10)
        top.pack(fill=tk.X)
        self.file_label = ttk.Label(top, text="No file loaded. Download sensor data below, or open a CSV.")
        self.file_label.pack(side=tk.LEFT, fill=tk.X, expand=True)
        ttk.Button(top, text="Open CSV...", command=self.choose_file).pack(side=tk.RIGHT)

        self.notebook = ttk.Notebook(root)
        self.notebook.pack(fill=tk.BOTH, expand=True, padx=10, pady=5)
        self.download = DownloadTab(self.notebook, self)
        self.preview = PreviewTab(self.notebook, self)
        self.plot = PlotTab(self.notebook, self)
        self.gaps = GapsTab(self.notebook, self)
        self.temperature = TemperatureTab(self.notebook, self)
        self.bounds = BoundsTab(self.notebook, self)
        self.tabs = (self.download, self.preview, self.plot, self.gaps, self.temperature, self.bounds)
        titles = ("Download", "Data Preview", "Plot", "Fill Gaps", "Temperature", "Column Bounds")
        for tab, title in zip(self.tabs, titles):
            self.notebook.add(tab, text=title)

        self.status = ttk.Label(root, text="Ready", relief=tk.SUNKEN, anchor=tk.W)
        self.status.pack(fill=tk.X, side=tk.BOTTOM)

    def set_status(self, message: str) -> None:
        """Show a message in the status bar."""
        self.status.config(text=message)

    def choose_file(self) -> None:
        """Ask for a CSV file and load it."""
        name = filedialog.askopenfilename(
            title="Open CSV", filetypes=[("CSV files", "*.csv"), ("All files", "*.*")]
        )
        if name:
            self.load_path(Path(name))

    def load_path(self, path: Path) -> None:
        """Load a CSV file and refresh every tab.

        Args:
            path: The file to load.
        """
        try:
            df = load_csv(path)
        except (OSError, ValueError) as error:
            messagebox.showerror("Could not open file", str(error))
            return
        if df.empty:
            messagebox.showerror("Could not open file", f"{path.name} has no data rows.")
            return
        self.df = df
        self.source_name = path.name
        self.file_label.config(text=f"{path.name}: {len(df):,} rows, {len(df.columns)} columns")
        for tab in self.tabs:
            tab.on_data_loaded()
        self.set_status("File loaded")


def main() -> None:
    """Start the app, opening a CSV file if one is given on the command line."""
    root = tk.Tk()
    app = App(root)
    if len(sys.argv) > 1:
        app.load_path(Path(sys.argv[1]))
    root.mainloop()


if __name__ == "__main__":
    main()
