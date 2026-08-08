"""Generic crop-pack KG helpers for minor-grain breeding evidence.

The first crop pack is the existing foxtail millet graph. This module gives the
rest of the system a crop-neutral entry point so future sorghum, broomcorn
millet, buckwheat, oat, or other minor-grain packs can be added without exposing
crop-specific tool names to agents.
"""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Any

from ..config import PROJECT_ROOT, Config
from .crop_kg_graph import (
    CropKGSearchResult,
    CropKGValidationResult,
    load_crop_kg_graph,
    search_crop_kg_graph,
    validate_crop_kg_graph,
)

DEFAULT_CROP_PACK = "foxtail_millet"
DEFAULT_CROP_NAME = "foxtail millet"

_PRESET_CROP_NAMES = {
    DEFAULT_CROP_PACK: DEFAULT_CROP_NAME,
    "rice": "rice",
    "sorghum": "sorghum",
    "broomcorn_millet": "broomcorn millet",
    "proso_millet": "proso millet",
    "buckwheat": "buckwheat",
    "oat": "oat",
    "quinoa": "quinoa",
}

_PRESET_ALIASES = {
    DEFAULT_CROP_PACK: {
        "foxtail millet",
        "foxtail_millet",
        "setaria italica",
        "setaria",
        "millet",
        "\u8c37\u5b50",
        "\u7c9f",
        "\u72d7\u5c3e\u8349",
    },
    "rice": {"rice", "oryza sativa", "oryza", "\u6c34\u7a3b", "\u7a3b\u7c73", "\u7a3b\u5b50"},
    "sorghum": {"sorghum", "sorghum bicolor", "\u9ad8\u7cb1"},
    "broomcorn_millet": {
        "broomcorn millet",
        "panicum miliaceum",
        "\u9ecd\u5b50",
        "\u7cdc\u5b50",
    },
    "proso_millet": {
        "proso millet",
        "panicum miliaceum",
        "\u9ecd\u5b50",
        "\u7cdc\u5b50",
    },
    "buckwheat": {"buckwheat", "fagopyrum", "\u835e\u9ea6"},
    "oat": {"oat", "avena", "\u71d5\u9ea6"},
    "quinoa": {"quinoa", "chenopodium quinoa", "\u85dc\u9ea6"},
}


@dataclass(frozen=True)
class CropKGPack:
    key: str
    crop_name: str
    path: Path
    aliases: tuple[str, ...]


@dataclass(frozen=True)
class CropKGPackSearchResult:
    pack: CropKGPack
    match: CropKGSearchResult
    nodes_by_id: dict[str, dict[str, Any]]


def list_crop_kg_packs(cfg: Config) -> list[CropKGPack]:
    """Return configured crop-pack KGs.

    Foxtail millet is always registered as the seed pack. Extra minor-grain
    packs can be added through ``[knowledge.crop_kg_packs]``.
    """

    packs: dict[str, CropKGPack] = {
        DEFAULT_CROP_PACK: CropKGPack(
            key=DEFAULT_CROP_PACK,
            crop_name=DEFAULT_CROP_NAME,
            path=cfg.crop_kg_path,
            aliases=tuple(sorted(_aliases_for_pack(DEFAULT_CROP_PACK, DEFAULT_CROP_NAME))),
        )
    }
    configured_packs = dict(cfg.knowledge.crop_kg_packs or {})
    configured_packs.update(cfg.active_crop_kg_packs)
    for key, path_text in sorted(configured_packs.items()):
        pack_key = _normalize_pack_key(key)
        if not pack_key or not path_text:
            continue
        crop_name = _PRESET_CROP_NAMES.get(pack_key, pack_key.replace("_", " "))
        packs[pack_key] = CropKGPack(
            key=pack_key,
            crop_name=crop_name,
            path=_resolve_path(path_text),
            aliases=tuple(sorted(_aliases_for_pack(pack_key, crop_name))),
        )
    return list(packs.values())


def normalize_crop_pack(crop: str | None, cfg: Config | None = None) -> str:
    """Return the configured crop-pack key for a crop hint."""

    if not crop:
        return DEFAULT_CROP_PACK
    value = _normalize_alias(crop)
    packs = list_crop_kg_packs(cfg) if cfg is not None else _default_known_packs()
    for pack in packs:
        if value in {_normalize_alias(alias) for alias in pack.aliases}:
            return pack.key
    supported = ", ".join(sorted(pack.crop_name for pack in packs))
    raise ValueError(
        f"Unsupported crop KG pack {crop!r}. Configured crop KG packs: {supported or 'none'}."
    )


