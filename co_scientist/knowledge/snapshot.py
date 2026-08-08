"""Knowledge-base snapshots for reproducible breeding sessions."""

from __future__ import annotations

import hashlib
import json
import shutil
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from ..config import PROJECT_ROOT, Config

SNAPSHOT_VERSION = 1
_RAG_SUFFIXES = {".md", ".markdown", ".txt", ".rst"}
_STATIC_TARGETS = {
    "catalog": "catalog.json",
    "germplasm": "germplasm_resources.csv",
    "rag_index": "evidence_index.json",
    "marker_qtl": "marker_qtl.csv",
    "phenotype_protocol": "phenotype_protocol.csv",
    "field_trial": "field_trial.csv",
}


def capture_knowledge_snapshot(cfg: Config) -> dict[str, Any]:
    """Capture the active knowledge boundary and return a stable snapshot."""

    paths: dict[str, Path] = {
        "catalog": cfg.active_knowledge_catalog_path,
        "germplasm": cfg.germplasm_csv_path,
        "rag_index": cfg.rag_index_path,
        "marker_qtl": cfg.marker_qtl_csv_path,
        "phenotype_protocol": cfg.phenotype_protocol_csv_path,
        "field_trial": cfg.field_trial_csv_path,
    }
    for crop_key, raw_path in sorted(cfg.active_crop_kg_packs.items()):
        path = Path(raw_path)
        paths[f"crop_kg:{crop_key}"] = path if path.is_absolute() else PROJECT_ROOT / path
    if not any(key.startswith("crop_kg:") for key in paths):
        paths["crop_kg:default"] = cfg.crop_kg_path
    if cfg.rag_sources_dir.is_dir():
        for path in sorted(cfg.rag_sources_dir.rglob("*")):
            if path.is_file() and path.suffix.lower() in _RAG_SUFFIXES:
                relative = path.relative_to(cfg.rag_sources_dir).as_posix()
                paths[f"rag_source:{relative}"] = path

    files = [_file_record(key, path) for key, path in sorted(paths.items())]
    catalog = cfg.active_knowledge_catalog
    identity = {
        "version": SNAPSHOT_VERSION,
        "active_batch_id": catalog.get("active_batch_id"),
        "files": files,
    }
    snapshot_id = hashlib.sha256(_canonical_json(identity).encode("utf-8")).hexdigest()[:20]
    return {
        **identity,
        "snapshot_id": f"kb_{snapshot_id}",
        "captured_at": datetime.now(UTC).isoformat(),
    }


def materialize_knowledge_snapshot(
    cfg: Config,
    snapshot: dict[str, Any],
) -> dict[str, Any]:
    """Copy the captured knowledge boundary into an immutable runtime version.

    ``files`` remains the source boundary used for drift detection. The
    ``runtime_*`` fields point agents at copies, so a later active-batch import
    cannot change a Session that is resumed from this snapshot.
    """

    snapshot_id = str(snapshot.get("snapshot_id") or "").strip()
    files = snapshot.get("files")
    if not snapshot_id or not isinstance(files, list) or not files:
        raise ValueError("cannot materialize an incomplete knowledge snapshot")

    store = cfg.data_dir / "knowledge" / "snapshots"
    root = (store / snapshot_id).resolve()
    if root.exists() and _materialized_snapshot_matches(root, files):
        runtime_files = _runtime_file_records(root, files)
        return _snapshot_with_runtime_paths(snapshot, root, runtime_files)

    if root.exists():
        shutil.rmtree(root)
    stage = store / f".{snapshot_id}.staging"
    if stage.exists():
        shutil.rmtree(stage)
    stage.mkdir(parents=True, exist_ok=True)
    moved = False
    try:
        for record in files:
            if not isinstance(record, dict) or not record.get("exists"):
                continue
            source = Path(str(record.get("path") or ""))
            if not source.is_file():
                raise FileNotFoundError(f"snapshot source is missing: {record.get('key')}")
            target = _runtime_target(stage, str(record.get("key") or ""))
            target.parent.mkdir(parents=True, exist_ok=True)
            shutil.copy2(source, target)
        store.mkdir(parents=True, exist_ok=True)
        shutil.move(str(stage), str(root))
        moved = True
        runtime_files = _runtime_file_records(root, files)
        runtime_catalog = _build_runtime_catalog(cfg, root, runtime_files)
        (root / "catalog.json").write_text(
            json.dumps(runtime_catalog, ensure_ascii=False, indent=2),
            encoding="utf-8",
        )
    except Exception:
        if stage.exists():
            shutil.rmtree(stage)
        if moved and root.exists():
            shutil.rmtree(root)
        raise

    return _snapshot_with_runtime_paths(
        snapshot,
        root,
        _runtime_file_records(root, files),
    )


def config_for_knowledge_snapshot(cfg: Config, snapshot: dict[str, Any]) -> Config:
    """Return a Config whose knowledge paths are bound to a Session snapshot."""

    runtime_catalog = Path(str(snapshot.get("runtime_catalog_path") or ""))
    if not runtime_catalog.is_file():
        # Sessions created before immutable materialization remain compatible.
        return cfg
    bound = cfg.model_copy(deep=True)
    bound.knowledge.active_catalog = str(runtime_catalog)
    bound.knowledge.crop_kg_packs = {}
    runtime_files = snapshot.get("runtime_files") or []
    default_kg = next(
        (
            str(record.get("path"))
            for record in runtime_files
            if isinstance(record, dict) and record.get("key") == "crop_kg:foxtail_millet"
        ),
        None,
    )
    if default_kg:
        bound.knowledge.crop_kg_json = default_kg
    return bound


