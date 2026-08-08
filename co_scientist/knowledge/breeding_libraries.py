"""Local breeding evidence libraries.

These helpers keep Evidence Curator local-first while making marker/QTL,
phenotyping protocol, and field-trial records searchable as structured
evidence rather than loose text.
"""

from __future__ import annotations

import csv
import re
from dataclasses import dataclass
from pathlib import Path

MARKER_QTL_COLUMNS = [
    "marker_id",
    "crop",
    "trait",
    "gene_or_qtl",
    "marker_name",
    "marker_type",
    "linked_materials",
    "validation_status",
    "assay_protocol",
    "source_refs",
    "evidence_summary",
    "risk_notes",
    "data_confidence",
    "last_updated",
    "notes",
]

PHENOTYPE_PROTOCOL_COLUMNS = [
    "protocol_id",
    "crop",
    "trait",
    "target_environment",
    "measurement_method",
    "scale_or_unit",
    "stage",
    "replication",
    "decision_thresholds",
    "source_refs",
    "validation_status",
    "risk_notes",
    "data_confidence",
    "notes",
]

FIELD_TRIAL_COLUMNS = [
    "trial_id",
    "crop",
    "trait",
    "environment",
    "season",
    "materials",
    "test_design",
    "phenotype_summary",
    "genotype_summary",
    "decision_outcome",
    "source_refs",
    "data_confidence",
    "risk_notes",
    "notes",
]

REQUIRED_BY_KIND = {
    "marker_qtl": [
        "marker_id",
        "crop",
        "trait",
        "gene_or_qtl",
        "marker_name",
        "source_refs",
        "data_confidence",
    ],
    "phenotype_protocol": [
        "protocol_id",
        "crop",
        "trait",
        "measurement_method",
        "decision_thresholds",
        "data_confidence",
    ],
    "field_trial": [
        "trial_id",
        "crop",
        "trait",
        "environment",
        "materials",
        "phenotype_summary",
        "data_confidence",
    ],
}

ID_FIELD_BY_KIND = {
    "marker_qtl": "marker_id",
    "phenotype_protocol": "protocol_id",
    "field_trial": "trial_id",
}

SEARCH_FIELDS_BY_KIND = {
    "marker_qtl": [
        "marker_id",
        "crop",
        "trait",
        "gene_or_qtl",
        "marker_name",
        "marker_type",
        "linked_materials",
        "validation_status",
        "assay_protocol",
        "source_refs",
        "evidence_summary",
        "risk_notes",
        "notes",
    ],
    "phenotype_protocol": [
        "protocol_id",
        "crop",
        "trait",
        "target_environment",
        "measurement_method",
        "scale_or_unit",
        "stage",
        "replication",
        "decision_thresholds",
        "source_refs",
        "validation_status",
        "risk_notes",
        "notes",
    ],
    "field_trial": [
        "trial_id",
        "crop",
        "trait",
        "environment",
        "season",
        "materials",
        "test_design",
        "phenotype_summary",
        "genotype_summary",
        "decision_outcome",
        "source_refs",
        "risk_notes",
        "notes",
    ],
}

VALID_CONFIDENCE = {"high", "medium", "low"}


@dataclass(frozen=True)
class LibrarySearchResult:
    score: int
    record: dict[str, str]
    matched_fields: list[str]


def load_marker_qtl_records(path: Path) -> list[dict[str, str]]:
    return _load_library(path, kind="marker_qtl", columns=MARKER_QTL_COLUMNS)


def load_phenotype_protocol_records(path: Path) -> list[dict[str, str]]:
    return _load_library(
        path,
        kind="phenotype_protocol",
        columns=PHENOTYPE_PROTOCOL_COLUMNS,
    )


def load_field_trial_records(path: Path) -> list[dict[str, str]]:
    return _load_library(path, kind="field_trial", columns=FIELD_TRIAL_COLUMNS)


