"""Validate the local knowledge-base intake surface.

This checks the core knowledge inputs used by Evidence Curator:

- germplasm resources
- crop-pack KGs
- local RAG sources / optional RAG index
- marker/QTL, phenotype protocol, and field-trial structured libraries
"""

from __future__ import annotations

import argparse
import csv
import sys
from collections.abc import Callable
from dataclasses import dataclass
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from co_scientist.config import load_config  # noqa: E402
from co_scientist.knowledge.breeding_libraries import (  # noqa: E402
    FIELD_TRIAL_COLUMNS,
    MARKER_QTL_COLUMNS,
    PHENOTYPE_PROTOCOL_COLUMNS,
    load_field_trial_records,
    load_marker_qtl_records,
    load_phenotype_protocol_records,
)
from co_scientist.knowledge.crop_kg import list_crop_kg_packs, validate_crop_kg  # noqa: E402
from co_scientist.knowledge.germplasm import validate_germplasm_csv  # noqa: E402
from co_scientist.knowledge.rag import (  # noqa: E402
    build_evidence_index,
    load_evidence_index,
    save_evidence_index,
)


@dataclass
class Check:
    name: str
    ok: bool
    message: str


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--build-rag-index",
        action="store_true",
        help="Write the RAG index JSON after validating RAG sources.",
    )
    parser.add_argument(
        "--require-rag-index",
        action="store_true",
        help="Fail if the configured RAG index JSON does not already exist.",
    )
    args = parser.parse_args(argv)

    cfg = load_config()
    checks: list[Check] = []

    checks.append(_check_germplasm(cfg.germplasm_csv_path))
    checks.extend(_check_crop_kg_packs(cfg))
    checks.append(
        _check_rag(
            cfg.rag_sources_dir,
            cfg.rag_index_path,
            build_index=args.build_rag_index,
            require_index=args.require_rag_index,
        )
    )
    checks.extend(_check_breeding_libraries(cfg))
    checks.extend(_check_blank_templates())

    for check in checks:
        status = "OK" if check.ok else "ERROR"
        print(f"{status} {check.name}: {check.message}")

    ok = all(check.ok for check in checks)
    if ok:
        print("Knowledge base validation passed.")
        return 0
    print("Knowledge base validation failed.")
    return 1


def _check_germplasm(path: Path) -> Check:
    if not path.exists():
        return Check("germplasm", False, f"missing {path}")
    try:
        result = validate_germplasm_csv(path)
    except Exception as exc:
        return Check("germplasm", False, f"{path}: {exc}")
    errors = [issue for issue in result.issues if issue.level == "error"]
    warnings = [issue for issue in result.issues if issue.level != "error"]
    if errors:
        return Check(
            "germplasm",
            False,
            f"{result.row_count} rows, {len(errors)} errors, {len(warnings)} warnings in {path}",
        )
    return Check(
        "germplasm",
        True,
        f"{result.row_count} rows, {len(warnings)} warnings in {path}",
    )


def _check_crop_kg_packs(cfg) -> list[Check]:
    checks: list[Check] = []
    for pack in list_crop_kg_packs(cfg):
        name = f"crop_kg:{pack.key}"
        if not pack.path.exists():
            checks.append(Check(name, False, f"missing {pack.path}"))
            continue
        try:
            result = validate_crop_kg(pack.path)
        except Exception as exc:
            checks.append(Check(name, False, f"{pack.path}: {exc}"))
            continue
        errors = [issue for issue in result.issues if issue.level == "error"]
        warnings = [issue for issue in result.issues if issue.level != "error"]
        checks.append(
            Check(
                name,
                not errors,
                (
                    f"{result.node_count} nodes, {result.edge_count} edges, "
                    f"{len(errors)} errors, {len(warnings)} warnings in {pack.path}"
                ),
            )
        )
    return checks


def _check_rag(
    source_dir: Path,
    index_path: Path,
    *,
    build_index: bool,
    require_index: bool,
) -> Check:
    if not source_dir.exists():
        return Check("rag", False, f"missing source directory {source_dir}")
    try:
        index = build_evidence_index(source_dir)
    except Exception as exc:
        return Check("rag", False, f"failed to build in-memory index from {source_dir}: {exc}")
    if build_index:
        try:
            save_evidence_index(index, index_path)
        except Exception as exc:
            return Check("rag", False, f"failed to write {index_path}: {exc}")
        return Check(
            "rag",
            True,
            f"{index.chunk_count} chunks from {source_dir}; wrote {index_path}",
        )
    if index_path.exists():
        try:
            saved = load_evidence_index(index_path)
        except Exception as exc:
            return Check("rag", False, f"configured index exists but cannot be loaded: {exc}")
        return Check(
            "rag",
            True,
            (
                f"{index.chunk_count} source chunks from {source_dir}; "
                f"{saved.chunk_count} saved chunks in {index_path}"
            ),
        )
    if require_index:
        return Check("rag", False, f"{index.chunk_count} source chunks but missing {index_path}")
    return Check(
        "rag",
        True,
        f"{index.chunk_count} source chunks from {source_dir}; index not written",
    )


def _check_breeding_libraries(cfg) -> list[Check]:
    loaders: dict[str, tuple[Path, Callable[[Path], list[dict[str, str]]]]] = {
        "marker_qtl": (cfg.marker_qtl_csv_path, load_marker_qtl_records),
        "phenotype_protocol": (
            cfg.phenotype_protocol_csv_path,
            load_phenotype_protocol_records,
        ),
        "field_trial": (cfg.field_trial_csv_path, load_field_trial_records),
    }
    checks: list[Check] = []
    for name, (path, loader) in loaders.items():
        if not path.exists():
            checks.append(Check(name, False, f"missing {path}"))
            continue
        try:
            rows = loader(path)
        except Exception as exc:
            checks.append(Check(name, False, f"{path}: {exc}"))
            continue
        checks.append(Check(name, True, f"{len(rows)} rows in {path}"))
    return checks


def _check_blank_templates() -> list[Check]:
    templates = {
        "marker_qtl": (ROOT / "docs/templates/marker_qtl_library_template.csv", MARKER_QTL_COLUMNS),
        "phenotype_protocol": (
            ROOT / "docs/templates/phenotype_protocol_library_template.csv",
            PHENOTYPE_PROTOCOL_COLUMNS,
        ),
        "field_trial": (
            ROOT / "docs/templates/field_trial_records_template.csv",
            FIELD_TRIAL_COLUMNS,
        ),
    }
    checks: list[Check] = []
    for name, (path, expected_columns) in templates.items():
        if not path.exists():
            checks.append(Check(f"template:{name}", False, f"missing {path}"))
            continue
        try:
            with path.open(encoding="utf-8", newline="") as stream:
                reader = csv.reader(stream)
                header = next(reader, None)
                extra_rows = sum(1 for _ in reader)
        except Exception as exc:
            checks.append(Check(f"template:{name}", False, f"{path}: {exc}"))
            continue
        if header != expected_columns:
            checks.append(
                Check(
                    f"template:{name}",
                    False,
                    f"header does not match expected schema in {path}",
                )
            )
            continue
        if extra_rows:
            checks.append(
                Check(
                    f"template:{name}",
                    False,
                    f"template must be blank but contains {extra_rows} data rows in {path}",
                )
            )
            continue
        checks.append(Check(f"template:{name}", True, f"blank schema is valid in {path}"))
    return checks


if __name__ == "__main__":
    raise SystemExit(main())
