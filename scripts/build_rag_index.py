"""Build the local RAG evidence index from Markdown/text sources."""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from co_scientist.config import load_config
from co_scientist.knowledge.rag import build_evidence_index, save_evidence_index


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--sources", default=None, help="Source directory of .md/.txt files.")
    parser.add_argument("--out", default=None, help="Output index JSON path.")
    parser.add_argument("--chunk-chars", type=int, default=1400, help="Approximate chunk size.")
    parser.add_argument("--chunk-overlap", type=int, default=180, help="Approximate overlap size.")
    args = parser.parse_args()

    cfg = load_config()
    source_dir = Path(args.sources) if args.sources else cfg.rag_sources_dir
    out_path = Path(args.out) if args.out else cfg.rag_index_path

    index = build_evidence_index(
        source_dir,
        chunk_chars=args.chunk_chars,
        chunk_overlap=args.chunk_overlap,
    )
    save_evidence_index(index, out_path)
    print(f"Indexed {index.chunk_count} chunks from {source_dir} into {out_path}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

