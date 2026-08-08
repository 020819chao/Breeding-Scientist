from __future__ import annotations

from pathlib import Path

from co_scientist.knowledge.crop_kg import (
    DEFAULT_CROP_PACK,
    list_crop_kg_packs,
    load_crop_kg,
    normalize_crop_pack,
    resolve_crop_kg_packs,
    search_crop_kg,
    search_crop_kg_packs,
    validate_crop_kg,
)


def test_crop_kg_wraps_seed_foxtail_millet_pack() -> None:
    path = Path("docs/templates/foxtail_millet_kg_seed.json")

    result = validate_crop_kg(path)

    assert result.ok
    assert normalize_crop_pack("foxtail millet") == DEFAULT_CROP_PACK
    assert normalize_crop_pack("\u8c37\u5b50") == DEFAULT_CROP_PACK


def test_crop_kg_pack_template_is_valid_blank_graph() -> None:
    path = Path("docs/templates/crop_kg_pack_template.json")

    result = validate_crop_kg(path)

    assert result.ok
    assert result.node_count == 0
    assert result.edge_count == 0


def test_crop_kg_search_supports_crop_hint_and_edges() -> None:
    graph = load_crop_kg(Path("docs/templates/foxtail_millet_kg_seed.json"))

    results = search_crop_kg(
        graph,
        "CAPS Seita.5G404900",
        crop="\u8c37\u5b50",
        node_type="marker",
        limit=3,
    )

    assert results
    assert results[0].node["id"] == "marker:Seita.5G404900_CAPS"
    assert any(edge["id"] == "edge:CAPS_supports_MAS" for edge in results[0].edges)


def test_crop_kg_registry_lists_default_and_configured_packs(tmp_cfg) -> None:
    tmp_cfg.knowledge.crop_kg_packs = {
        "sorghum": "docs/templates/foxtail_millet_kg_seed.json",
    }

    packs = list_crop_kg_packs(tmp_cfg)

    assert {pack.key for pack in packs} == {"foxtail_millet", "sorghum"}
    assert resolve_crop_kg_packs(tmp_cfg, "sorghum")[0].key == "sorghum"
    assert normalize_crop_pack("sorghum", tmp_cfg) == "sorghum"


def test_crop_kg_pack_search_can_scan_all_configured_packs(tmp_cfg) -> None:
    tmp_cfg.knowledge.crop_kg_packs = {
        "sorghum": "docs/templates/foxtail_millet_kg_seed.json",
    }

    results = search_crop_kg_packs(
        tmp_cfg,
        "CAPS Seita.5G404900",
        node_type="marker",
        limit=5,
    )

    assert {result.pack.key for result in results} == {"foxtail_millet", "sorghum"}
    assert all(result.match.node["id"] == "marker:Seita.5G404900_CAPS" for result in results)
