"""Run the real app against the example file. Skipped where no display exists."""

from collections.abc import Iterator
from pathlib import Path

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
