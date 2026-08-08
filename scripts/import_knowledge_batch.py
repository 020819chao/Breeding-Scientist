"""Validate and activate one portable knowledge-base intake batch."""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from co_scientist.knowledge.intake import (  # noqa: E402
    DEFAULT_ACTIVE_ROOT,
    import_knowledge_batch,
)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("batch_dir", type=Path, help="Directory containing manifest.json.")
    parser.add_argument(
        "--target-root",
        type=Path,
        default=DEFAULT_ACTIVE_ROOT,
        help="Active knowledge directory (default: data/knowledge/active).",
    )
    parser.add_argument(
        "--catalog",
        type=Path,
        default=None,
        help="Catalog path (default: <target-root>/catalog.json).",
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Validate and build the merged result without activating it.",
    )
    args = parser.parse_args(argv)
    try:
        result = import_knowledge_batch(
            args.batch_dir,
            active_root=args.target_root,
            catalog_path=args.catalog,
            dry_run=args.dry_run,
        )
    except (OSError, ValueError) as exc:
        print(f"Knowledge batch import failed: {exc}")
        return 1

    print(f"Batch: {result.batch_id}")
    print(f"Active: {'yes' if result.activated else 'dry-run'}")
    print(f"Catalog: {result.catalog_path}")
    print(json.dumps(result.stats, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
