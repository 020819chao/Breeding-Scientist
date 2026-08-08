"""Portable knowledge-batch validation and activation.

The importer keeps the live knowledge boundary in ``data/knowledge/active``.
Each batch is validated before it can change that boundary. Structured records
are merged by stable IDs, crop KG packs are merged by node/edge IDs, and RAG
sources are stored under the batch ID so every imported source remains
traceable.
"""

from __future__ import annotations

import csv
import json
import re
import shutil
from collections.abc import Callable
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from ..config import PROJECT_ROOT
from .breeding_libraries import (
    FIELD_TRIAL_COLUMNS,
    MARKER_QTL_COLUMNS,
    PHENOTYPE_PROTOCOL_COLUMNS,
    load_field_trial_records,
    load_marker_qtl_records,
    load_phenotype_protocol_records,
)
from .crop_kg_graph import validate_crop_kg_graph
from .germplasm import EXPECTED_COLUMNS as GERMPLASM_COLUMNS
from .germplasm import validate_germplasm_csv
from .rag import (
    SUPPORTED_EXTENSIONS,
    build_evidence_index,
    deduplicate_source_documents,
    load_evidence_index,
    save_evidence_index,
)

SUPPORTED_SOURCE_KEYS = (
    "germplasm_csv",
    "crop_kg_packs",
    "rag_sources_dir",
    "marker_qtl_csv",
    "phenotype_protocol_csv",
    "field_trial_csv",
)

DEFAULT_ACTIVE_ROOT = PROJECT_ROOT / "data" / "knowledge" / "active"
DEFAULT_ACTIVE_CATALOG = DEFAULT_ACTIVE_ROOT / "catalog.json"


@dataclass(frozen=True)
class IntakeCheck:
    name: str
    ok: bool
    message: str


@dataclass(frozen=True)
class BatchSourcePaths:
    batch_dir: Path
    manifest: dict[str, Any]
    germplasm_csv: Path | None
    crop_kg_packs: dict[str, Path]
    rag_sources_dir: Path | None
    rag_index_json: Path | None
    marker_qtl_csv: Path | None
    phenotype_protocol_csv: Path | None
    field_trial_csv: Path | None


@dataclass(frozen=True)
class IntakeReport:
    batch_dir: Path
    checks: list[IntakeCheck]
    sources: BatchSourcePaths | None

    @property
    def ok(self) -> bool:
        return bool(self.checks) and all(check.ok for check in self.checks)

    def format_errors(self) -> str:
        return "; ".join(
            f"{check.name}: {check.message}" for check in self.checks if not check.ok
        )


@dataclass(frozen=True)
class KnowledgeImportResult:
    batch_id: str
    activated: bool
    active_root: Path
    catalog_path: Path
    stats: dict[str, Any]


