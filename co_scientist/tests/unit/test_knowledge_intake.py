from __future__ import annotations

import json
import shutil
from pathlib import Path

import pytest

from co_scientist.config import Config, KnowledgeCfg
from co_scientist.knowledge import intake
from co_scientist.knowledge.crop_kg import list_crop_kg_packs
from co_scientist.knowledge.intake import import_knowledge_batch
from co_scientist.knowledge.rag import load_evidence_index


def test_import_knowledge_batch_activates_merged_catalog(tmp_path: Path) -> None:
    batch = tmp_path / "batch"
    sources = batch / "sources"
    (sources / "kg").mkdir(parents=True)
    (sources / "rag").mkdir()

    root = Path(__file__).resolve().parents[3]
    for filename in (
        "germplasm_resources_public_seed.csv",
        "marker_qtl_library_seed.csv",
        "phenotype_protocol_library_seed.csv",
        "field_trial_records_seed.csv",
    ):
        shutil.copyfile(root / "docs" / "templates" / filename, sources / filename)
    shutil.copyfile(
        root / "docs" / "templates" / "foxtail_millet_kg_seed.json",
        sources / "kg" / "foxtail_millet.json",
    )
    shutil.copyfile(
        root / "docs" / "rag_sources" / "foxtail_millet_drought_testing_note.md",
        sources / "rag" / "drought_note.md",
    )
    shutil.copyfile(
        root / "docs" / "rag_sources" / "foxtail_millet_drought_testing_note.md",
        sources / "rag" / "drought_note_copy.md",
    )
    (batch / "manifest.json").write_text(
        json.dumps(
            {
                "batch_id": "batch-test-2026-08-04",
                "schema_version": "1.0",
                "crop_scope": ["foxtail_millet"],
                "sources": {
                    "germplasm_csv": "sources/germplasm_resources_public_seed.csv",
                    "crop_kg_packs": [
                        {"crop_key": "foxtail_millet", "path": "sources/kg/foxtail_millet.json"}
                    ],
                    "rag_sources_dir": "sources/rag",
                    "rag_index_json": "outputs/evidence_index.json",
                    "marker_qtl_csv": "sources/marker_qtl_library_seed.csv",
                    "phenotype_protocol_csv": "sources/phenotype_protocol_library_seed.csv",
                    "field_trial_csv": "sources/field_trial_records_seed.csv",
                },
            }
        ),
        encoding="utf-8",
    )

    active_root = tmp_path / "active"
    catalog = active_root / "catalog.json"
    result = import_knowledge_batch(batch, active_root=active_root, catalog_path=catalog)

    assert result.activated is True
    assert result.stats["rag_chunks"] > 0
    assert result.stats["rag_documents_deduplicated"] >= 1
    assert (active_root / "germplasm_resources.csv").is_file()
    assert (active_root / "kg" / "foxtail_millet.json").is_file()
    assert (active_root / "last_import_report.json").is_file()
    assert result.stats["version_archive"] == "passed"
    assert (active_root.parent / "versions" / result.batch_id / "catalog.json").is_file()
    assert load_evidence_index(active_root / "evidence_index.json").chunk_count > 0

    cfg = Config(knowledge=KnowledgeCfg(active_catalog=str(catalog)))
    assert cfg.germplasm_csv_path == active_root / "germplasm_resources.csv"
    assert cfg.rag_sources_dir == active_root / "rag"
    assert cfg.crop_kg_path == active_root / "kg" / "foxtail_millet.json"
    assert list_crop_kg_packs(cfg)[0].path == active_root / "kg" / "foxtail_millet.json"

    germplasm_before = (active_root / "germplasm_resources.csv").read_text(encoding="utf-8")
    incremental = tmp_path / "incremental-rag"
    incremental_rag = incremental / "sources" / "rag"
    incremental_rag.mkdir(parents=True)
    (incremental_rag / "new-note.md").write_text(
        "# Incremental validation note\n\nA new locally observed field result.\n",
        encoding="utf-8",
    )
    (incremental / "manifest.json").write_text(
        json.dumps(
            {
                "batch_id": "batch-test-2026-08-04-rag-only",
                "schema_version": "1.0",
                "crop_scope": ["foxtail_millet"],
                "sources": {"rag_sources_dir": "sources/rag"},
            }
        ),
        encoding="utf-8",
    )

    incremental_result = import_knowledge_batch(
        incremental,
        active_root=active_root,
        catalog_path=catalog,
    )

    assert incremental_result.activated is True
    assert "germplasm_rows" not in incremental_result.stats
    assert (active_root / "germplasm_resources.csv").read_text(encoding="utf-8") == germplasm_before
    assert load_evidence_index(active_root / "evidence_index.json").chunk_count > result.stats["rag_chunks"]


def test_import_knowledge_batch_rejects_invalid_batch_without_activation(tmp_path: Path) -> None:
    batch = tmp_path / "batch"
    batch.mkdir()
    (batch / "manifest.json").write_text("{}", encoding="utf-8")
    active_root = tmp_path / "active"

    with pytest.raises(ValueError, match="validation failed"):
        import_knowledge_batch(batch, active_root=active_root)

    assert not active_root.exists()


