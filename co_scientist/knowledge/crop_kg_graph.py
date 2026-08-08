"""Generic validation and search helpers for crop-pack knowledge graphs."""

from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path
from typing import Any

REQUIRED_NODE_FIELDS = ["id", "name", "type", "summary", "source_refs", "data_confidence"]
REQUIRED_EDGE_FIELDS = [
    "id",
    "subject",
    "predicate",
    "object",
    "evidence",
    "source_refs",
    "data_confidence",
]

VALID_NODE_TYPES = {
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
}
VALID_CONFIDENCE = {"high", "medium", "low"}

SEARCH_NODE_FIELDS = ["id", "name", "type", "aliases", "summary", "source_refs", "notes"]
SEARCH_EDGE_FIELDS = ["id", "predicate", "evidence", "source_refs", "notes"]


@dataclass(frozen=True)
class ValidationIssue:
    item_id: str
    level: str
    message: str


@dataclass(frozen=True)
class CropKGValidationResult:
    path: Path
    node_count: int
    edge_count: int
    issues: list[ValidationIssue]

    @property
    def ok(self) -> bool:
        return not any(issue.level == "error" for issue in self.issues)


@dataclass(frozen=True)
class CropKGSearchResult:
    score: int
    node: dict[str, Any]
    matched_fields: list[str]
    edges: list[dict[str, Any]]


def validate_crop_kg_graph(path: Path) -> CropKGValidationResult:
    """Validate a crop-pack KG JSON file without mutating it."""

    issues: list[ValidationIssue] = []
    graph = _read_json(path)
    nodes = graph.get("nodes")
    edges = graph.get("edges")
    if not isinstance(nodes, list):
        issues.append(ValidationIssue("nodes", "error", "Field 'nodes' must be a list."))
        nodes = []
    if not isinstance(edges, list):
        issues.append(ValidationIssue("edges", "error", "Field 'edges' must be a list."))
        edges = []

    seen_nodes: dict[str, int] = {}
    for idx, node in enumerate(nodes, start=1):
        if not isinstance(node, dict):
            issues.append(ValidationIssue(f"node[{idx}]", "error", "Node must be an object."))
            continue
        node_id = str(node.get("id") or "").strip()
        item_id = node_id or f"node[{idx}]"
        for field in REQUIRED_NODE_FIELDS:
            if not _present(node.get(field)):
                issues.append(ValidationIssue(item_id, "error", f"Missing required node field {field!r}."))
        if node_id in seen_nodes:
            issues.append(
                ValidationIssue(
                    item_id,
                    "error",
                    f"Duplicate node id {node_id!r}; first seen at node index {seen_nodes[node_id]}.",
                )
            )
        elif node_id:
            seen_nodes[node_id] = idx
        node_type = str(node.get("type") or "").strip()
        if node_type and node_type not in VALID_NODE_TYPES:
            issues.append(
                ValidationIssue(
                    item_id,
                    "error",
                    f"Invalid node type {node_type!r}; expected one of {sorted(VALID_NODE_TYPES)}.",
                )
            )
        confidence = str(node.get("data_confidence") or "").strip()
        if confidence and confidence not in VALID_CONFIDENCE:
            issues.append(
                ValidationIssue(
                    item_id,
                    "error",
                    f"Invalid data_confidence {confidence!r}; expected one of {sorted(VALID_CONFIDENCE)}.",
                )
            )
        aliases = node.get("aliases", [])
        if aliases is not None and not isinstance(aliases, list):
            issues.append(ValidationIssue(item_id, "error", "Node aliases must be a list."))

    node_ids = set(seen_nodes)
    seen_edges: dict[str, int] = {}
    for idx, edge in enumerate(edges, start=1):
        if not isinstance(edge, dict):
            issues.append(ValidationIssue(f"edge[{idx}]", "error", "Edge must be an object."))
            continue
        edge_id = str(edge.get("id") or "").strip()
        item_id = edge_id or f"edge[{idx}]"
        for field in REQUIRED_EDGE_FIELDS:
            if not _present(edge.get(field)):
                issues.append(ValidationIssue(item_id, "error", f"Missing required edge field {field!r}."))
        if edge_id in seen_edges:
            issues.append(
                ValidationIssue(
                    item_id,
                    "error",
                    f"Duplicate edge id {edge_id!r}; first seen at edge index {seen_edges[edge_id]}.",
                )
            )
        elif edge_id:
            seen_edges[edge_id] = idx
        for endpoint in ("subject", "object"):
            endpoint_id = str(edge.get(endpoint) or "").strip()
            if endpoint_id and endpoint_id not in node_ids:
                issues.append(
                    ValidationIssue(item_id, "error", f"Unknown {endpoint} node {endpoint_id!r}.")
                )
        confidence = str(edge.get("data_confidence") or "").strip()
        if confidence and confidence not in VALID_CONFIDENCE:
            issues.append(
                ValidationIssue(
                    item_id,
                    "error",
                    f"Invalid data_confidence {confidence!r}; expected one of {sorted(VALID_CONFIDENCE)}.",
                )
            )

    return CropKGValidationResult(
        path=path,
        node_count=len(nodes),
        edge_count=len(edges),
        issues=issues,
    )