def validate_knowledge_batch(batch_dir: Path) -> IntakeReport:
    """Validate a batch and return resolved source paths without writing files."""

    batch_dir = batch_dir.resolve()
    manifest_path = batch_dir / "manifest.json"
    if not manifest_path.is_file():
        return IntakeReport(
            batch_dir=batch_dir,
            checks=[IntakeCheck("manifest", False, f"missing {manifest_path}")],
            sources=None,
        )
    try:
        manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    except Exception as exc:
        return IntakeReport(
            batch_dir=batch_dir,
            checks=[IntakeCheck("manifest", False, f"cannot read {manifest_path}: {exc}")],
            sources=None,
        )
    if not isinstance(manifest, dict):
        return IntakeReport(
            batch_dir=batch_dir,
            checks=[IntakeCheck("manifest", False, "manifest root must be a JSON object")],
            sources=None,
        )

    errors: list[str] = []
    if not str(manifest.get("batch_id") or "").strip():
        errors.append("batch_id is required")
    if not str(manifest.get("schema_version") or "").strip():
        errors.append("schema_version is required")
    crop_scope = manifest.get("crop_scope")
    if not isinstance(crop_scope, list) or not crop_scope or not all(
        isinstance(item, str) and item.strip() for item in crop_scope
    ):
        errors.append("crop_scope must be a non-empty list of crop keys")
    raw_sources = manifest.get("sources")
    if not isinstance(raw_sources, dict):
        errors.append("sources must be an object")
    else:
        unknown = sorted(set(raw_sources) - set(SUPPORTED_SOURCE_KEYS) - {"rag_index_json"})
        if unknown:
            errors.append(f"sources contains unsupported keys: {', '.join(unknown)}")
        if raw_sources.get("crop_kg_packs") is not None and not isinstance(
            raw_sources.get("crop_kg_packs"), list
        ):
            errors.append("sources.crop_kg_packs must be a list")
    if errors:
        return IntakeReport(
            batch_dir=batch_dir,
            checks=[IntakeCheck("manifest", False, "; ".join(errors))],
            sources=None,
        )

    checks = [
        IntakeCheck(
            "manifest",
            True,
            f"batch_id={manifest['batch_id']}, crops={', '.join(manifest['crop_scope'])}",
        )
    ]
    sources = raw_sources
    valid_data_sources: list[str] = []
    germplasm_csv, germplasm_check = _resolve_optional_source(
        batch_dir, sources.get("germplasm_csv"), "germplasm"
    )
    checks.append(germplasm_check)
    if germplasm_csv is not None and germplasm_check.ok:
        germplasm_result = _check_germplasm(germplasm_csv)
        checks.append(germplasm_result)
        if germplasm_result.ok and _csv_has_data_rows(germplasm_csv):
            valid_data_sources.append("germplasm")

    crop_kg_packs: dict[str, Path] = {}
    seen_pack_keys: set[str] = set()
    for index, item in enumerate(sources.get("crop_kg_packs") or [], start=1):
        name = f"crop_kg[{index}]"
        if not isinstance(item, dict):
            checks.append(IntakeCheck(name, False, "each crop KG pack must be an object"))
            continue
        crop_key = _normalize_key(item.get("crop_key"))
        if not crop_key:
            checks.append(IntakeCheck(name, False, "crop_key is required"))
            continue
        if crop_key in seen_pack_keys:
            checks.append(IntakeCheck(name, False, f"duplicate crop_key {crop_key!r}"))
            continue
        seen_pack_keys.add(crop_key)
        path, path_check = _resolve_source(batch_dir, item.get("path"), name)
        checks.append(path_check)
        if path is None or not path_check.ok:
            continue
        kg_check = _check_crop_kg(name, crop_key, path)
        checks.append(kg_check)
        if kg_check.ok and _crop_kg_has_data(path):
            valid_data_sources.append(f"crop_kg:{crop_key}")
        crop_kg_packs[crop_key] = path

    rag_sources_dir, rag_check = _resolve_optional_source(
        batch_dir, sources.get("rag_sources_dir"), "rag"
    )
    checks.append(rag_check)
    if rag_sources_dir is not None and rag_check.ok:
        if not rag_sources_dir.is_dir():
            checks.append(IntakeCheck("rag", False, f"{rag_sources_dir} is not a directory"))
        else:
            index = build_evidence_index(rag_sources_dir)
            checks.append(IntakeCheck("rag", True, f"{index.chunk_count} source chunks"))
            if index.chunk_count > 0:
                valid_data_sources.append("rag")

    resolved_libraries: dict[str, tuple[Path | None, Callable[[Path], list[dict[str, str]]]]] = {}
    for name, key, loader in (
        ("marker_qtl", "marker_qtl_csv", load_marker_qtl_records),
        ("phenotype_protocol", "phenotype_protocol_csv", load_phenotype_protocol_records),
        ("field_trial", "field_trial_csv", load_field_trial_records),
    ):
        path, path_check = _resolve_optional_source(batch_dir, sources.get(key), name)
        checks.append(path_check)
        if path is not None and path_check.ok:
            resolved_libraries[name] = (path, loader)
            try:
                rows = loader(path)
            except Exception as exc:
                checks.append(IntakeCheck(name, False, f"{path}: {exc}"))
            else:
                checks.append(IntakeCheck(name, True, f"{len(rows)} rows"))
                if rows:
                    valid_data_sources.append(name)
        else:
            resolved_libraries[name] = (None, loader)

    rag_index_json = _resolve_optional_output(batch_dir, sources.get("rag_index_json"))
    if not valid_data_sources:
        checks.append(
            IntakeCheck(
                "batch_content",
                False,
                "batch must contain at least one valid data record; omitted source types are allowed",
            )
        )
    else:
        checks.append(
            IntakeCheck(
                "batch_content",
                True,
                f"valid sources: {', '.join(valid_data_sources)}",
            )
        )
    return IntakeReport(
        batch_dir=batch_dir,
        checks=checks,
        sources=BatchSourcePaths(
            batch_dir=batch_dir,
            manifest=manifest,
            germplasm_csv=germplasm_csv,
            crop_kg_packs=crop_kg_packs,
            rag_sources_dir=rag_sources_dir,
            rag_index_json=rag_index_json,
            marker_qtl_csv=resolved_libraries["marker_qtl"][0],
            phenotype_protocol_csv=resolved_libraries["phenotype_protocol"][0],
            field_trial_csv=resolved_libraries["field_trial"][0],
        ),
    )


