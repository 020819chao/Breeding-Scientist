"""Search the public germplasm seed CSV."""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from co_scientist.knowledge.germplasm import (  # noqa: E402
    load_germplasm_records,
    search_germplasm_records,
)

DEFAULT_CSV = "docs/templates/germplasm_resources_public_seed.csv"


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("query", help="Keyword query, e.g. lodging or plant architecture.")
    parser.add_argument("--csv", default=DEFAULT_CSV, help="Path to germplasm CSV.")
    parser.add_argument("--crop", default=None, help="Optional crop filter.")
    parser.add_argument("--trait", default=None, help="Optional trait filter.")
    parser.add_argument(
        "--min-confidence",
        choices=["low", "medium", "high"],
        default=None,
        help="Optional minimum data confidence.",
    )
    parser.add_argument("--limit", type=int, default=5, help="Maximum number of records.")
    args = parser.parse_args()

    records = load_germplasm_records(Path(args.csv))
    results = search_germplasm_records(
        records,
        args.query,
        crop=args.crop,
        trait=args.trait,
        min_confidence=args.min_confidence,
        limit=args.limit,
    )

    if not results:
        print("No matching germplasm records found.")
        return 0

    for i, result in enumerate(results, start=1):
        record = result.record
        print(f"{i}. {record['accession_id']} | {record['name']} | {record['crop']}")
        print(f"   traits: {record['primary_traits']}")
        print(f"   confidence: {record.get('data_confidence') or 'unknown'}")
        print(f"   use: {record.get('breeding_use') or '(not specified)'}")
        print(f"   risk: {record.get('risk_notes') or '(not specified)'}")
        print(f"   source: {record.get('source_refs') or '(missing)'}")
        print(f"   matched: {', '.join(result.matched_fields) or '(filter match)'}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
