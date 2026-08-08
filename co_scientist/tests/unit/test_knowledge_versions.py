from __future__ import annotations

import json
import shutil
from pathlib import Path

from co_scientist.config import Config, KnowledgeCfg
from co_scientist.knowledge.intake import import_knowledge_batch
from co_scientist.knowledge.versions import (
    compare_version_files,
    find_archived_version,
    load_batch_history,
    rollback_knowledge_version,
)


def test_compare_version_files_reports_added_changed_and_removed(tmp_path: Path) -> None:
    previous = tmp_path / "previous"
    current = tmp_path / "current"
    previous.mkdir()
    current.mkdir()
    (previous / "same.txt").write_text("same", encoding="utf-8")
    (previous / "changed.txt").write_text("old", encoding="utf-8")
    (previous / "removed.txt").write_text("gone", encoding="utf-8")
    (current / "same.txt").write_text("same", encoding="utf-8")
    (current / "changed.txt").write_text("new", encoding="utf-8")
    (current / "added.txt").write_text("new", encoding="utf-8")

    diff = compare_version_files(current, previous)

    assert diff["added"] == ["added.txt"]
    assert diff["changed"] == ["changed.txt"]
    assert diff["removed"] == ["removed.txt"]
    assert diff["unchanged_count"] == 1


def _make_batch(tmp_path: Path, batch_id: str) -> Path:
    project_root = Path(__file__).resolve().parents[3]
    batch = tmp_path / batch_id
    sources = batch / "sources"
    (sources / "kg").mkdir(parents=True)
    (sources / "rag").mkdir()
    for target, source in {
        "germplasm.csv": "germplasm_resources_public_seed.csv",
        "marker.csv": "marker_qtl_library_seed.csv",
        "protocol.csv": "phenotype_protocol_library_seed.csv",
        "trial.csv": "field_trial_records_seed.csv",
    }.items():
        shutil.copyfile(project_root / "docs" / "templates" / source, sources / target)
    shutil.copyfile(
        project_root / "docs" / "templates" / "foxtail_millet_kg_seed.json",
        sources / "kg" / "foxtail_millet.json",
    )
    shutil.copyfile(
        project_root / "docs" / "rag_sources" / "foxtail_millet_drought_testing_note.md",
        sources / "note.md",
    )
    (batch / "manifest.json").write_text(
        json.dumps(
            {
                "batch_id": batch_id,
                "schema_version": "1.0",
                "crop_scope": ["foxtail_millet"],
                "sources": {
                    "germplasm_csv": "sources/germplasm.csv",
                    "crop_kg_packs": [
                        {"crop_key": "foxtail_millet", "path": "sources/kg/foxtail_millet.json"}
                    ],
                    "rag_sources_dir": "sources",
                    "rag_index_json": "outputs/evidence_index.json",
                    "marker_qtl_csv": "sources/marker.csv",
                    "phenotype_protocol_csv": "sources/protocol.csv",
                    "field_trial_csv": "sources/trial.csv",
                },
            }
        ),
        encoding="utf-8",
    )
    return batch


def test_batch_history_and_rollback_use_immutable_archives(tmp_path: Path) -> None:
    active_root = tmp_path / "active"
    catalog_path = active_root / "catalog.json"
    first = import_knowledge_batch(
        _make_batch(tmp_path, "version-one"), active_root=active_root, catalog_path=catalog_path
    )
    second = import_knowledge_batch(
        _make_batch(tmp_path, "version-two"), active_root=active_root, catalog_path=catalog_path
    )

    cfg = Config(knowledge=KnowledgeCfg(active_catalog=str(catalog_path)))
    history = load_batch_history(cfg)
    assert [row["batch_id"] for row in history][:2] == [second.batch_id, first.batch_id]
    archived_first = find_archived_version(cfg, first.batch_id)
    assert archived_first is not None
    archived_catalog = json.loads((archived_first / "catalog.json").read_text(encoding="utf-8"))
    assert str(active_root) not in archived_catalog["germplasm_csv"]
    assert Path(archived_catalog["germplasm_csv"]).is_file()

    result = rollback_knowledge_version(active_root, catalog_path, archived_first)
    assert result["batch_id"] == first.batch_id
    active_catalog = json.loads(catalog_path.read_text(encoding="utf-8"))
    assert active_catalog["active_batch_id"] == first.batch_id
    assert active_catalog["batch_history"][-1]["action"] == "rollback"