def test_import_knowledge_batch_rejects_existing_batch_id(tmp_path: Path) -> None:
    batch = tmp_path / "batch"
    sources = batch / "sources"
    (sources / "kg").mkdir(parents=True)
    (sources / "rag").mkdir()
    root = Path(__file__).resolve().parents[3]
    for filename in (
        "germplasm_resources_public_seed.csv",
        "marker_qtl_library_seed.csv",
        "phenotype_protocol_library_seed.csv",
        "field_trial_records_seed.csv",
    ):
        shutil.copyfile(root / "docs" / "templates" / filename, sources / filename)
    shutil.copyfile(root / "docs" / "templates" / "foxtail_millet_kg_seed.json", sources / "kg/foxtail_millet.json")
    shutil.copyfile(root / "docs" / "rag_sources" / "foxtail_millet_drought_testing_note.md", sources / "note.md")
    (batch / "manifest.json").write_text(
        json.dumps(
            {
                "batch_id": "immutable-batch",
                "schema_version": "1.0",
                "crop_scope": ["foxtail_millet"],
                "sources": {
                    "germplasm_csv": "sources/germplasm_resources_public_seed.csv",
                    "crop_kg_packs": [
                        {"crop_key": "foxtail_millet", "path": "sources/kg/foxtail_millet.json"}
                    ],
                    "rag_sources_dir": "sources/rag",
                    "rag_index_json": "outputs/evidence_index.json",
                    "marker_qtl_csv": "sources/marker_qtl_library_seed.csv",
                    "phenotype_protocol_csv": "sources/phenotype_protocol_library_seed.csv",
                    "field_trial_csv": "sources/field_trial_records_seed.csv",
                },
            }
        ),
        encoding="utf-8",
    )
    active_root = tmp_path / "active"
    import_knowledge_batch(batch, active_root=active_root)

    with pytest.raises(ValueError, match="batch_id already exists"):
        import_knowledge_batch(batch, active_root=active_root)


def test_import_knowledge_batch_rejects_pending_batch_id(tmp_path: Path) -> None:
    batch = tmp_path / "batch"
    sources = batch / "sources"
    (sources / "kg").mkdir(parents=True)
    (sources / "rag").mkdir()
    root = Path(__file__).resolve().parents[3]
    for filename in (
        "germplasm_resources_public_seed.csv",
        "marker_qtl_library_seed.csv",
        "phenotype_protocol_library_seed.csv",
        "field_trial_records_seed.csv",
    ):
        shutil.copyfile(root / "docs" / "templates" / filename, sources / filename)
    shutil.copyfile(root / "docs" / "templates" / "foxtail_millet_kg_seed.json", sources / "kg/foxtail_millet.json")
    shutil.copyfile(root / "docs" / "rag_sources" / "foxtail_millet_drought_testing_note.md", sources / "note.md")
    (batch / "manifest.json").write_text(
        json.dumps(
            {
                "batch_id": "pending-batch",
                "schema_version": "1.0",
                "crop_scope": ["foxtail_millet"],
                "sources": {
                    "germplasm_csv": "sources/germplasm_resources_public_seed.csv",
                    "crop_kg_packs": [
                        {"crop_key": "foxtail_millet", "path": "sources/kg/foxtail_millet.json"}
                    ],
                    "rag_sources_dir": "sources/rag",
                    "rag_index_json": "outputs/evidence_index.json",
                    "marker_qtl_csv": "sources/marker_qtl_library_seed.csv",
                    "phenotype_protocol_csv": "sources/phenotype_protocol_library_seed.csv",
                    "field_trial_csv": "sources/field_trial_records_seed.csv",
                },
            }
        ),
        encoding="utf-8",
    )
    active_root = tmp_path / "active"
    import_knowledge_batch(batch, active_root=active_root, dry_run=True)
    pending = active_root.parent / "pending" / "pending_batch"
    pending.mkdir(parents=True)
    (pending / "audit.json").write_text("{}", encoding="utf-8")

    with pytest.raises(ValueError, match="batch_id already pending"):
        import_knowledge_batch(batch, active_root=active_root, dry_run=True)


def test_staged_activation_restores_previous_knowledge_on_post_switch_failure(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    active_root = tmp_path / "active"
    active_root.mkdir()
    (active_root / "sentinel.txt").write_text("previous", encoding="utf-8")
    stage = tmp_path / ".active.staging-test"
    stage.mkdir()
    (stage / "catalog.json").write_text("{}", encoding="utf-8")

    def fail_validation(*args, **kwargs):
        raise ValueError("simulated post-switch validation failure")

    monkeypatch.setattr(intake, "_validate_merged_outputs", fail_validation)

    with pytest.raises(ValueError, match="simulated post-switch"):
        intake._activate_staged_knowledge(
            stage,
            active_root,
            active_root / "catalog.json",
            {},
            batch_id="rollback-test",
            stats={"crop_kg_packs": {}},
        )

    assert (active_root / "sentinel.txt").read_text(encoding="utf-8") == "previous"
    assert not stage.exists()