def search_marker_qtl_records(
    records: list[dict[str, str]],
    query: str,
    *,
    crop: str | None = None,
    limit: int = 10,
) -> list[LibrarySearchResult]:
    return _search_library(records, query, kind="marker_qtl", crop=crop, limit=limit)


def search_phenotype_protocol_records(
    records: list[dict[str, str]],
    query: str,
    *,
    crop: str | None = None,
    limit: int = 10,
) -> list[LibrarySearchResult]:
    return _search_library(records, query, kind="phenotype_protocol", crop=crop, limit=limit)


def search_field_trial_records(
    records: list[dict[str, str]],
    query: str,
    *,
    crop: str | None = None,
    limit: int = 10,
) -> list[LibrarySearchResult]:
    return _search_library(records, query, kind="field_trial", crop=crop, limit=limit)


def _load_library(path: Path, *, kind: str, columns: list[str]) -> list[dict[str, str]]:
    with path.open(encoding="utf-8", newline="") as f:
        reader = csv.DictReader(f)
        if reader.fieldnames != columns:
            raise ValueError(f"{kind} CSV header does not match the expected schema")
        rows = [{key: (value or "").strip() for key, value in row.items()} for row in reader]

    seen_ids: set[str] = set()
    required = REQUIRED_BY_KIND[kind]
    id_field = ID_FIELD_BY_KIND[kind]
    for index, row in enumerate(rows, start=2):
        record_id = row.get(id_field) or ""
        if not record_id:
            raise ValueError(f"{kind} row {index} is missing {id_field}")
        if record_id in seen_ids:
            raise ValueError(f"{kind} row {index} duplicates {id_field} {record_id!r}")
        seen_ids.add(record_id)
        missing = [field for field in required if not row.get(field)]
        if missing:
            raise ValueError(f"{kind} row {index} is missing required fields: {', '.join(missing)}")
        confidence = (row.get("data_confidence") or "").lower()
        if confidence not in VALID_CONFIDENCE:
            raise ValueError(
                f"{kind} row {index} has invalid data_confidence {confidence!r}"
            )
    return rows


def _search_library(
    records: list[dict[str, str]],
    query: str,
    *,
    kind: str,
    crop: str | None,
    limit: int,
) -> list[LibrarySearchResult]:
    query_terms = _terms(query)
    crop_term = (crop or "").strip().lower()
    fields = SEARCH_FIELDS_BY_KIND[kind]
    id_field = ID_FIELD_BY_KIND[kind]

    results: list[LibrarySearchResult] = []
    for record in records:
        if crop_term and crop_term not in (record.get("crop") or "").lower():
            continue
        score, matched_fields = _score_record(record, query_terms, fields=fields)
        if query_terms and score == 0:
            continue
        results.append(
            LibrarySearchResult(
                score=score or 1,
                record=record,
                matched_fields=matched_fields,
            )
        )

    return sorted(
        results,
        key=lambda result: (
            -result.score,
            result.record.get("data_confidence") != "high",
            result.record.get("data_confidence") != "medium",
            result.record.get(id_field, ""),
        ),
    )[:limit]


def _score_record(
    record: dict[str, str],
    query_terms: list[str],
    *,
    fields: list[str],
) -> tuple[int, list[str]]:
    if not query_terms:
        return 1, []
    score = 0
    matched_fields: list[str] = []
    for field in fields:
        value = (record.get(field) or "").lower()
        if not value:
            continue
        hits = sum(1 for term in query_terms if term in value)
        if not hits:
            continue
        weight = 3 if field in {"marker_id", "gene_or_qtl", "marker_name", "trait"} else 1
        score += hits * weight
        matched_fields.append(field)
    return score, matched_fields


def _terms(text: str) -> list[str]:
    return [
        term
        for term in re.findall(r"[A-Za-z0-9_.:-]+|[\u4e00-\u9fff]+", text.lower())
        if len(term) > 1
    ]