def verify_knowledge_snapshot(cfg: Config, snapshot: dict[str, Any]) -> tuple[bool, str]:
    """Verify that the active knowledge boundary still matches a snapshot."""

    if not isinstance(snapshot, dict) or not snapshot.get("snapshot_id"):
        return False, "knowledge snapshot is missing"
    files = snapshot.get("files")
    if not isinstance(files, list) or not files:
        return False, "knowledge snapshot has no file records"
    mismatches: list[str] = []
    for record in files:
        if not isinstance(record, dict):
            mismatches.append("invalid file record")
            continue
        path = Path(str(record.get("path") or ""))
        expected_exists = bool(record.get("exists"))
        if not path.is_file():
            if expected_exists:
                mismatches.append(f"missing:{record.get('key')}")
            continue
        actual = _file_record(str(record.get("key") or "unknown"), path)
        if actual.get("sha256") != record.get("sha256"):
            mismatches.append(f"changed:{record.get('key')}")
    current_batch = cfg.active_knowledge_catalog.get("active_batch_id")
    if current_batch != snapshot.get("active_batch_id"):
        mismatches.append("active_batch_id changed")
    if mismatches:
        return False, "; ".join(mismatches[:6])
    return True, f"snapshot {snapshot['snapshot_id']} is unchanged"


def _file_record(key: str, path: Path) -> dict[str, Any]:
    resolved = path.resolve()
    exists = resolved.is_file()
    return {
        "key": key,
        "path": str(resolved),
        "exists": exists,
        "size": resolved.stat().st_size if exists else 0,
        "sha256": _sha256(resolved) if exists else None,
    }


def _runtime_target(root: Path, key: str) -> Path:
    if key in _STATIC_TARGETS:
        return root / _STATIC_TARGETS[key]
    if key.startswith("crop_kg:"):
        crop_key = key.split(":", 1)[1]
        return root / "kg" / f"{crop_key}.json"
    if key.startswith("rag_source:"):
        relative = Path(key.split(":", 1)[1])
        if relative.is_absolute() or ".." in relative.parts:
            raise ValueError(f"invalid RAG snapshot path: {key}")
        return root / "rag" / relative
    raise ValueError(f"unsupported knowledge snapshot file key: {key}")


def _materialized_snapshot_matches(root: Path, files: list[Any]) -> bool:
    if not (root / "catalog.json").is_file():
        return False
    try:
        for record in files:
            if not isinstance(record, dict) or not record.get("exists"):
                continue
            if record.get("key") == "catalog":
                # The runtime catalog intentionally points at immutable copy
                # paths, so its bytes differ from the active source catalog.
                continue
            target = _runtime_target(root, str(record.get("key") or ""))
            if not target.is_file() or _sha256(target) != record.get("sha256"):
                return False
    except (OSError, ValueError):
        return False
    return True


def _runtime_file_records(root: Path, files: list[Any]) -> list[dict[str, Any]]:
    records: list[dict[str, Any]] = []
    for record in files:
        if not isinstance(record, dict) or not record.get("exists"):
            continue
        target = _runtime_target(root, str(record.get("key") or ""))
        records.append(_file_record(str(record.get("key") or ""), target))
    return records


def _snapshot_with_runtime_paths(
    snapshot: dict[str, Any],
    root: Path,
    runtime_files: list[dict[str, Any]],
) -> dict[str, Any]:
    return {
        **snapshot,
        "runtime_root": str(root),
        "runtime_catalog_path": str(root / "catalog.json"),
        "runtime_files": runtime_files,
    }


def _build_runtime_catalog(
    cfg: Config,
    root: Path,
    runtime_files: list[dict[str, Any]],
) -> dict[str, Any]:
    catalog = dict(cfg.active_knowledge_catalog)
    by_key = {str(record.get("key")): Path(str(record.get("path"))) for record in runtime_files}
    for key, field in (
        ("germplasm", "germplasm_csv"),
        ("rag_index", "rag_index_json"),
        ("marker_qtl", "marker_qtl_csv"),
        ("phenotype_protocol", "phenotype_protocol_csv"),
        ("field_trial", "field_trial_csv"),
    ):
        if key in by_key:
            catalog[field] = str(by_key[key])
    catalog["rag_sources_dir"] = str(root / "rag")
    crop_packs = {
        key.split(":", 1)[1]: str(path)
        for key, path in by_key.items()
        if key.startswith("crop_kg:")
    }
    if crop_packs:
        catalog["crop_kg_packs"] = crop_packs
        catalog["crop_kg_json"] = next(iter(crop_packs.values()))
    catalog["catalog_path"] = str(root / "catalog.json")
    return catalog


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for block in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def _canonical_json(payload: Any) -> str:
    return json.dumps(payload, ensure_ascii=False, sort_keys=True, separators=(",", ":"))


__all__ = [
    "capture_knowledge_snapshot",
    "config_for_knowledge_snapshot",
    "materialize_knowledge_snapshot",
    "verify_knowledge_snapshot",
]
