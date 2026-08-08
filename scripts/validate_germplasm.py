"""Validate a germplasm resource CSV file."""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from co_scientist.knowledge.germplasm import validate_germplasm_csv  # noqa: E402


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "csv_path",
        nargs="?",
        default="docs/templates/germplasm_resources_public_seed.csv",
        help="Path to a germplasm CSV file.",
    )
    args = parser.parse_args()

    result = validate_germplasm_csv(Path(args.csv_path))
    print(f"Validated {result.row_count} rows in {result.path}")

    for issue in result.issues:
        print(f"{issue.level.upper()} row {issue.row_number}: {issue.message}")

    if result.ok:
        if not result.issues:
            print("No issues found.")
        return 0
    return 1


if __name__ == "__main__":
    raise SystemExit(main())
