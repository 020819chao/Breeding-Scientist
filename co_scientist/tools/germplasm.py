"""Local germplasm resource search tool."""

from __future__ import annotations

import time
from typing import Any

from ..config import Config
from ..knowledge.germplasm import load_germplasm_records, search_germplasm_records
from .base import ToolCtx, ToolResult


class GermplasmSearchTool:
    name = "germplasm_search"
    description = (
        "Search the local breeding germplasm resource CSV. Use this to find candidate "
        "foxtail millet or crop materials, parent lines, accession records, trait "
        "evidence, breeding uses, risks, and source references. Results are local "
        "resource clues, not final validated recommendations."
    )
    input_schema: dict[str, Any] = {
        "type": "object",
        "properties": {
            "query": {
                "type": "string",
                "description": "Keyword query such as lodging architecture, drought tolerance, QTL, 263A.",
            },
            "crop": {
                "type": "string",
                "description": "Optional crop filter, for example foxtail millet.",
            },
            "trait": {
                "type": "string",
                "description": "Optional trait filter, for example yield traits or plant architecture.",
            },
            "min_confidence": {
                "type": "string",
                "enum": ["low", "medium", "high"],
                "description": "Optional minimum data confidence.",
            },
            "max_results": {
                "type": "integer",
                "minimum": 1,
                "maximum": 20,
                "description": "Number of records to return. Default 5.",
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
            limit = max(1, min(int(args.get("max_results") or 5), 20))
        except (TypeError, ValueError):
            return ToolResult(is_error=True, error_message="max_results must be an integer")

        path = self._cfg.germplasm_csv_path
        if not path.exists():
            return ToolResult(
                is_error=True,
                error_message=f"germplasm CSV not found: {path}",
            )

        try:
            records = load_germplasm_records(path)
            matches = search_germplasm_records(
                records,
                query,
                crop=(args.get("crop") or None),
                trait=(args.get("trait") or None),
                min_confidence=(args.get("min_confidence") or None),
                limit=limit,
            )
        except ValueError as e:
            return ToolResult(is_error=True, error_message=str(e))

        results = []
        for match in matches:
            record = match.record
            source_url = _first_source_url(record.get("source_refs") or "")
            results.append(
                {
                    "accession_id": record.get("accession_id"),
                    "name": record.get("name"),
                    "url": source_url,
                    "crop": record.get("crop"),
                    "germplasm_type": record.get("germplasm_type"),
                    "primary_traits": record.get("primary_traits"),
                    "summary": record.get("summary"),
                    "strengths": record.get("strengths"),
                    "weaknesses": record.get("weaknesses"),
                    "known_genes_qtls": record.get("known_genes_qtls"),
                    "markers": record.get("markers"),
                    "phenotype_evidence": record.get("phenotype_evidence"),
                    "genotype_evidence": record.get("genotype_evidence"),
                    "breeding_use": record.get("breeding_use"),
                    "risk_notes": record.get("risk_notes"),
                    "source_refs": record.get("source_refs"),
                    "data_confidence": record.get("data_confidence"),
                    "matched_fields": match.matched_fields,
                    "score": match.score,
                    "usage_boundary": (
                        "Treat this as a germplasm resource clue. Do not infer unlisted "
                        "genes, markers, availability, or validated breeding value."
                    ),
                }
            )

        payload = {
            "query": query,
            "source_csv": str(path),
            "n": len(results),
            "results": results,
        }
        return ToolResult(
            content=payload,
            duration_ms=int((time.monotonic() - t0) * 1000),
            result_bytes=len(str(payload)),
        )


def _first_source_url(source_refs: str) -> str | None:
    for part in source_refs.replace(";", " ").split():
        if part.startswith(("http://", "https://")):
            return part
    return None