def import_knowledge_batch(
    batch_dir: Path,
    *,
    active_root: Path = DEFAULT_ACTIVE_ROOT,
    catalog_path: Path | None = None,
    dry_run: bool = False,
    approval: dict[str, str] | None = None,
    allow_existing_pending: bool = False,
) -> KnowledgeImportResult:
    """Validate, merge, index, and activate one knowledge batch."""

    report = validate_knowledge_batch(batch_dir)
    if not report.ok or report.sources is None:
        raise ValueError(f"Knowledge batch validation failed: {report.format_errors()}")

    sources = report.sources
    batch_id = _safe_name(str(sources.manifest["batch_id"]))
    active_root = active_root.resolve()
    catalog_path = (catalog_path or active_root / "catalog.json").resolve()
    if active_root.is_dir() and (active_root / "catalog.json").is_file():
        try:
            active_catalog = json.loads((active_root / "catalog.json").read_text(encoding="utf-8"))
        except (OSError, ValueError) as exc:
            raise ValueError(f"cannot read active knowledge catalog: {exc}") from exc
        history = active_catalog.get("batch_history") if isinstance(active_catalog, dict) else []
        existing_ids = {
            str(row.get("batch_id") or "")
            for row in history or []
            if isinstance(row, dict)
        }
        if batch_id in existing_ids or batch_id == active_catalog.get("active_batch_id"):
            raise ValueError(
                f"batch_id already exists: {batch_id}; use a new immutable batch_id for a revision"
            )
    pending_path = active_root.parent / "pending" / batch_id
    if (
        not allow_existing_pending
        and pending_path.is_dir()
        and (pending_path / "audit.json").is_file()
    ):
        raise ValueError(
            f"batch_id already pending: {batch_id}; approve or reject the existing review item"
        )
    stage = active_root.parent / f".{active_root.name}.staging-{batch_id}"
    if stage.exists():
        shutil.rmtree(stage)
    if active_root.exists():
        shutil.copytree(active_root, stage)
    else:
        stage.mkdir(parents=True)
        _bootstrap_seed_knowledge(stage)

    stats: dict[str, Any] = {"batch_id": batch_id, "replaced": {}, "added": {}}
    try:
        stage.mkdir(parents=True, exist_ok=True)
        (stage / "kg").mkdir(exist_ok=True)
        (stage / "rag").mkdir(exist_ok=True)

        if sources.germplasm_csv is not None:
            stats["germplasm_rows"] = _merge_csv(
                stage / "germplasm_resources.csv",
                sources.germplasm_csv,
                columns=GERMPLASM_COLUMNS,
                id_field="accession_id",
                stats=stats,
            )
        for name, source_path, columns, id_field in (
            ("marker_qtl", sources.marker_qtl_csv, MARKER_QTL_COLUMNS, "marker_id"),
            (
                "phenotype_protocol",
                sources.phenotype_protocol_csv,
                PHENOTYPE_PROTOCOL_COLUMNS,
                "protocol_id",
            ),
            ("field_trial", sources.field_trial_csv, FIELD_TRIAL_COLUMNS, "trial_id"),
        ):
            if source_path is not None:
                stats[f"{name}_rows"] = _merge_csv(
                    stage / f"{name}.csv",
                    source_path,
                    columns=columns,
                    id_field=id_field,
                    stats=stats,
                )

        rag_count = _copy_rag_sources(sources.rag_sources_dir, stage / "rag", batch_id)
        rag_deduplicated = deduplicate_source_documents(stage / "rag")
        rag_index = build_evidence_index(stage / "rag")
        save_evidence_index(rag_index, stage / "evidence_index.json")
        stats["rag_documents_added"] = rag_count - rag_deduplicated
        stats["rag_documents_deduplicated"] = rag_deduplicated
        stats["rag_chunks"] = rag_index.chunk_count

        crop_stats: dict[str, dict[str, int]] = {}
        for crop_key, source_path in sources.crop_kg_packs.items():
            target_path = stage / "kg" / f"{crop_key}.json"
            graph = _merge_crop_kg(target_path, source_path)
            target_path.write_text(json.dumps(graph, ensure_ascii=False, indent=2), encoding="utf-8")
            crop_stats[crop_key] = {
                "nodes": len(graph.get("nodes", [])),
                "edges": len(graph.get("edges", [])),
            }
        stats["crop_kg_packs"] = crop_stats

        catalog = _build_catalog(
            stage, active_root, catalog_path, sources, batch_id, stats, approval=approval
        )
        (stage / "catalog.json").write_text(
            json.dumps(catalog, ensure_ascii=False, indent=2), encoding="utf-8"
        )
        _validate_merged_outputs(stage, crop_stats)

        if not dry_run:
            _activate_staged_knowledge(
                stage,
                active_root,
                catalog_path,
                catalog,
                batch_id=batch_id,
                stats=stats,
            )
            try:
                from .versions import archive_active_knowledge

                archive_active_knowledge(active_root, batch_id)
                stats["version_archive"] = "passed"
            except (OSError, ValueError) as exc:
                # Activation remains valid, but the UI must not advertise a
                # rollback target when immutable archiving failed.
                stats["version_archive"] = f"failed: {exc}"
    finally:
        if stage.exists():
            shutil.rmtree(stage)

    return KnowledgeImportResult(
        batch_id=batch_id,
        activated=not dry_run,
        active_root=active_root,
        catalog_path=catalog_path,
        stats=stats,
    )