def resolve_crop_kg_packs(cfg: Config, crop: str | None = None) -> list[CropKGPack]:
    """Resolve one or more KG packs for a search request."""

    packs = list_crop_kg_packs(cfg)
    if not crop:
        return packs
    pack_key = normalize_crop_pack(crop, cfg)
    return [pack for pack in packs if pack.key == pack_key]


def crop_kg_path(cfg: Config, crop: str | None = None) -> Path:
    """Resolve the KG path for a crop-pack.

    The config uses ``crop_kg_json`` for the default crop-pack path.
    """

    packs = resolve_crop_kg_packs(cfg, crop)
    if not packs:
        raise ValueError(f"No crop KG pack configured for {crop!r}.")
    return packs[0].path


def validate_crop_kg(path: Path) -> CropKGValidationResult:
    """Validate a crop-pack KG JSON file."""

    return validate_crop_kg_graph(path)


def load_crop_kg(path: Path) -> dict[str, Any]:
    """Load a crop-pack KG JSON file after validation."""

    return load_crop_kg_graph(path)


def search_crop_kg(
    graph: dict[str, Any],
    query: str,
    *,
    node_type: str | None = None,
    crop: str | None = None,
    min_confidence: str | None = None,
    include_edges: bool = True,
    limit: int = 10,
) -> list[CropKGSearchResult]:
    """Search a crop-pack KG with deterministic keyword scoring."""

    return search_crop_kg_graph(
        graph,
        query,
        node_type=node_type,
        crop=None,
        min_confidence=min_confidence,
        include_edges=include_edges,
        limit=limit,
    )


def search_crop_kg_packs(
    cfg: Config,
    query: str,
    *,
    crop: str | None = None,
    node_type: str | None = None,
    min_confidence: str | None = None,
    include_edges: bool = True,
    limit: int = 10,
) -> list[CropKGPackSearchResult]:
    """Search configured crop-pack KGs and return pack-aware matches."""

    results: list[CropKGPackSearchResult] = []
    for pack in resolve_crop_kg_packs(cfg, crop):
        if not pack.path.exists():
            continue
        graph = load_crop_kg(pack.path)
        nodes_by_id = {node["id"]: node for node in graph.get("nodes", []) if node.get("id")}
        for match in search_crop_kg(
            graph,
            query,
            node_type=node_type,
            min_confidence=min_confidence,
            include_edges=include_edges,
            limit=limit,
        ):
            results.append(CropKGPackSearchResult(pack=pack, match=match, nodes_by_id=nodes_by_id))
    return sorted(
        results,
        key=lambda result: (
            -result.match.score,
            result.match.node.get("data_confidence") != "high",
            result.match.node.get("data_confidence") != "medium",
            result.pack.key,
            result.match.node.get("id", ""),
        ),
    )[:limit]


def _aliases_for_pack(pack_key: str, crop_name: str) -> set[str]:
    aliases = {
        pack_key,
        pack_key.replace("_", " "),
        crop_name,
        crop_name.replace(" ", "_"),
    }
    aliases.update(_PRESET_ALIASES.get(pack_key, set()))
    return {_normalize_alias(alias) for alias in aliases if alias}


def _default_known_packs() -> list[CropKGPack]:
    return [
        CropKGPack(
            key=key,
            crop_name=_PRESET_CROP_NAMES.get(key, key.replace("_", " ")),
            path=Path(),
            aliases=tuple(sorted(_aliases_for_pack(key, _PRESET_CROP_NAMES.get(key, key)))),
        )
        for key in _PRESET_CROP_NAMES
    ]


def _normalize_pack_key(value: str) -> str:
    key = _normalize_alias(value)
    key = key.replace("-", "_").replace(" ", "_")
    return "".join(ch for ch in key if ch.isalnum() or ch == "_")


def _normalize_alias(value: str) -> str:
    return " ".join(str(value or "").strip().lower().replace("-", " ").replace("_", " ").split())


def _resolve_path(value: str) -> Path:
    path = Path(value)
    return path if path.is_absolute() else (PROJECT_ROOT / path)
