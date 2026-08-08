"""Search a local crop-pack KG JSON file."""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from co_scientist.knowledge.crop_kg import load_crop_kg, search_crop_kg

DEFAULT_JSON = "docs/templates/foxtail_millet_kg_seed.json"


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("query", help="Keyword query.")
    parser.add_argument("--json", default=DEFAULT_JSON, help="Path to crop-pack KG JSON.")
    parser.add_argument("--crop", default=None, help="Optional crop hint.")
    parser.add_argument("--node-type", default=None, help="Optional node type filter.")
    parser.add_argument(
        "--min-confidence",
        choices=["low", "medium", "high"],
        default=None,
        help="Optional minimum data confidence.",
    )
    parser.add_argument("--limit", type=int, default=5, help="Maximum result nodes.")
    args = parser.parse_args()

    graph = load_crop_kg(Path(args.json))
    results = search_crop_kg(
        graph,
        args.query,
        crop=args.crop,
        node_type=args.node_type,
        min_confidence=args.min_confidence,
        limit=args.limit,
    )
    if not results:
        print("No matching crop KG nodes found.")
        return 0
    for result in results:
        node = result.node
        print(f"{node['id']} | {node['name']} | {node['type']} | score={result.score}")
        print(f"  summary: {node.get('summary', '')}")
        print(f"  confidence: {node.get('data_confidence', '')}")
        print(f"  matched_fields: {', '.join(result.matched_fields) or '-'}")
        if result.edges:
            print("  edges:")
            for edge in result.edges[:5]:
                print(
                    f"    {edge.get('subject')} --{edge.get('predicate')}--> "
                    f"{edge.get('object')}: {edge.get('evidence')}"
                )
        print(f"  sources: {node.get('source_refs', '')}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
