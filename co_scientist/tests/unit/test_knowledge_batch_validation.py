from __future__ import annotations

import csv
import json
import subprocess
import sys
from pathlib import Path

from co_scientist.knowledge.breeding_libraries import (
    FIELD_TRIAL_COLUMNS,
    MARKER_QTL_COLUMNS,
    PHENOTYPE_PROTOCOL_COLUMNS,
)
from co_scientist.knowledge.germplasm import EXPECTED_COLUMNS as GERMPLASM_COLUMNS


def test_validate_knowledge_batch_accepts_batch_when_only_rag_has_records(tmp_path: Path) -> None:
    batch_dir = tmp_path / "batch-2026-08-04-test"
    sources_dir = batch_dir / "sources"
    (sources_dir / "kg").mkdir(parents=True)
    (sources_dir / "rag").mkdir()
    (batch_dir / "outputs").mkdir()

    _write_header(sources_dir / "germplasm_resources.csv", GERMPLASM_COLUMNS)
    _write_header(sources_dir / "marker_qtl_library.csv", MARKER_QTL_COLUMNS)
    _write_header(sources_dir / "phenotype_protocol_library.csv", PHENOTYPE_PROTOCOL_COLUMNS)
    _write_header(sources_dir / "field_trial_records.csv", FIELD_TRIAL_COLUMNS)
    (sources_dir / "kg" / "sorghum.json").write_text(
        json.dumps({"metadata": {}, "nodes": [], "edges": []}), encoding="utf-8"
    )
    (sources_dir / "rag" / "note.md").write_text("# Test note\n", encoding="utf-8")
    (batch_dir / "manifest.json").write_text(
        json.dumps(
            {
                "batch_id": "batch-2026-08-04-test",
                "schema_version": "1.0",
                "crop_scope": ["sorghum"],
                "sources": {
                    "germplasm_csv": "sources/germplasm_resources.csv",
                    "crop_kg_packs": [
                        {"crop_key": "sorghum", "path": "sources/kg/sorghum.json"}
                    ],
                    "rag_sources_dir": "sources/rag",
                    "rag_index_json": "outputs/evidence_index.json",
                    "marker_qtl_csv": "sources/marker_qtl_library.csv",
                    "phenotype_protocol_csv": "sources/phenotype_protocol_library.csv",
                    "field_trial_csv": "sources/field_trial_records.csv",
                },
            }
        ),
        encoding="utf-8",
    )

    result = subprocess.run(
        [sys.executable, "scripts/validate_knowledge_batch.py", str(batch_dir), "--build-rag-index"],
        capture_output=True,
        check=False,
        text=True,
    )

    assert result.returncode == 0, result.stdout + result.stderr
    assert "OK manifest:" in result.stdout
    assert "OK crop_kg[1]:" in result.stdout
    assert "OK rag:" in result.stdout
    assert "Knowledge batch validation passed" in result.stdout
    assert (batch_dir / "outputs" / "evidence_index.json").exists()


def test_validate_knowledge_batch_accepts_incremental_rag_only_batch(tmp_path: Path) -> None:
    batch_dir = tmp_path / "rag-only"
    rag_dir = batch_dir / "sources" / "rag"
    rag_dir.mkdir(parents=True)
    (rag_dir / "new-observation.md").write_text(
        "# New field observation\n\nDrought screening note for buckwheat.\n",
        encoding="utf-8",
    )
    (batch_dir / "manifest.json").write_text(
        json.dumps(
            {
                "batch_id": "rag-only-2026-08-07",
                "schema_version": "1.0",
                "crop_scope": ["buckwheat"],
                "sources": {"rag_sources_dir": "sources/rag"},
            }
        ),
        encoding="utf-8",
    )

    result = subprocess.run(
        [sys.executable, "scripts/validate_knowledge_batch.py", str(batch_dir)],
        capture_output=True,
        check=False,
        text=True,
    )

    assert result.returncode == 0, result.stdout + result.stderr
    assert "OK germplasm: not provided; treated as an incremental batch" in result.stdout
    assert "OK batch_content: valid sources: rag" in result.stdout


def test_validate_knowledge_batch_rejects_completely_empty_batch(tmp_path: Path) -> None:
    batch_dir = tmp_path / "empty"
    batch_dir.mkdir()
    (batch_dir / "manifest.json").write_text(
        json.dumps(
            {
                "batch_id": "empty-2026-08-07",
                "schema_version": "1.0",
                "crop_scope": ["rice"],
                "sources": {},
            }
        ),
        encoding="utf-8",
    )

    result = subprocess.run(
        [sys.executable, "scripts/validate_knowledge_batch.py", str(batch_dir)],
        capture_output=True,
        check=False,
        text=True,
    )

    assert result.returncode == 1
    assert "ERROR batch_content:" in result.stdout
    assert "at least one valid data record" in result.stdout


def _write_header(path: Path, columns: list[str]) -> None:
    with path.open("w", encoding="utf-8", newline="") as stream:
        csv.writer(stream).writerow(columns)
