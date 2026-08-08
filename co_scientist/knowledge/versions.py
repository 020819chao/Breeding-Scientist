"""Immutable active-knowledge versions and safe rollback helpers."""

from __future__ import annotations

import hashlib
import json
import shutil
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from .intake import _activate_staged_knowledge, _validate_merged_outputs


def versions_root(active_root: Path) -> Path:
    return active_root.resolve().parent / "versions"


def pending_root(active_root: Path) -> Path:
    return active_root.resolve().parent / "pending"


def version_path(active_root: Path, batch_id: str) -> Path:
    safe = "".join(char if char.isalnum() or char in "._-" else "_" for char in batch_id)
    return versions_root(active_root) / (safe or "batch")


def pending_path(active_root: Path, batch_id: str) -> Path:
    safe = "".join(char if char.isalnum() or char in "._-" else "_" for char in batch_id)
    return pending_root(active_root) / (safe or "batch")


def save_pending_batch(
    active_root: Path,
    batch_dir: Path,
    *,
    batch_id: str,
    crop_scope: list[str],
    stats: dict[str, Any],
    source_filename: str,
) -> Path:
    """Persist a successful preflight package until an explicit approval."""

    active_root = active_root.resolve()
    destination = pending_path(active_root, batch_id).resolve()
    if destination.exists():
        raise ValueError(f"a pending batch already exists: {batch_id}")
    pending_root(active_root).mkdir(parents=True, exist_ok=True)
    stage = pending_root(active_root) / f".{destination.name}.staging"
    if stage.exists():
        shutil.rmtree(stage)
    shutil.copytree(batch_dir.resolve(), stage)
    try:
        (stage / "audit.json").write_text(
            json.dumps(
                {
                    "batch_id": batch_id,
                    "crop_scope": crop_scope,
                    "created_at": datetime.now(UTC).isoformat(),
                    "source_filename": source_filename,
                    "lifecycle_status": "preflight_passed",
                    "approval_status": "pending_review",
                    "stats": stats,
                },
                ensure_ascii=False,
                indent=2,
            ),
            encoding="utf-8",
        )
        shutil.move(str(stage), str(destination))
    except Exception:
        if stage.exists():
            shutil.rmtree(stage)
        if destination.exists():
            shutil.rmtree(destination)
        raise
    return destination


def list_pending_batches(active_root: Path) -> dict[str, Path]:
    root = pending_root(active_root)
    if not root.is_dir():
        return {}
    result: dict[str, Path] = {}
    for path in sorted(root.iterdir()):
        if not path.is_dir() or not (path / "audit.json").is_file():
            continue
        try:
            audit = json.loads((path / "audit.json").read_text(encoding="utf-8"))
        except (OSError, ValueError):
            continue
        batch_id = str(audit.get("batch_id") or path.name)
        result[batch_id] = path
    return result


def find_pending_batch(cfg: Any, batch_id: str) -> Path | None:
    return list_pending_batches(Path(cfg.active_knowledge_catalog_path).parent).get(batch_id)


def complete_pending_batch(active_root: Path, batch_id: str) -> None:
    path = pending_path(active_root, batch_id)
    if path.exists():
        shutil.rmtree(path)


def record_batch_approval(
    active_root: Path,
    catalog_path: Path,
    batch_id: str,
    *,
    reviewer: str,
    note: str,
) -> None:
    """Attach an approval audit record to both active catalog copies."""

    catalog_paths = {catalog_path.resolve(), (active_root / "catalog.json").resolve()}
    reviewed_at = datetime.now(UTC).isoformat()
    for path in catalog_paths:
        if not path.is_file():
            continue
        payload = json.loads(path.read_text(encoding="utf-8"))
        if not isinstance(payload, dict):
            raise ValueError(f"catalog must be an object: {path}")
        history = list(payload.get("batch_history") or [])
        matching = [row for row in history if isinstance(row, dict) and row.get("batch_id") == batch_id]
        if not matching:
            raise ValueError(f"batch is missing from catalog history: {batch_id}")
        row = matching[-1]
        row["lifecycle_status"] = "active"
        row["approval_status"] = "approved"
        row["reviewer"] = reviewer
        row["reviewed_at"] = reviewed_at
        row["review_note"] = note
        payload["batch_history"] = history
        payload["updated_at"] = reviewed_at
        temporary = path.with_name(f".{path.name}.approval")
        temporary.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
        temporary.replace(path)


