from __future__ import annotations

from pathlib import Path

from co_scientist.knowledge.germplasm import (
    EXPECTED_COLUMNS,
    load_germplasm_records,
    search_germplasm_records,
    validate_germplasm_csv,
)


def _write_csv(path: Path, rows: list[dict[str, str]]) -> None:
    lines = [",".join(EXPECTED_COLUMNS)]
    for row in rows:
        lines.append(",".join(row.get(col, "") for col in EXPECTED_COLUMNS))
    path.write_text("\n".join(lines) + "\n", encoding="utf-8")


def test_public_seed_germplasm_csv_is_valid() -> None:
    path = Path("docs/templates/germplasm_resources_public_seed.csv")
    result = validate_germplasm_csv(path)
    assert result.ok
    assert result.row_count == 35
    assert result.issues == []


def test_germplasm_validation_rejects_duplicate_ids_and_bad_terms(tmp_path: Path) -> None:
    path = tmp_path / "bad.csv"
    base = {
        "accession_id": "G1",
        "name": "Material 1",
        "crop": "foxtail millet",
        "germplasm_type": "landrace",
        "source": "demo",
        "availability": "maybe",
        "primary_traits": "drought tolerance",
        "summary": "Demo material.",
        "source_refs": "https://example.test/source",
        "data_confidence": "certain",
    }
    _write_csv(path, [base, {**base, "name": "Material duplicate"}])

    result = validate_germplasm_csv(path)

    assert not result.ok
    messages = [issue.message for issue in result.issues]
    assert any("Duplicate accession_id" in message for message in messages)
    assert any("Invalid availability" in message for message in messages)
    assert any("Invalid data_confidence" in message for message in messages)


def test_germplasm_validation_rejects_ragged_rows(tmp_path: Path) -> None:
    path = tmp_path / "ragged.csv"
    path.write_text(",".join(EXPECTED_COLUMNS) + "\nG1,Material 1\n", encoding="utf-8")

    result = validate_germplasm_csv(path)

    assert not result.ok
    assert any("Expected 31 columns" in issue.message for issue in result.issues)


def test_germplasm_validation_warns_on_gene_claim_without_genotype_evidence(
    tmp_path: Path,
) -> None:
    path = tmp_path / "gene_claim.csv"
    _write_csv(
        path,
        [
            {
                "accession_id": "G2",
                "name": "Material 2",
                "crop": "foxtail millet",
                "germplasm_type": "variety",
                "source": "demo",
                "availability": "unknown",
                "primary_traits": "plant architecture",
                "summary": "Demo material.",
                "known_genes_qtls": "SiNF-YC2 Hap-A",
                "source_refs": "https://example.test/source",
                "genotype_evidence": "no genotype evidence in source table",
                "data_confidence": "medium",
            }
        ],
    )

    result = validate_germplasm_csv(path)

    assert result.ok
    assert any(issue.level == "warning" for issue in result.issues)


def test_germplasm_search_finds_architecture_records() -> None:
    path = Path("docs/templates/germplasm_resources_public_seed.csv")
    records = load_germplasm_records(path)

    results = search_germplasm_records(
        records,
        "lodging architecture",
        crop="foxtail millet",
        min_confidence="medium",
        limit=5,
    )

    ids = {result.record["accession_id"] for result in results}
    assert "ARCH-263A" in ids
    assert all(result.record["data_confidence"] == "medium" for result in results)


def test_germplasm_search_can_filter_by_trait() -> None:
    path = Path("docs/templates/germplasm_resources_public_seed.csv")
    records = load_germplasm_records(path)

    results = search_germplasm_records(records, "QTL", trait="yield traits", limit=10)

    ids = {result.record["accession_id"] for result in results}
    assert {"ARCH-Longgu7", "ARCH-Hongmiaozhangu", "ARCH-Changnong35"} <= ids
