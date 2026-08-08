from __future__ import annotations

import json
from pathlib import Path

from co_scientist.config import Config, KnowledgeCfg, StorageCfg
from co_scientist.knowledge.snapshot import (
    capture_knowledge_snapshot,
    config_for_knowledge_snapshot,
    materialize_knowledge_snapshot,
    verify_knowledge_snapshot,
)


def test_knowledge_snapshot_detects_active_file_changes(tmp_path: Path) -> None:
    active = tmp_path / "active"
    rag = active / "rag"
    kg = active / "kg"
    rag.mkdir(parents=True)
    kg.mkdir()
    files = {
        "germplasm_csv": active / "germplasm.csv",
        "rag_index_json": active / "evidence_index.json",
        "marker_qtl_csv": active / "marker.csv",
        "phenotype_protocol_csv": active / "phenotype.csv",
        "field_trial_csv": active / "field.csv",
    }
    for path in files.values():
        path.write_text(path.name, encoding="utf-8")
    (kg / "rice.json").write_text("{}", encoding="utf-8")
    (rag / "rice.md").write_text("rice evidence", encoding="utf-8")
    catalog = active / "catalog.json"
    catalog.write_text(
        json.dumps(
            {
                "active_batch_id": "rice-test",
                "germplasm_csv": str(files["germplasm_csv"]),
                "rag_sources_dir": str(rag),
                "rag_index_json": str(files["rag_index_json"]),
                "marker_qtl_csv": str(files["marker_qtl_csv"]),
                "phenotype_protocol_csv": str(files["phenotype_protocol_csv"]),
                "field_trial_csv": str(files["field_trial_csv"]),
                "crop_kg_packs": {"rice": str(kg / "rice.json")},
            }
        ),
        encoding="utf-8",
    )
    cfg = Config(
        storage=StorageCfg(data_dir=str(tmp_path / "data")),
        knowledge=KnowledgeCfg(active_catalog=str(catalog)),
    )

    snapshot = capture_knowledge_snapshot(cfg)
    assert snapshot["snapshot_id"].startswith("kb_")
    assert verify_knowledge_snapshot(cfg, snapshot)[0] is True

    files["germplasm_csv"].write_text("changed", encoding="utf-8")
    ok, message = verify_knowledge_snapshot(cfg, snapshot)
    assert ok is False
    assert "changed:germplasm" in message


def test_materialized_snapshot_binds_runtime_config_to_immutable_copies(tmp_path: Path) -> None:
    active = tmp_path / "active"
    kg = active / "kg"
    rag = active / "rag"
    kg.mkdir(parents=True)
    rag.mkdir()
    files = {
        "germplasm_csv": active / "germplasm.csv",
        "rag_index_json": active / "evidence_index.json",
        "marker_qtl_csv": active / "marker.csv",
        "phenotype_protocol_csv": active / "phenotype.csv",
        "field_trial_csv": active / "field.csv",
    }
    for path in files.values():
        path.write_text(path.name, encoding="utf-8")
    (kg / "rice.json").write_text("rice kg", encoding="utf-8")
    (rag / "rice.md").write_text("rice evidence", encoding="utf-8")
    catalog = active / "catalog.json"
    catalog.write_text(
        json.dumps(
            {
                "active_batch_id": "rice-test",
                "germplasm_csv": str(files["germplasm_csv"]),
                "rag_sources_dir": str(rag),
                "rag_index_json": str(files["rag_index_json"]),
                "marker_qtl_csv": str(files["marker_qtl_csv"]),
                "phenotype_protocol_csv": str(files["phenotype_protocol_csv"]),
                "field_trial_csv": str(files["field_trial_csv"]),
                "crop_kg_packs": {"rice": str(kg / "rice.json")},
            }
        ),
        encoding="utf-8",
    )
    cfg = Config(
        storage=StorageCfg(data_dir=str(tmp_path / "data")),
        knowledge=KnowledgeCfg(active_catalog=str(catalog)),
    )

    snapshot = materialize_knowledge_snapshot(cfg, capture_knowledge_snapshot(cfg))
    bound = config_for_knowledge_snapshot(cfg, snapshot)
    runtime_root = Path(snapshot["runtime_root"])
    assert runtime_root.is_dir()
    assert bound.germplasm_csv_path == runtime_root / "germplasm_resources.csv"
    assert bound.active_crop_kg_packs["rice"] == str(runtime_root / "kg/rice.json")

    files["germplasm_csv"].write_text("changed active source", encoding="utf-8")
    assert bound.germplasm_csv_path.read_text(encoding="utf-8") == "germplasm.csv"