def archive_active_knowledge(active_root: Path, batch_id: str) -> Path:
    """Archive a validated active tree once, rewriting catalog paths locally."""

    active_root = active_root.resolve()
    destination = version_path(active_root, batch_id).resolve()
    if destination.exists():
        return destination
    if not active_root.is_dir() or not (active_root / "catalog.json").is_file():
        raise ValueError(f"cannot archive incomplete active knowledge: {active_root}")

    versions_root(active_root).mkdir(parents=True, exist_ok=True)
    stage = versions_root(active_root) / f".{destination.name}.staging"
    if stage.exists():
        shutil.rmtree(stage)
    shutil.copytree(active_root, stage)
    try:
        catalog_path = stage / "catalog.json"
        catalog = json.loads(catalog_path.read_text(encoding="utf-8"))
        if not isinstance(catalog, dict):
            raise ValueError("active catalog must be an object")
        # Rewrite paths against the final archive location. The staging path
        # is temporary and must never leak into a version catalog.
        shutil.move(str(stage), str(destination))
        _rewrite_catalog_paths(catalog, destination)
        catalog["version_archive"] = {
            "batch_id": batch_id,
            "archived_at": datetime.now(UTC).isoformat(),
            "path": str(destination),
        }
        (destination / "catalog.json").write_text(
            json.dumps(catalog, ensure_ascii=False, indent=2),
            encoding="utf-8",
        )
    except Exception:
        if stage.exists():
            shutil.rmtree(stage)
        if destination.exists():
            shutil.rmtree(destination)
        raise
    return destination


def list_archived_versions(active_root: Path) -> dict[str, Path]:
    root = versions_root(active_root)
    if not root.is_dir():
        return {}
    result: dict[str, Path] = {}
    for path in sorted(root.iterdir()):
        if not path.is_dir() or not (path / "catalog.json").is_file():
            continue
        try:
            payload = json.loads((path / "catalog.json").read_text(encoding="utf-8"))
        except (OSError, ValueError):
            continue
        batch_id = str(payload.get("active_batch_id") or path.name)
        result[batch_id] = path
    return result


def load_batch_history(cfg: Any) -> list[dict[str, Any]]:
    """Combine catalog history with archive availability for the web UI."""

    catalog = cfg.active_knowledge_catalog
    active_root = Path(cfg.active_knowledge_catalog_path).parent
    archived = list_archived_versions(active_root)
    history = catalog.get("batch_history") or []
    latest_index_by_batch = {
        str(raw.get("batch_id") or ""): index
        for index, raw in enumerate(history)
        if isinstance(raw, dict)
    }
    rows: list[dict[str, Any]] = []
    for index, raw in enumerate(history):
        if not isinstance(raw, dict):
            continue
        row = dict(raw)
        batch_id = str(row.get("batch_id") or "")
        row["history_index"] = index
        row["is_active"] = (
            batch_id == catalog.get("active_batch_id")
            and index == latest_index_by_batch.get(batch_id)
        )
        row["archive_path"] = str(archived[batch_id]) if batch_id in archived else None
        row["rollback_available"] = bool(row["archive_path"])
        row.setdefault("lifecycle_status", "active")
        row.setdefault("approval_status", "not_required")
        row["is_pending"] = False
        rows.append(row)
    known_ids = {str(row.get("batch_id") or "") for row in rows}
    for batch_id, path in list_pending_batches(active_root).items():
        if batch_id in known_ids:
            continue
        try:
            audit = json.loads((path / "audit.json").read_text(encoding="utf-8"))
        except (OSError, ValueError):
            continue
        rows.append(
            {
                "batch_id": batch_id,
                "crop_scope": audit.get("crop_scope") or [],
                "imported_at": audit.get("created_at"),
                "stats": audit.get("stats") or {},
                "lifecycle_status": audit.get("lifecycle_status", "preflight_passed"),
                "approval_status": audit.get("approval_status", "pending_review"),
                "is_active": False,
                "is_pending": True,
                "pending_path": str(path),
                "archive_path": None,
                "rollback_available": False,
            }
        )
    rows.sort(key=lambda item: str(item.get("imported_at") or ""), reverse=True)
    return rows


def find_archived_version(cfg: Any, batch_id: str) -> Path | None:
    return list_archived_versions(Path(cfg.active_knowledge_catalog_path).parent).get(batch_id)


def compare_version_files(current_dir: Path, previous_dir: Path) -> dict[str, Any]:
    """Compare source files in two immutable knowledge archives by SHA256."""

    current = _file_hashes(current_dir)
    previous = _file_hashes(previous_dir)
    current_names = set(current)
    previous_names = set(previous)
    added = sorted(current_names - previous_names)
    removed = sorted(previous_names - current_names)
    changed = sorted(
        name for name in current_names & previous_names if current[name] != previous[name]
    )
    unchanged = sorted(
        name for name in current_names & previous_names if current[name] == previous[name]
    )
    return {
        "added": added,
        "removed": removed,
        "changed": changed,
        "unchanged_count": len(unchanged),
        "current_count": len(current_names),
        "previous_count": len(previous_names),
    }


