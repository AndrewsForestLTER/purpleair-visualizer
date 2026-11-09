"""Run the real app against the example file. Skipped where no display exists."""

import time
from collections.abc import Iterator
from pathlib import Path

import pandas as pd
import pytest

tk = pytest.importorskip("tkinter")

from purpleair_visualizer import gui  # noqa: E402

EXAMPLE = Path(__file__).parent.parent / "examples" / "sample_purpleair.csv"


@pytest.fixture(scope="module")
def tk_root() -> Iterator[tk.Tk]:
    try:
        root = tk.Tk()
    except tk.TclError:
        pytest.skip("no display available")
    root.withdraw()
    yield root
    root.destroy()


@pytest.fixture
def app(tk_root: tk.Tk, monkeypatch: pytest.MonkeyPatch) -> Iterator[gui.App]:
    for name in ("showerror", "showwarning"):
        monkeypatch.setattr(gui.messagebox, name, lambda title, message: pytest.fail(f"{title}: {message}"))
    window = tk.Toplevel(tk_root)
    window.withdraw()
    application = gui.App(window)
    application.load_path(EXAMPLE)
    yield application
    window.destroy()


def pump(app: gui.App) -> None:
    """Run the event loop until the Download tab's background work ends."""
    deadline = time.monotonic() + 10
    while app.download.running and time.monotonic() < deadline:
        app.root.update()
        time.sleep(0.01)
    assert not app.download.running


def fill_form(app: gui.App, folder: Path) -> None:
    app.download.key_var.set("secret")
    app.download.sensor_var.set("115739")
    app.download.start_var.set("2025-01-01")
    app.download.end_var.set("2025-01-02")
    app.download.folder_var.set(str(folder))


def test_download_saves_and_opens(app: gui.App, tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(gui, "save_settings", lambda settings: None)
    seen = []

    def fake(job: object, progress: object, cancel: object) -> pd.DataFrame:
        seen.append(job)
        return pd.DataFrame({"time_stamp": ["2025-01-01 00:00:00+00:00"], "pm2.5_cf_1": [1.5]})

    monkeypatch.setattr(gui, "download_history", fake)
    fill_form(app, tmp_path)
    app.download.start()
    pump(app)
    assert seen[0].end == pd.Timestamp("2025-01-03", tz="UTC")  # the end date is included
    assert list(tmp_path.glob("115739 2025-01-01 2025-01-02 1 hour.csv"))
    assert app.source_name.startswith("115739")
    assert app.plot.pm_var.get() == "pm2.5_cf_1"


@pytest.mark.parametrize(("answer", "opened"), [(True, [gui.DEVELOP_URL]), (False, [])])
def test_key_help_opens_site_only_when_asked(
    app: gui.App, monkeypatch: pytest.MonkeyPatch, answer: bool, opened: list[str]
) -> None:
    urls: list[str] = []
    monkeypatch.setattr(gui.messagebox, "askyesno", lambda title, text: answer)
    monkeypatch.setattr(gui.webbrowser, "open", urls.append)
    app.download.show_key_help()
    assert urls == opened


@pytest.mark.parametrize(("answer", "opened"), [(True, [gui.MAP_URL]), (False, [])])
def test_sensor_help_opens_map_only_when_asked(
    app: gui.App, monkeypatch: pytest.MonkeyPatch, answer: bool, opened: list[str]
) -> None:
    urls: list[str] = []
    monkeypatch.setattr(gui.messagebox, "askyesno", lambda title, text: answer)
    monkeypatch.setattr(gui.webbrowser, "open", urls.append)
    app.download.show_sensor_help()
    assert urls == opened


def test_key_is_saved_only_when_asked(app: gui.App, monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    saved: list[dict] = []
    monkeypatch.setattr(gui, "save_settings", saved.append)
    fill_form(app, tmp_path)
    app.download.remember_var.set(False)
    app.download._save_choices()
    app.download.remember_var.set(True)
    app.download._save_choices()
    assert "api_key" not in saved[0]
    assert saved[1]["api_key"] == "secret"


@pytest.mark.parametrize(
    ("variable", "value", "message"),
    [("key_var", "", "API read key"), ("sensor_var", "abc", "whole number"), ("start_var", "soon", "YYYY-MM-DD")],
)
def test_bad_form_is_rejected(
    app: gui.App, tmp_path: Path, monkeypatch: pytest.MonkeyPatch, variable: str, value: str, message: str
) -> None:
    errors: list[str] = []
    monkeypatch.setattr(gui.messagebox, "showerror", lambda title, text: errors.append(text))
    fill_form(app, tmp_path)
    getattr(app.download, variable).set(value)
    app.download.start()
    assert not app.download.running
    assert message in errors[0]


def legend_labels(app: gui.App) -> list[str]:
    return [text.get_text() for text in app.plot.fig.axes[0].get_legend().get_texts()]


def test_detects_columns(app: gui.App) -> None:
    assert app.plot.time_var.get() == "time_stamp"
    assert app.plot.pm_var.get() == "pm2.5_cf_1"
    assert app.temperature.column_var.get() == "temperature"


def test_aqi_with_other_column_keeps_both_in_legend(app: gui.App) -> None:
    app.plot.convert_var.set(True)
    app.plot.draw()
    labels = legend_labels(app)
    assert "humidity" in labels
    assert "Hazardous (301+)" in labels


def test_aqi_plots_when_pm_column_unticked(app: gui.App) -> None:
    for var in app.plot.column_vars.values():
        var.set(False)
    app.plot.convert_var.set(True)
    app.plot.draw()
    assert app.plot.fig.axes[0].get_ylabel() == "AQI (per reading)"
    assert len(app.plot.fig.axes[0].collections) == 1


def test_subplots_and_replotting_reuse_one_canvas(app: gui.App) -> None:
    widgets = len(app.plot.canvas.get_tk_widget().master.winfo_children())
    app.plot.layout_var.set("Subplots")
    for _ in range(3):
        app.plot.draw()
    assert len(app.plot.fig.axes) == 4
    assert len(app.plot.canvas.get_tk_widget().master.winfo_children()) == widgets


def test_other_tabs_run(app: gui.App) -> None:
    app.gaps.run()
    assert app.gaps.result is not None
    assert len(app.gaps.result.missing) > 0
    app.temperature.run()
    assert app.temperature.result is not None
    app.bounds.stats_var.set(True)
    app.bounds.refresh()
    assert app.bounds.results is not None
