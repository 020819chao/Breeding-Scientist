from __future__ import annotations

from pathlib import Path

from co_scientist.knowledge.rag import (
    build_evidence_index,
    deduplicate_source_documents,
    document_id_for_text,
    load_evidence_index,
    save_evidence_index,
    search_evidence_index,
)


def test_build_and_search_evidence_index(tmp_path: Path) -> None:
    sources = tmp_path / "sources"
    sources.mkdir()
    (sources / "README.md").write_text(
        "# Source guidance\n\nCAPS template guidance should not be indexed.\n",
        encoding="utf-8",
    )
    (sources / "_draft_note.md").write_text(
        "# Draft\n\nSiNF-YC2 draft text should not be indexed.\n",
        encoding="utf-8",
    )
    (sources / "millet_lodging.md").write_text(
        """# Foxtail millet lodging notes

SiNF-YC2 and dense planting architecture may affect stem strength in foxtail millet.
CAPS marker validation should be treated as a candidate marker workflow, not proof
of broad multi-environment yield benefit.
""",
        encoding="utf-8",
    )

    index = build_evidence_index(sources, chunk_chars=240, chunk_overlap=40)
    results = search_evidence_index(index, "SiNF-YC2 CAPS marker", limit=3)

    assert index.chunk_count >= 1
    assert all(chunk.source_path not in {"README.md", "_draft_note.md"} for chunk in index.chunks)
    assert results
    assert results[0].chunk.source_path == "millet_lodging.md"
    assert {"sinf-yc2", "caps", "marker"} <= set(results[0].matched_terms)


def test_save_and_load_evidence_index_roundtrip(tmp_path: Path) -> None:
    sources = tmp_path / "sources"
    sources.mkdir()
    (sources / "trait.txt").write_text("lodging resistance needs field validation\n", encoding="utf-8")
    out = tmp_path / "index.json"

    index = build_evidence_index(sources)
    save_evidence_index(index, out)
    loaded = load_evidence_index(out)

    assert loaded.chunk_count == index.chunk_count
    assert loaded.chunks[0].source_path == "trait.txt"
    assert loaded.chunks[0].document_id == document_id_for_text(
        "lodging resistance needs field validation\n"
    )


def test_rag_index_and_source_cleanup_deduplicate_same_document(tmp_path: Path) -> None:
    sources = tmp_path / "sources"
    (sources / "first").mkdir(parents=True)
    (sources / "second").mkdir()
    text = "# Shared evidence\n\nThe same local field note was imported twice.\n"
    (sources / "first" / "note.md").write_text(text, encoding="utf-8")
    (sources / "second" / "copy.md").write_text(text, encoding="utf-8")

    index = build_evidence_index(sources)
    assert index.chunk_count == 1
    assert {chunk.document_id for chunk in index.chunks} == {document_id_for_text(text)}

    assert deduplicate_source_documents(sources) == 1
    remaining = [path for path in sources.rglob("*.md")]
    assert [path.relative_to(sources).as_posix() for path in remaining] == ["first/note.md"]
