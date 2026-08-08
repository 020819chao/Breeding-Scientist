"""Validate local marker/QTL, phenotype protocol, and field-trial CSV libraries."""

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
    load_field_trial_records,
    load_marker_qtl_records,
    load_phenotype_protocol_records,
)

KindLoader = Callable[[Path], list[dict[str, str]]]


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--kind",
        choices=["all", "marker_qtl", "phenotype_protocol", "field_trial"],
        default="all",
        help="Library kind to validate.",
    )
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
    loaders: dict[str, KindLoader] = {
        "marker_qtl": load_marker_qtl_records,
        "phenotype_protocol": load_phenotype_protocol_records,
        "field_trial": load_field_trial_records,
    }

    selected = list(loaders) if args.kind == "all" else [args.kind]
    ok = True
    for kind in selected:
        path = paths[kind]
        try:
            records = loaders[kind](path)
        except Exception as exc:
            ok = False
            print(f"ERROR {kind}: {path}")
            print(f"  {exc}")
            continue
        print(f"OK {kind}: {len(records)} rows in {path}")

    return 0 if ok else 1


if __name__ == "__main__":
    raise SystemExit(main())