def _resolve_source(batch_dir: Path, raw_path: Any, name: str) -> tuple[Path | None, IntakeCheck]:
    if not isinstance(raw_path, str) or not raw_path.strip():
        return None, IntakeCheck(name, False, "source path must be a non-empty relative path")
    path = Path(raw_path)
    if path.is_absolute():
        return None, IntakeCheck(name, False, "source path must be relative to the batch directory")
    resolved = (batch_dir / path).resolve()
    try:
        resolved.relative_to(batch_dir.resolve())
    except ValueError:
        return None, IntakeCheck(name, False, "source path escapes the batch directory")
    if not resolved.exists():
        return None, IntakeCheck(name, False, f"missing {resolved}")
    return resolved, IntakeCheck(name, True, str(resolved))


def _resolve_optional_source(
    batch_dir: Path, raw_path: Any, name: str
) -> tuple[Path | None, IntakeCheck]:
    """Resolve an optional source without turning an omitted category into an error."""

    if raw_path is None or raw_path == "":
        return None, IntakeCheck(name, True, "not provided; treated as an incremental batch")
    return _resolve_source(batch_dir, raw_path, name)


def _csv_has_data_rows(path: Path) -> bool:
    with path.open(encoding="utf-8", newline="") as stream:
        reader = csv.reader(stream)
        next(reader, None)
        return any(any(cell.strip() for cell in row) for row in reader)


def _crop_kg_has_data(path: Path) -> bool:
    payload = json.loads(path.read_text(encoding="utf-8"))
    return bool(payload.get("nodes") or payload.get("edges")) if isinstance(payload, dict) else False


def _resolve_optional_output(batch_dir: Path, raw_path: Any) -> Path | None:
    if not isinstance(raw_path, str) or not raw_path.strip():
        return None
    path = Path(raw_path)
    if path.is_absolute():
        raise ValueError("rag_index_json must be relative to the batch directory")
    resolved = (batch_dir / path).resolve()
    try:
        resolved.relative_to(batch_dir.resolve())
    except ValueError as exc:
        raise ValueError("rag_index_json escapes the batch directory") from exc
    return resolved


