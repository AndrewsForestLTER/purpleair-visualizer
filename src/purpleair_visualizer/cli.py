"""Command-line entry point for the column bounds summary."""

from __future__ import annotations

import argparse
import logging
import sys
from pathlib import Path

from purpleair_visualizer.data import load_csv
from purpleair_visualizer.processing import compute_bounds, format_cell

logger = logging.getLogger(__name__)


def bounds_main(argv: list[str] | None = None) -> int:
    """Print the bounds of each column in a CSV file.

    Args:
        argv: Command-line arguments. Defaults to ``sys.argv``.

    Returns:
        The process exit code.
    """
    parser = argparse.ArgumentParser(description="Summarize the min/max bounds of each CSV column.")
    parser.add_argument("csv_file", type=Path)
    parser.add_argument("--stats", action="store_true", help="include mean, median and std dev")
    parser.add_argument("--precision", type=int, default=2, help="decimal places to display")
    parser.add_argument("--save", action="store_true", help="also write <csv_file>_bounds.csv")
    args = parser.parse_args(argv)
    logging.basicConfig(level=logging.INFO, format="%(message)s", stream=sys.stdout)

    try:
        df = load_csv(args.csv_file)
    except (OSError, ValueError) as error:
        logger.error("Could not read %s: %s", args.csv_file, error)
        return 1

    results = compute_bounds(df, include_stats=args.stats)
    display = results.copy()
    for column in display.columns.difference(["Column", "Data Type"]):
        display[column] = display[column].map(lambda value: format_cell(value, args.precision))
    logger.info("%s rows, %s columns\n", f"{len(df):,}", len(df.columns))
    logger.info("%s", display.to_string(index=False))

    if args.save:
        output = args.csv_file.with_name(f"{args.csv_file.stem}_bounds.csv")
        try:
            results.to_csv(output, index=False)
        except OSError as error:
            logger.error("Could not write %s: %s", output, error)
            return 1
        logger.info("\nSaved %s", output)
    return 0


if __name__ == "__main__":
    sys.exit(bounds_main())
