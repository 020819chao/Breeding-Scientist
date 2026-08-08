"""Search the local RAG evidence index."""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from co_scientist.config import load_config
from co_scientist.knowledge.rag import load_evidence_index, search_evidence_index


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("query", help="Keyword query.")
    parser.add_argument("--index", default=None, help="Path to evidence index JSON.")
    parser.add_argument("--source-filter", default=None, help="Optional source path substring filter.")
    parser.add_argument("--limit", type=int, default=5, help="Maximum result chunks.")
    args = parser.parse_args()

    cfg = load_config()
    index_path = Path(args.index) if args.index else cfg.rag_index_path
    index = load_evidence_index(index_path)
    results = search_evidence_index(
        index,
        args.query,
        source_filter=args.source_filter,
        limit=args.limit,
    )
    if not results:
        print("No matching evidence chunks found.")
        return 0
    for result in results:
        chunk = result.chunk
        excerpt = " ".join(chunk.text.split())
        if len(excerpt) > 500:
            excerpt = excerpt[:497].rstrip() + "..."
        print(f"{chunk.chunk_id} | score={result.score}")
        print(f"  source: {chunk.source_path}:{chunk.start_line}-{chunk.end_line}")
        print(f"  title: {chunk.title}")
        print(f"  matched_terms: {', '.join(result.matched_terms)}")
        print(f"  excerpt: {excerpt}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

