# Contributing

Bug reports, fixes and suggestions are welcome through [GitHub issues](https://github.com/AndrewsForestLTER/purpleair-visualizer/issues) and pull requests.

## Reporting a bug

Please include the app version (shown in the title bar), your operating system, the steps that caused the problem, and what you expected. If you can, attach a few rows of a CSV that shows it.

## Making a change

1. Fork the repository and branch from `main`.
2. Install with `pip install -e ".[dev]"`.
3. Add or update tests, and run `pytest`.
4. Update the docs and `CHANGELOG.md` if behavior changes.
5. Open a pull request.

## Code layout

Calculations and network calls live in `aqi.py`, `data.py`, `processing.py` and `api.py`, and don't depend on the GUI so they can be tested directly. `gui.py` only handles the interface.

## Style

Follow PEP 8 with lines under 120 characters, type hints, Google-style docstrings, f-strings and `pathlib`. Changes that alter output values need a test showing the expected result, and a source for any scientific constant.

## License

By contributing, you agree that your contributions are dedicated to the public domain under [CC0 1.0 Universal](LICENSE).
