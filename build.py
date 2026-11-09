"""Build a single-file desktop executable with PyInstaller."""

from pathlib import Path

import PyInstaller.__main__

ROOT = Path(__file__).resolve().parent

if __name__ == "__main__":
    PyInstaller.__main__.run(
        [
            str(ROOT / "src" / "purpleair_visualizer" / "__main__.py"),
            "--name=PurpleAirVisualizer",
            "--onefile",
            "--windowed",
            f"--paths={ROOT / 'src'}",
            "--clean",
            "--noconfirm",
        ]
    )
