"""Local evidence RAG search tool."""

from __future__ import annotations

import time
from typing import Any

from ..config import Config
from ..knowledge.rag import load_evidence_index, search_evidence_index
from .base import ToolCtx, ToolResult


class EvidenceSearchTool:
    name = "evidence_search"
    description = (
        "Search the local RAG evidence index built from docs/rag_sources. Use this "
        "to find source-grounded text snippets from local papers, notes, reviews, "
        "or advisor-provided materials. Results are candidate evidence snippets; "
        "quote them carefully and mark evidence gaps when no relevant chunk is found."
    )
    input_schema: dict[str, Any] = {
        "type": "object",
        "properties": {
            "query": {
                "type": "string",
                "description": "Keyword query, for example lodging resistance SiNF-YC2 dense planting.",
            },
            "source_filter": {
                "type": "string",
                "description": "Optional substring filter for source file names.",
            },
            "max_results": {
                "type": "integer",
                "minimum": 1,
                "maximum": 10,
                "description": "Number of chunks to return. Default 5.",
            },
        },
        "required": ["query"],
    }

    def __init__(self, cfg: Config) -> None:
        self._cfg = cfg

    async def call(self, args: dict[str, Any], ctx: ToolCtx) -> ToolResult:
        t0 = time.monotonic()
        query = (args.get("query") or "").strip()
        if not query:
            return ToolResult(is_error=True, error_message="empty query")

        try:
            limit = max(1, min(int(args.get("max_results") or 5), 10))
        except (TypeError, ValueError):
            return ToolResult(is_error=True, error_message="max_results must be an integer")

        path = self._cfg.rag_index_path
        if not path.exists():
            return ToolResult(
                is_error=True,
                error_message=(
                    f"RAG evidence index not found: {path}. Run scripts/build_rag_index.py first."
                ),
            )

        try:
            index = load_evidence_index(path)
            matches = search_evidence_index(
                index,
                query,
                source_filter=(args.get("source_filter") or None),
                limit=limit,
            )
        except (OSError, ValueError) as e:
            return ToolResult(is_error=True, error_message=str(e))

        results = []
        for match in matches:
            chunk = match.chunk
            excerpt = _short_excerpt(chunk.text)
            local_url = f"local-rag://{chunk.source_path}#L{chunk.start_line}-L{chunk.end_line}"
            results.append(
                {
                    "chunk_id": chunk.chunk_id,
                    "url": local_url,
                    "source_path": chunk.source_path,
                    "title": chunk.title,
                    "line_range": f"{chunk.start_line}-{chunk.end_line}",
                    "excerpt": excerpt,
                    "matched_terms": match.matched_terms,
                    "score": match.score,
                    "usage_boundary": (
                        "Treat this as a local RAG evidence snippet. Cite the local-rag URL, "
                        "source_path, and line_range, and do not infer claims not present "
                        "in the excerpt."
                    ),
                }
            )

        payload = {
            "query": query,
            "source_index": str(path),
            "n": len(results),
            "results": results,
        }
        return ToolResult(
            content=payload,
            duration_ms=int((time.monotonic() - t0) * 1000),
            result_bytes=len(str(payload)),
        )


def _short_excerpt(text: str, *, max_chars: int = 900) -> str:
    cleaned = " ".join(text.split())
    if len(cleaned) <= max_chars:
        return cleaned
    return cleaned[: max_chars - 3].rstrip() + "..."