def load_crop_kg_graph(path: Path) -> dict[str, Any]:
    """Load a crop-pack KG after validating that it has no hard errors."""

    result = validate_crop_kg_graph(path)
    if not result.ok:
        messages = "; ".join(
            f"{issue.item_id}: {issue.message}"
            for issue in result.issues
            if issue.level == "error"
        )
        raise ValueError(f"Invalid crop KG: {messages}")
    return _read_json(path)


def search_crop_kg_graph(
    graph: dict[str, Any],
    query: str,
    *,
    node_type: str | None = None,
    crop: str | None = None,
    min_confidence: str | None = None,
    include_edges: bool = True,
    limit: int = 10,
) -> list[CropKGSearchResult]:
    """Search graph nodes with deterministic keyword scoring and edge expansion."""

    query_terms = _terms(query)
    type_filter = (node_type or "").strip()
    crop_term = (crop or "").strip().lower()
    min_rank = _confidence_rank(min_confidence)
    edges_by_node = _edges_by_node(graph.get("edges", []))

    results: list[CropKGSearchResult] = []
    for node in graph.get("nodes", []):
        if type_filter and node.get("type") != type_filter:
            continue
        if crop_term and crop_term not in _node_crop_text(node):
            continue
        if min_rank is not None and _confidence_rank(node.get("data_confidence")) < min_rank:
            continue
        score, matched_fields = _score_node(node, query_terms)
        edge_hits = _matching_edges(edges_by_node.get(node.get("id"), []), query_terms)
        if query_terms and score == 0 and not edge_hits:
            continue
        score += sum(edge_score for edge_score, _ in edge_hits)
        expanded_edges = edges_by_node.get(node.get("id"), []) if include_edges else []
        if edge_hits:
            matched_fields = sorted({*matched_fields, "edges"})
        results.append(
            CropKGSearchResult(
                score=score or 1,
                node=node,
                matched_fields=matched_fields,
                edges=expanded_edges,
            )
        )

    return sorted(
        results,
        key=lambda result: (
            -result.score,
            result.node.get("data_confidence") != "high",
            result.node.get("data_confidence") != "medium",
            result.node.get("id", ""),
        ),
    )[:limit]


def _read_json(path: Path) -> dict[str, Any]:
    with path.open(encoding="utf-8") as f:
        data = json.load(f)
    if not isinstance(data, dict):
        raise ValueError("millet KG JSON root must be an object")
    return data


def _present(value: Any) -> bool:
    if isinstance(value, str):
        return bool(value.strip())
    return value is not None


def _score_node(node: dict[str, Any], query_terms: list[str]) -> tuple[int, list[str]]:
    if not query_terms:
        return 1, []

    score = 0
    matched_fields: list[str] = []
    for field in SEARCH_NODE_FIELDS:
        value = _stringify(node.get(field)).lower()
        if not value:
            continue
        hits = sum(1 for term in query_terms if term in value)
        if not hits:
            continue
        weight = 4 if field in {"id", "name", "aliases"} else 2 if field == "summary" else 1
        score += hits * weight
        matched_fields.append(field)
    return score, matched_fields


def _matching_edges(edges: list[dict[str, Any]], query_terms: list[str]) -> list[tuple[int, dict[str, Any]]]:
    if not query_terms:
        return []
    out: list[tuple[int, dict[str, Any]]] = []
    for edge in edges:
        text = " ".join(_stringify(edge.get(field)).lower() for field in SEARCH_EDGE_FIELDS)
        hits = sum(1 for term in query_terms if term in text)
        if hits:
            out.append((hits, edge))
    return out


def _edges_by_node(edges: list[dict[str, Any]]) -> dict[str, list[dict[str, Any]]]:
    out: dict[str, list[dict[str, Any]]] = {}
    for edge in edges:
        if not isinstance(edge, dict):
            continue
        for endpoint in (edge.get("subject"), edge.get("object")):
            if endpoint:
                out.setdefault(str(endpoint), []).append(edge)
    return out


def _node_crop_text(node: dict[str, Any]) -> str:
    values = [node.get("crop"), node.get("name"), node.get("summary"), node.get("aliases")]
    return " ".join(_stringify(value).lower() for value in values)


def _terms(text: str) -> list[str]:
    return [term for term in text.lower().replace(";", " ").replace(",", " ").split() if term]


def _stringify(value: Any) -> str:
    if value is None:
        return ""
    if isinstance(value, list):
        return " ".join(_stringify(item) for item in value)
    if isinstance(value, dict):
        return " ".join(_stringify(item) for item in value.values())
    return str(value)


def _confidence_rank(confidence: str | None) -> int:
    return {"low": 1, "medium": 2, "high": 3}.get((confidence or "").strip(), 0)
