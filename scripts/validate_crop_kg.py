"""Validate a local crop-pack KG JSON file."""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from co_scientist.knowledge.crop_kg import validate_crop_kg


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument(
        "json_path",
        nargs="?",
        default="docs/templates/foxtail_millet_kg_seed.json",
        help="Path to a crop-pack KG JSON file.",
    )
    args = parser.parse_args()

    result = validate_crop_kg(Path(args.json_path))
    print(
        f"Validated {result.node_count} nodes and {result.edge_count} edges in {result.path}"
    )
    if not result.issues:
        print("No issues found.")
        return 0
    for issue in result.issues:
        print(f"{issue.level.upper()}: {issue.item_id}: {issue.message}")
    return 0 if result.ok else 1


if __name__ == "__main__":
    raise SystemExit(main())
