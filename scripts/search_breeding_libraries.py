"""Search local marker/QTL, phenotype protocol, and field-trial CSV libraries."""

from __future__ import annotations

import argparse
import sys
from collections.abc import Callable
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from co_scientist.config import load_config  # noqa: E402
from co_scientist.knowledge.breeding_libraries import (  # noqa: E402
    LibrarySearchResult,
    load_field_trial_records,
    load_marker_qtl_records,
    load_phenotype_protocol_records,
    search_field_trial_records,
    search_marker_qtl_records,
    search_phenotype_protocol_records,
)

Loader = Callable[[Path], list[dict[str, str]]]
Searcher = Callable[..., list[LibrarySearchResult]]


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("query", help="Keyword query, e.g. lodging, drought, blast, quality.")
    parser.add_argument(
        "--kind",
        choices=["all", "marker_qtl", "phenotype_protocol", "field_trial"],
        default="all",
        help="Library kind to search.",
    )
    parser.add_argument("--crop", default=None, help="Optional crop filter.")
    parser.add_argument("--limit", type=int, default=5, help="Maximum results per library.")
    parser.add_argument("--marker-qtl-csv", default=None, help="Path to marker/QTL CSV.")
    parser.add_argument(
        "--phenotype-protocol-csv",
        default=None,
        help="Path to phenotype protocol CSV.",
    )
    parser.add_argument("--field-trial-csv", default=None, help="Path to field-trial CSV.")
    args = parser.parse_args()

    cfg = load_config()
    paths = {
        "marker_qtl": Path(args.marker_qtl_csv) if args.marker_qtl_csv else cfg.marker_qtl_csv_path,
        "phenotype_protocol": (
            Path(args.phenotype_protocol_csv)
            if args.phenotype_protocol_csv
            else cfg.phenotype_protocol_csv_path
        ),
        "field_trial": Path(args.field_trial_csv) if args.field_trial_csv else cfg.field_trial_csv_path,
    }
    loaders: dict[str, Loader] = {
        "marker_qtl": load_marker_qtl_records,
        "phenotype_protocol": load_phenotype_protocol_records,
        "field_trial": load_field_trial_records,
    }
    searchers: dict[str, Searcher] = {
        "marker_qtl": search_marker_qtl_records,
        "phenotype_protocol": search_phenotype_protocol_records,
        "field_trial": search_field_trial_records,
    }

    selected = list(loaders) if args.kind == "all" else [args.kind]
    any_hits = False
    for kind in selected:
        records = loaders[kind](paths[kind])
        results = searchers[kind](records, args.query, crop=args.crop, limit=args.limit)
        print(f"[{kind}] {len(results)} hits from {paths[kind]}")
        if not results:
            continue
        any_hits = True
        for index, result in enumerate(results, start=1):
            _print_result(kind, index, result)

    if not any_hits:
        print("No matching breeding library records found.")
    return 0


def _print_result(kind: str, index: int, result: LibrarySearchResult) -> None:
    record = result.record
    if kind == "marker_qtl":
        title = f"{record['marker_id']} | {record['marker_name']} | {record['trait']}"
        details = [
            ("gene_or_qtl", record.get("gene_or_qtl")),
            ("validation", record.get("validation_status")),
            ("materials", record.get("linked_materials")),
            ("risk", record.get("risk_notes")),
        ]
    elif kind == "phenotype_protocol":
        title = f"{record['protocol_id']} | {record['trait']} | {record['target_environment']}"
        details = [
            ("method", record.get("measurement_method")),
            ("thresholds", record.get("decision_thresholds")),
            ("validation", record.get("validation_status")),
            ("risk", record.get("risk_notes")),
        ]
    else:
        title = f"{record['trial_id']} | {record['trait']} | {record['environment']}"
        details = [
            ("materials", record.get("materials")),
            ("design", record.get("test_design")),
            ("outcome", record.get("decision_outcome")),
            ("risk", record.get("risk_notes")),
        ]

    print(f"  {index}. {title}")
    print(f"     score: {result.score}")
    print(f"     confidence: {record.get('data_confidence') or 'unknown'}")
    print(f"     source: {record.get('source_refs') or '(missing)'}")
    print(f"     matched: {', '.join(result.matched_fields) or '(filter match)'}")
    for label, value in details:
        if value:
            print(f"     {label}: {value}")


if __name__ == "__main__":
    raise SystemExit(main())