def _file_hashes(root: Path) -> dict[str, str]:
    ignored = {"catalog.json", "last_import_report.json", "audit.json"}
    result: dict[str, str] = {}
    if not root.is_dir():
        return result
    for path in root.rglob("*"):
        if not path.is_file() or path.name in ignored:
            continue
        digest = hashlib.sha256()
        with path.open("rb") as stream:
            for chunk in iter(lambda: stream.read(1024 * 1024), b""):
                digest.update(chunk)
        result[path.relative_to(root).as_posix()] = digest.hexdigest()
    return result


def rollback_knowledge_version(
    active_root: Path,
    catalog_path: Path,
    version_dir: Path,
) -> dict[str, Any]:
    """Promote one complete archive atomically and preserve rollback history."""

    active_root = active_root.resolve()
    catalog_path = catalog_path.resolve()
    version_dir = version_dir.resolve()
    if not version_dir.is_dir() or not (version_dir / "catalog.json").is_file():
        raise ValueError("selected knowledge version is not a complete archive")
    target_catalog = json.loads((version_dir / "catalog.json").read_text(encoding="utf-8"))
    if not isinstance(target_catalog, dict) or not target_catalog.get("active_batch_id"):
        raise ValueError("selected knowledge version has no active batch ID")

    current_catalog = {}
    if (active_root / "catalog.json").is_file():
        current_catalog = json.loads((active_root / "catalog.json").read_text(encoding="utf-8"))
    stage = active_root.parent / f".{active_root.name}.rollback-{version_dir.name}"
    if stage.exists():
        shutil.rmtree(stage)
    shutil.copytree(version_dir, stage)
    try:
        staged_catalog = json.loads((stage / "catalog.json").read_text(encoding="utf-8"))
        _rewrite_catalog_paths(staged_catalog, stage)
        history = list(current_catalog.get("batch_history") or [])
        history.append(
            {
                "batch_id": staged_catalog.get("active_batch_id"),
                "imported_at": datetime.now(UTC).isoformat(),
                "action": "rollback",
                "source_version": str(version_dir),
            }
        )
        staged_catalog["batch_history"] = history[-50:]
        staged_catalog["updated_at"] = datetime.now(UTC).isoformat()
        (stage / "catalog.json").write_text(
            json.dumps(staged_catalog, ensure_ascii=False, indent=2),
            encoding="utf-8",
        )
        stats = dict(staged_catalog.get("last_import_stats") or {})
        stats["rollback_source"] = str(version_dir)
        _validate_merged_outputs(stage, stats.get("crop_kg_packs", {}))
        _activate_staged_knowledge(
            stage,
            active_root,
            catalog_path,
            staged_catalog,
            batch_id=f"rollback_{version_dir.name}",
            stats=stats,
        )
    except Exception:
        if stage.exists():
            shutil.rmtree(stage)
        raise
    return {
        "batch_id": str(target_catalog["active_batch_id"]),
        "source_version": str(version_dir),
        "rolled_back_at": datetime.now(UTC).isoformat(),
    }


def _rewrite_catalog_paths(catalog: dict[str, Any], root: Path) -> None:
    mapping = {
        "germplasm_csv": root / "germplasm_resources.csv",
        "rag_sources_dir": root / "rag",
        "rag_index_json": root / "evidence_index.json",
        "marker_qtl_csv": root / "marker_qtl.csv",
        "phenotype_protocol_csv": root / "phenotype_protocol.csv",
        "field_trial_csv": root / "field_trial.csv",
        "catalog_path": root / "catalog.json",
    }
    for key, path in mapping.items():
        if path.exists() or key in catalog:
            catalog[key] = str(path)
    raw_packs = catalog.get("crop_kg_packs") or {}
    if isinstance(raw_packs, dict):
        catalog["crop_kg_packs"] = {
            str(key): str(root / "kg" / f"{key}.json")
            for key in raw_packs
            if (root / "kg" / f"{key}.json").is_file()
        }
    if (root / "kg" / "foxtail_millet.json").is_file():
        catalog["crop_kg_json"] = str(root / "kg" / "foxtail_millet.json")


__all__ = [
    "archive_active_knowledge",
    "compare_version_files",
    "complete_pending_batch",
    "find_archived_version",
    "find_pending_batch",
    "list_archived_versions",
    "list_pending_batches",
    "load_batch_history",
    "pending_path",
    "pending_root",
    "record_batch_approval",
    "rollback_knowledge_version",
    "save_pending_batch",
    "version_path",
    "versions_root",
]