def _check_germplasm(path: Path) -> IntakeCheck:
    try:
        result = validate_germplasm_csv(path)
    except Exception as exc:
        return IntakeCheck("germplasm", False, f"{path}: {exc}")
    errors = [issue for issue in result.issues if issue.level == "error"]
    return IntakeCheck("germplasm", not errors, f"{result.row_count} rows, {len(errors)} errors")


def _check_crop_kg(name: str, crop_key: str, path: Path) -> IntakeCheck:
    try:
        result = validate_crop_kg_graph(path)
    except Exception as exc:
        return IntakeCheck(name, False, f"{path}: {exc}")
    errors = [issue for issue in result.issues if issue.level == "error"]
    return IntakeCheck(
        name,
        not errors,
        f"crop_key={crop_key}, {result.node_count} nodes, {result.edge_count} edges",
    )


def _merge_csv(
    target_path: Path,
    source_path: Path,
    *,
    columns: list[str],
    id_field: str,
    stats: dict[str, Any],
) -> int:
    existing: dict[str, dict[str, str]] = {}
    if target_path.exists():
        existing = _read_csv_records(target_path, columns, id_field)
    incoming = _read_csv_records(source_path, columns, id_field)
    added = 0
    replaced = 0
    for record_id, row in incoming.items():
        if record_id in existing:
            replaced += 1
        else:
            added += 1
        existing[record_id] = row
    target_path.parent.mkdir(parents=True, exist_ok=True)
    with target_path.open("w", encoding="utf-8", newline="") as stream:
        writer = csv.DictWriter(stream, fieldnames=columns)
        writer.writeheader()
        writer.writerows(existing.values())
    name = target_path.stem
    stats["added"][name] = added
    stats["replaced"][name] = replaced
    return len(existing)


def _read_csv_records(path: Path, columns: list[str], id_field: str) -> dict[str, dict[str, str]]:
    with path.open(encoding="utf-8", newline="") as stream:
        reader = csv.DictReader(stream)
        if reader.fieldnames != columns:
            raise ValueError(f"{path} header does not match the expected schema")
        records: dict[str, dict[str, str]] = {}
        for line_number, raw in enumerate(reader, start=2):
            row = {key: (value or "").strip() for key, value in raw.items()}
            record_id = row.get(id_field, "")
            if not record_id:
                raise ValueError(f"{path} row {line_number} is missing {id_field}")
            if record_id in records:
                raise ValueError(f"{path} duplicates {id_field} {record_id!r}")
            records[record_id] = row
    return records


def _copy_rag_sources(source_dir: Path | None, target_dir: Path, batch_id: str) -> int:
    if source_dir is None:
        return 0
    count = 0
    for source in sorted(source_dir.rglob("*")):
        if not source.is_file() or source.suffix.lower() not in SUPPORTED_EXTENSIONS:
            continue
        if source.name.lower() == "readme.md" or source.name.startswith("_"):
            continue
        destination = target_dir / batch_id / source.relative_to(source_dir)
        destination.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(source, destination)
        count += 1
    return count


def _merge_crop_kg(target_path: Path, source_path: Path) -> dict[str, Any]:
    incoming = json.loads(source_path.read_text(encoding="utf-8"))
    existing: dict[str, Any] = {}
    if target_path.exists():
        existing = json.loads(target_path.read_text(encoding="utf-8"))
    nodes = _merge_by_id(existing.get("nodes", []), incoming.get("nodes", []), "id")
    edges = _merge_by_id(existing.get("edges", []), incoming.get("edges", []), "id")
    metadata = dict(existing.get("metadata") or {})
    metadata.update(incoming.get("metadata") or {})
    return {"metadata": metadata, "nodes": nodes, "edges": edges}


def _merge_by_id(existing: Any, incoming: Any, id_field: str) -> list[dict[str, Any]]:
    merged: dict[str, dict[str, Any]] = {}
    for item in [*(existing if isinstance(existing, list) else []), *(incoming if isinstance(incoming, list) else [])]:
        if not isinstance(item, dict) or not str(item.get(id_field) or "").strip():
            raise ValueError(f"KG records must be objects with a non-empty {id_field}")
        merged[str(item[id_field])] = item
    return list(merged.values())


