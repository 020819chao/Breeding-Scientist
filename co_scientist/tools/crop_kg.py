"""Generic crop-pack knowledge graph search tool."""

from __future__ import annotations

import time
from typing import Any

from ..config import Config
from ..knowledge.crop_kg import (
    CropKGPack,
    list_crop_kg_packs,
    resolve_crop_kg_packs,
    search_crop_kg_packs,
)
from .base import ToolCtx, ToolResult


class CropKGSearchTool:
    name = "crop_kg_search"
    description = (
        "Search local crop-pack knowledge graphs for minor-grain breeding. Use this "
        "to connect germplasm, traits, genes/QTL, markers, environments, phenotyping "
        "plans, breeding strategies, risks, and source references. Searches configured "
        "minor-grain crop packs; the default seed pack is foxtail millet / Setaria "
        "italica. Results are structured local graph clues, not final proof."
    )
    input_schema: dict[str, Any] = {
        "type": "object",
        "properties": {
            "query": {
                "type": "string",
                "description": "Keyword query such as lodging, dense planting, Seita.5G404900, CAPS, QTL.",
            },
            "crop": {
                "type": "string",
                "description": (
                    "Optional crop hint. If omitted, all configured crop-pack KGs are searched. "
                    "The default seed pack supports foxtail millet / Setaria italica aliases."
                ),
            },
            "node_type": {
                "type": "string",
                "enum": [
                    "crop",
                    "germplasm",
                    "trait",
                    "gene_qtl",
                    "marker",
                    "environment",
                    "evidence",
                    "breeding_strategy",
                    "risk",
                    "phenotype_protocol",
                ],
                "description": "Optional node type filter.",
            },
            "min_confidence": {
                "type": "string",
                "enum": ["low", "medium", "high"],
                "description": "Optional minimum data confidence.",
            },
            "include_edges": {
                "type": "boolean",
                "description": "Whether to include neighboring KG edges. Default true.",
            },
            "max_results": {
                "type": "integer",
                "minimum": 1,
                "maximum": 20,
                "description": "Number of nodes to return. Default 5.",
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

        crop_hint = (args.get("crop") or "").strip() or None
        try:
            packs = resolve_crop_kg_packs(self._cfg, crop_hint)
        except ValueError as e:
            return ToolResult(is_error=True, error_message=str(e))

        try:
            limit = max(1, min(int(args.get("max_results") or 5), 20))
        except (TypeError, ValueError):
            return ToolResult(is_error=True, error_message="max_results must be an integer")

        missing = [pack for pack in packs if not pack.path.exists()]
        if len(missing) == len(packs):
            missing_paths = ", ".join(str(pack.path) for pack in missing)
            return ToolResult(is_error=True, error_message=f"crop KG not found: {missing_paths}")

        try:
            matches = search_crop_kg_packs(
                self._cfg,
                query,
                crop=crop_hint,
                node_type=(args.get("node_type") or None),
                min_confidence=(args.get("min_confidence") or None),
                include_edges=bool(args.get("include_edges", True)),
                limit=limit,
            )
        except ValueError as e:
            return ToolResult(is_error=True, error_message=str(e))

        results = []
        for pack_match in matches:
            pack = pack_match.pack
            match = pack_match.match
            node = match.node
            source_url = _first_source_url(node.get("source_refs") or "")
            results.append(
                {
                    "id": node.get("id"),
                    "name": node.get("name"),
                    "type": node.get("type"),
                    "url": source_url,
                    "crop_pack": pack.key,
                    "crop_scope": pack.crop_name,
                    "source_kg": str(pack.path),
                    "aliases": node.get("aliases", []),
                    "summary": node.get("summary"),
                    "source_refs": node.get("source_refs"),
                    "data_confidence": node.get("data_confidence"),
                    "matched_fields": match.matched_fields,
                    "score": match.score,
                    "edges": [_format_edge(edge, pack_match.nodes_by_id) for edge in match.edges],
                    "usage_boundary": (
                        "Treat this as a local crop-pack KG clue. Do not infer unlisted "
                        "genes, markers, causal effects, availability, or validated "
                        "breeding value."
                    ),
                }
            )

        first_pack = matches[0].pack if matches else (packs[0] if len(packs) == 1 else None)
        payload = {
            "query": query,
            "searched_crop_packs": [_pack_payload(pack) for pack in packs],
            "configured_crop_packs": [_pack_payload(pack) for pack in list_crop_kg_packs(self._cfg)],
            "crop_pack": first_pack.key if first_pack else None,
            "crop_scope": first_pack.crop_name if first_pack else None,
            "source_kg": str(first_pack.path) if first_pack else None,
            "n": len(results),
            "results": results,
        }
        return ToolResult(
            content=payload,
            duration_ms=int((time.monotonic() - t0) * 1000),
            result_bytes=len(str(payload)),
        )


def _pack_payload(pack: CropKGPack) -> dict[str, Any]:
    return {
        "key": pack.key,
        "crop_name": pack.crop_name,
        "source_kg": str(pack.path),
        "available": pack.path.exists(),
        "aliases": list(pack.aliases),
    }


def _format_edge(edge: dict[str, Any], nodes_by_id: dict[str, dict[str, Any]]) -> dict[str, Any]:
    subject = nodes_by_id.get(edge.get("subject"), {})
    obj = nodes_by_id.get(edge.get("object"), {})
    return {
        "id": edge.get("id"),
        "subject": edge.get("subject"),
        "subject_name": subject.get("name"),
        "predicate": edge.get("predicate"),
        "object": edge.get("object"),
        "object_name": obj.get("name"),
        "evidence": edge.get("evidence"),
        "source_refs": edge.get("source_refs"),
        "data_confidence": edge.get("data_confidence"),
    }


def _first_source_url(source_refs: str) -> str | None:
    for part in source_refs.replace(";", " ").split():
        if part.startswith(("http://", "https://")):
            return part
    return None
