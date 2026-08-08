# RAG First Pass Notes

This pass adds a conservative local RAG evidence layer without replacing the existing breeding knowledge tools.

## Positioning

- `germplasm_search`: local material and accession clues.
- `crop_kg_search`: local structured crop-pack relationship clues.
- `evidence_search`: local text evidence snippets from curated `.md` and `.txt` files.

RAG snippets are treated as candidate evidence. They should be cited with the returned `local-rag://` URL, `source_path`, line range, and excerpt, and they should not be used to infer claims beyond the retrieved text.

## Files Added

- `co_scientist/knowledge/rag.py`: builds, saves, loads, and searches a lightweight evidence index.
- `co_scientist/tools/evidence.py`: exposes `evidence_search` to agents.
- `scripts/build_rag_index.py`: builds `data/rag/evidence_index.json` from `docs/rag_sources`.
- `scripts/search_evidence.py`: command-line search over the built index.
- `docs/rag_sources/README.md`: source directory guidance.

## Basic Workflow

1. Put curated local materials in `docs/rag_sources/`.
2. Run `python scripts/build_rag_index.py`.
3. Test retrieval with `python scripts/search_evidence.py "your query"`.
4. Run sessions normally; Evidence Curator should be the primary caller of `evidence_search`, and Breeding Designer / Risk Reviewer / Iteration Orchestrator-triggered revision steps can reuse it when they need local evidence or gap checks.

## Stability Boundary

The first pass intentionally avoids online crawling, automatic PDF parsing, external embedding calls, reranking, and database schema changes. This keeps the existing breeding scientist flow stable while adding a usable local evidence layer.