def _build_catalog(
    stage: Path,
    active_root: Path,
    catalog_path: Path,
    sources: BatchSourcePaths,
    batch_id: str,
    stats: dict[str, Any],
    *,
    approval: dict[str, str] | None = None,
) -> dict[str, Any]:
    previous: dict[str, Any] = {}
    previous_path = stage / "catalog.json"
    if previous_path.exists():
        try:
            payload = json.loads(previous_path.read_text(encoding="utf-8"))
            if isinstance(payload, dict):
                previous = payload
        except Exception:
            previous = {}
    crop_packs = dict(previous.get("crop_kg_packs") or {})
    default_kg = stage / "kg" / "foxtail_millet.json"
    if default_kg.is_file():
        crop_packs.setdefault("foxtail_millet", _project_relative(active_root / "kg" / default_kg.name))
    for crop_key in sources.crop_kg_packs:
        crop_packs[crop_key] = _project_relative(active_root / "kg" / f"{crop_key}.json")
    history = list(previous.get("batch_history") or [])
    history_entry = {
        "batch_id": batch_id,
        "imported_at": _now(),
        "crop_scope": sources.manifest.get("crop_scope", []),
        "lifecycle_status": "active",
        "approval_status": "not_required" if approval is None else "approved",
        "stats": stats,
    }
    if approval is not None:
        history_entry.update(
            {
                "reviewer": approval.get("reviewer", ""),
                "reviewed_at": approval.get("reviewed_at", _now()),
                "review_note": approval.get("note", ""),
            }
        )
    history.append(history_entry)
    return {
        "catalog_version": 1,
        "active_batch_id": batch_id,
        "updated_at": _now(),
        "germplasm_csv": _project_relative(active_root / "germplasm_resources.csv"),
        "crop_kg_packs": crop_packs,
        "rag_sources_dir": _project_relative(active_root / "rag"),
        "rag_index_json": _project_relative(active_root / "evidence_index.json"),
        "marker_qtl_csv": _project_relative(active_root / "marker_qtl.csv"),
        "phenotype_protocol_csv": _project_relative(active_root / "phenotype_protocol.csv"),
        "field_trial_csv": _project_relative(active_root / "field_trial.csv"),
        "batch_history": history[-50:],
        "last_import_stats": stats,
        "catalog_path": _project_relative(catalog_path),
    }


def _validate_merged_outputs(stage: Path, crop_stats: dict[str, dict[str, int]]) -> None:
    for filename, validator in (
        ("germplasm_resources.csv", validate_germplasm_csv),
        ("marker_qtl.csv", lambda path: _library_check(path, load_marker_qtl_records)),
        (
            "phenotype_protocol.csv",
            lambda path: _library_check(path, load_phenotype_protocol_records),
        ),
        ("field_trial.csv", lambda path: _library_check(path, load_field_trial_records)),
    ):
        path = stage / filename
        if not path.exists():
            raise ValueError(f"merged active library is missing {path}")
        result = validator(path)
        if hasattr(result, "ok") and not result.ok:
            raise ValueError(f"merged active library failed validation: {path}")
    for crop_key in crop_stats:
        path = stage / "kg" / f"{crop_key}.json"
        result = validate_crop_kg_graph(path)
        if not result.ok:
            raise ValueError(f"merged crop KG failed validation: {path}")
    rag_index_path = stage / "evidence_index.json"
    if not rag_index_path.is_file():
        raise ValueError(f"merged RAG index is missing {rag_index_path}")
    rag_index = load_evidence_index(rag_index_path)
    if rag_index.chunk_count <= 0:
        raise ValueError("merged RAG index contains no evidence chunks")


