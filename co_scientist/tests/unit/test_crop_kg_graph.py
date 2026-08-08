from __future__ import annotations

import json
from pathlib import Path

from co_scientist.knowledge.crop_kg_graph import (
    load_crop_kg_graph,
    search_crop_kg_graph,
    validate_crop_kg_graph,
)


def test_public_seed_crop_kg_graph_is_valid() -> None:
    path = Path("docs/templates/foxtail_millet_kg_seed.json")
    result = validate_crop_kg_graph(path)
    assert result.ok
    assert result.node_count == 19
    assert result.edge_count == 17
    assert result.issues == []


def test_crop_kg_graph_validation_rejects_unknown_edge_endpoint(tmp_path: Path) -> None:
    path = tmp_path / "bad_kg.json"
    path.write_text(
        json.dumps(
            {
                "nodes": [
                    {
                        "id": "trait:lodging",
                        "name": "lodging",
                        "type": "trait",
                        "summary": "Demo trait.",
                        "source_refs": "https://example.test/source",
                        "data_confidence": "medium",
                    }
                ],
                "edges": [
                    {
                        "id": "edge:bad",
                        "subject": "trait:lodging",
                        "predicate": "related_to",
                        "object": "missing:node",
                        "evidence": "Demo edge.",
                        "source_refs": "https://example.test/source",
                        "data_confidence": "medium",
                    }
                ],
            }
        ),
        encoding="utf-8",
    )

    result = validate_crop_kg_graph(path)

    assert not result.ok
    assert any("Unknown object node" in issue.message for issue in result.issues)


def test_crop_kg_graph_search_finds_marker_and_neighbor_edges() -> None:
    graph = load_crop_kg_graph(Path("docs/templates/foxtail_millet_kg_seed.json"))

    results = search_crop_kg_graph(graph, "CAPS Seita.5G404900", node_type="marker", limit=3)

    assert results
    assert results[0].node["id"] == "marker:Seita.5G404900_CAPS"
    edge_ids = {edge["id"] for edge in results[0].edges}
    assert "edge:Seita5G404900_has_CAPS" in edge_ids
    assert "edge:CAPS_supports_MAS" in edge_ids


def test_crop_kg_graph_search_can_find_risk_from_edges() -> None:
    graph = load_crop_kg_graph(Path("docs/templates/foxtail_millet_kg_seed.json"))

    results = search_crop_kg_graph(graph, "yield penalty", node_type="germplasm", limit=5)

    ids = {result.node["id"] for result in results}
    assert "germplasm:ARCH-263A" in ids
