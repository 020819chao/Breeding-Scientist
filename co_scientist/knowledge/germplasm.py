"""Validation helpers for germplasm resource CSV files."""

from __future__ import annotations

import csv
from dataclasses import dataclass
from pathlib import Path

REQUIRED_COLUMNS = [
    "accession_id",
    "name",
    "crop",
    "germplasm_type",
    "source",
    "availability",
    "primary_traits",
    "summary",
]

EXPECTED_COLUMNS = [
    "accession_id",
    "name",
    "crop",
    "germplasm_type",
    "source",
    "availability",
    "primary_traits",
    "summary",
    "ecological_zone",
    "strengths",
    "weaknesses",
    "known_genes_qtls",
    "markers",
    "phenotype_evidence",
    "genotype_evidence",
    "breeding_use",
    "risk_notes",
    "source_refs",
    "pedigree",
    "population",
    "maturity_group",
    "plant_height",
    "yield_level",
    "quality_traits",
    "stress_tolerance",
    "disease_resistance",
    "preferred_crosses",
    "avoid_crosses",
    "data_confidence",
    "last_updated",
    "notes",
]

VALID_AVAILABILITY = {"available", "limited", "unavailable", "unknown"}
VALID_CONFIDENCE = {"high", "medium", "low"}

SEARCH_FIELDS = [
    "accession_id",
    "name",
    "crop",
    "germplasm_type",
    "primary_traits",
    "summary",
    "ecological_zone",
    "strengths",
    "weaknesses",
    "known_genes_qtls",
    "markers",
    "phenotype_evidence",
    "genotype_evidence",
    "breeding_use",
    "risk_notes",
    "source_refs",
    "population",
    "plant_height",
    "yield_level",
    "quality_traits",
    "stress_tolerance",
    "disease_resistance",
    "notes",
]


@dataclass(frozen=True)
class ValidationIssue:
    row_number: int
    level: str
    message: str


@dataclass(frozen=True)
class GermplasmValidationResult:
    path: Path
    row_count: int
    issues: list[ValidationIssue]

    @property
    def ok(self) -> bool:
        return not any(issue.level == "error" for issue in self.issues)


@dataclass(frozen=True)
class GermplasmSearchResult:
    score: int
    record: dict[str, str]
    matched_fields: list[str]


def validate_germplasm_csv(path: Path) -> GermplasmValidationResult:
    """Validate a germplasm CSV without mutating it."""

    issues: list[ValidationIssue] = []
    with path.open(encoding="utf-8", newline="") as f:
        raw_rows = list(csv.reader(f))
    for raw_idx, raw_row in enumerate(raw_rows, start=1):
        if len(raw_row) != len(EXPECTED_COLUMNS):
            issues.append(
                ValidationIssue(
                    raw_idx,
                    "error",
                    f"Expected {len(EXPECTED_COLUMNS)} columns but found {len(raw_row)}.",
                )
            )

    with path.open(encoding="utf-8", newline="") as f:
        reader = csv.DictReader(f)
        fieldnames = reader.fieldnames or []
        if fieldnames != EXPECTED_COLUMNS:
            issues.append(
                ValidationIssue(
                    1,
                    "error",
                    "CSV header does not match the germplasm resource schema.",
                )
            )
        missing_columns = [col for col in REQUIRED_COLUMNS if col not in fieldnames]
        if missing_columns:
            issues.append(
                ValidationIssue(
                    1,
                    "error",
                    f"Missing required columns: {', '.join(missing_columns)}.",
                )
            )

        seen_ids: dict[str, int] = {}
        rows = list(reader)

    for idx, row in enumerate(rows, start=2):
        accession_id = (row.get("accession_id") or "").strip()
        if not accession_id:
            issues.append(ValidationIssue(idx, "error", "Missing accession_id."))
        elif accession_id in seen_ids:
            issues.append(
                ValidationIssue(
                    idx,
                    "error",
                    f"Duplicate accession_id {accession_id!r}; first seen on row {seen_ids[accession_id]}.",
                )
            )
        else:
            seen_ids[accession_id] = idx

        for col in REQUIRED_COLUMNS:
            if not (row.get(col) or "").strip():
                issues.append(ValidationIssue(idx, "error", f"Missing required field {col!r}."))

        availability = (row.get("availability") or "").strip()
        if availability and availability not in VALID_AVAILABILITY:
            issues.append(
                ValidationIssue(
                    idx,
                    "error",
                    f"Invalid availability {availability!r}; expected one of {sorted(VALID_AVAILABILITY)}.",
                )
            )

        confidence = (row.get("data_confidence") or "").strip()
        if confidence and confidence not in VALID_CONFIDENCE:
            issues.append(
                ValidationIssue(
                    idx,
                    "error",
                    f"Invalid data_confidence {confidence!r}; expected one of {sorted(VALID_CONFIDENCE)}.",
                )
            )

        source_refs = (row.get("source_refs") or "").strip()
        known_genes_qtls = (row.get("known_genes_qtls") or "").strip()
        markers = (row.get("markers") or "").strip()
        genotype_evidence = (row.get("genotype_evidence") or "").strip().lower()

        if not source_refs:
            issues.append(ValidationIssue(idx, "warning", "Missing source_refs."))
        if (known_genes_qtls or markers) and not source_refs:
            issues.append(
                ValidationIssue(
                    idx,
                    "error",
                    "Gene/QTL or marker claims require source_refs.",
                )
            )
        if (known_genes_qtls or markers) and (
            not genotype_evidence or "no genotype evidence" in genotype_evidence
        ):
            issues.append(
                ValidationIssue(
                    idx,
                    "warning",
                    "Gene/QTL or marker fields are present but genotype_evidence is absent or negative.",
                )
            )

    return GermplasmValidationResult(path=path, row_count=len(rows), issues=issues)