def _activate_staged_knowledge(
    stage: Path,
    active_root: Path,
    catalog_path: Path,
    catalog: dict[str, Any],
    *,
    batch_id: str,
    stats: dict[str, Any],
) -> None:
    """Atomically promote a validated stage, restoring the previous version on error."""

    active_root.parent.mkdir(parents=True, exist_ok=True)
    backup = active_root.parent / f".{active_root.name}.backup-{batch_id}"
    if backup.exists():
        shutil.rmtree(backup)
    external_catalog = catalog_path != (active_root / "catalog.json").resolve()
    old_catalog = catalog_path.read_bytes() if external_catalog and catalog_path.is_file() else None
    old_catalog_exists = external_catalog and catalog_path.exists()
    moved_new = False
    try:
        if active_root.exists():
            shutil.move(str(active_root), str(backup))
        shutil.move(str(stage), str(active_root))
        moved_new = True
        _validate_merged_outputs(active_root, stats.get("crop_kg_packs", {}))
        stats["active_validation"] = "passed"
        (active_root / "last_import_report.json").write_text(
            json.dumps(
                {
                    "batch_id": batch_id,
                    "imported_at": _now(),
                    "stats": stats,
                    "catalog_path": _project_relative(catalog_path),
                },
                ensure_ascii=False,
                indent=2,
            ),
            encoding="utf-8",
        )
        if external_catalog:
            catalog_path.parent.mkdir(parents=True, exist_ok=True)
            catalog_path.write_text(
                json.dumps(catalog, ensure_ascii=False, indent=2), encoding="utf-8"
            )
    except Exception:
        if moved_new and active_root.exists():
            shutil.rmtree(active_root)
        if backup.exists():
            shutil.move(str(backup), str(active_root))
        if external_catalog:
            if old_catalog_exists and old_catalog is not None:
                catalog_path.parent.mkdir(parents=True, exist_ok=True)
                catalog_path.write_bytes(old_catalog)
            elif catalog_path.exists():
                catalog_path.unlink()
        raise
    else:
        if backup.exists():
            shutil.rmtree(backup)


def _bootstrap_seed_knowledge(stage: Path) -> None:
    """Preserve the repository's original local-first seed boundary on first import."""

    stage.mkdir(parents=True, exist_ok=True)
    (stage / "kg").mkdir(exist_ok=True)
    (stage / "rag" / "bootstrap").mkdir(parents=True, exist_ok=True)
    seed_files = {
        "germplasm_resources.csv": PROJECT_ROOT / "docs/templates/germplasm_resources_public_seed.csv",
        "marker_qtl.csv": PROJECT_ROOT / "docs/templates/marker_qtl_library_seed.csv",
        "phenotype_protocol.csv": PROJECT_ROOT / "docs/templates/phenotype_protocol_library_seed.csv",
        "field_trial.csv": PROJECT_ROOT / "docs/templates/field_trial_records_seed.csv",
    }
    for target_name, source_path in seed_files.items():
        if source_path.is_file():
            shutil.copy2(source_path, stage / target_name)
    kg_seed = PROJECT_ROOT / "docs/templates/foxtail_millet_kg_seed.json"
    if kg_seed.is_file():
        shutil.copy2(kg_seed, stage / "kg/foxtail_millet.json")
    rag_seed_dir = PROJECT_ROOT / "docs/rag_sources"
    if rag_seed_dir.is_dir():
        for source in rag_seed_dir.rglob("*"):
            if not source.is_file() or source.suffix.lower() not in SUPPORTED_EXTENSIONS:
                continue
            if source.name.lower() == "readme.md" or source.name.startswith("_"):
                continue
            destination = stage / "rag" / "bootstrap" / source.relative_to(rag_seed_dir)
            destination.parent.mkdir(parents=True, exist_ok=True)
            shutil.copy2(source, destination)


def _library_check(path: Path, loader: Callable[[Path], list[dict[str, str]]]) -> IntakeCheck:
    try:
        rows = loader(path)
    except Exception as exc:
        return IntakeCheck(path.name, False, str(exc))
    return IntakeCheck(path.name, True, f"{len(rows)} rows")


def _project_relative(path: Path) -> str:
    try:
        return path.resolve().relative_to(PROJECT_ROOT.resolve()).as_posix()
    except ValueError:
        return str(path.resolve())


def _normalize_key(value: Any) -> str:
    raw = str(value or "").strip().lower().replace("-", "_").replace(" ", "_")
    return re.sub(r"[^a-z0-9_]+", "", raw)


def _safe_name(value: str) -> str:
    return _normalize_key(value) or "batch"


def _now() -> str:
    return datetime.now(UTC).isoformat()