def load_germplasm_records(path: Path) -> list[dict[str, str]]:
    """Load a germplasm CSV after validating that it has no hard errors."""

    result = validate_germplasm_csv(path)
    if not result.ok:
        messages = "; ".join(
            f"row {issue.row_number}: {issue.message}"
            for issue in result.issues
            if issue.level == "error"
        )
        raise ValueError(f"Invalid germplasm CSV: {messages}")

    with path.open(encoding="utf-8", newline="") as f:
        return [
            {key: (value or "").strip() for key, value in row.items()}
            for row in csv.DictReader(f)
        ]


def search_germplasm_records(
    records: list[dict[str, str]],
    query: str,
    *,
    crop: str | None = None,
    trait: str | None = None,
    min_confidence: str | None = None,
    limit: int = 10,
) -> list[GermplasmSearchResult]:
    """Search germplasm records with deterministic keyword scoring.

    This is intentionally simple: it keeps the seed database useful before we
    wire in vector retrieval or an LLM-facing tool.
    """

    query_terms = _terms(query)
    crop_term = (crop or "").strip().lower()
    trait_terms = _terms(trait or "")
    min_rank = _confidence_rank(min_confidence)

    results: list[GermplasmSearchResult] = []
    for record in records:
        if crop_term and crop_term not in (record.get("crop") or "").lower():
            continue
        if min_rank is not None and _confidence_rank(record.get("data_confidence")) < min_rank:
            continue
        if trait_terms:
            trait_text = _record_text(record, ["primary_traits", "summary", "breeding_use"])
            if not all(term in trait_text for term in trait_terms):
                continue

        score, matched_fields = _score_record(record, query_terms)
        if query_terms and score == 0:
            continue
        if trait_terms:
            score += 2 * len(trait_terms)
            matched_fields = sorted({*matched_fields, "primary_traits"})
        results.append(GermplasmSearchResult(score=score, record=record, matched_fields=matched_fields))

    return sorted(
        results,
        key=lambda result: (
            -result.score,
            result.record.get("data_confidence") != "high",
            result.record.get("data_confidence") != "medium",
            result.record.get("accession_id", ""),
        ),
    )[:limit]


def _score_record(record: dict[str, str], query_terms: list[str]) -> tuple[int, list[str]]:
    if not query_terms:
        return 1, []

    score = 0
    matched_fields: list[str] = []
    for field in SEARCH_FIELDS:
        value = (record.get(field) or "").lower()
        if not value:
            continue
        field_hits = sum(1 for term in query_terms if term in value)
        if not field_hits:
            continue
        weight = 3 if field in {"accession_id", "name", "primary_traits", "known_genes_qtls"} else 1
        score += field_hits * weight
        matched_fields.append(field)
    return score, matched_fields


def _record_text(record: dict[str, str], fields: list[str]) -> str:
    return " ".join((record.get(field) or "").lower() for field in fields)


def _terms(text: str) -> list[str]:
    return [term for term in text.lower().replace(";", " ").replace(",", " ").split() if term]


def _confidence_rank(confidence: str | None) -> int:
    return {"low": 1, "medium": 2, "high": 3}.get((confidence or "").strip(), 0)
