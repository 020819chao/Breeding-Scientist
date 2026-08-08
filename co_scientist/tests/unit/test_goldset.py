"""Tests for the breeding bench gold-set matcher."""

from __future__ import annotations

from co_scientist.bench.goldset import (
    GOLDSETS,
    MINOR_GRAIN_DROUGHT_DEMO,
    MINOR_GRAIN_RESOURCE_DEMO,
    GoldEntity,
    GoldSet,
    _contains_subseq,
    _tokens,
    score_candidate_against_goldset,
    score_hypothesis_against_goldset,
)


def _hyp(**kwargs) -> dict:
    return {
        "id": kwargs.pop("id", "hyp_t"),
        "title": kwargs.pop("title", ""),
        "summary": kwargs.pop("summary", ""),
        "full_text": kwargs.pop("full_text", ""),
        "entities": kwargs.pop("entities", []),
        "citations": kwargs.pop("citations", []),
    }


def test_tokens_lowercases_and_splits_breeding_ids() -> None:
    assert _tokens("Seita.5G404900 / qPH5.1") == ["seita", "5g404900", "qph5", "1"]


def test_tokens_handles_unicode_normalization() -> None:
    assert _tokens("Cafe") == ["cafe"]


def test_contains_subseq_requires_contiguous_match() -> None:
    h = ["managed", "drought", "phenotyping", "with", "spad"]
    assert _contains_subseq(h, ["drought", "phenotyping"])
    assert not _contains_subseq(h, ["phenotyping", "drought"])
    assert not _contains_subseq(h, ["drought", "spad"])
    assert not _contains_subseq(h, [])


def test_canonical_marker_in_title_hits() -> None:
    h = _hyp(title="Use Seita.5G404900 to prioritize drought-tolerant demo lines")
    hits = score_hypothesis_against_goldset(h, MINOR_GRAIN_DROUGHT_DEMO)
    assert any(r.entity == "Seita.5G404900" for r in hits)


def test_qtl_alias_hits_marker_entity() -> None:
    h = _hyp(full_text="The route uses qPH5.1 as a marker-linked plant-height clue.")
    hits = score_hypothesis_against_goldset(h, MINOR_GRAIN_DROUGHT_DEMO)
    assert len(hits) == 1
    assert hits[0].entity == "Seita.5G404900"
    assert hits[0].matched_alias == "qPH5.1"


def test_stress_response_alias_in_entities_hits() -> None:
    h = _hyp(entities=["SiDREB2", "drought response", "stay-green"])
    hits = score_hypothesis_against_goldset(h, MINOR_GRAIN_DROUGHT_DEMO)
    assert any(r.entity == "SiDREB2-like" for r in hits)


def test_marker_validation_in_citation_excerpt_hits() -> None:
    h = _hyp(
        citations=[
            {
                "title": "Local validation note",
                "url": "local-rag://marker-note",
                "excerpt": "CAPS marker validation is still required in target parents.",
            }
        ]
    )
    hits = score_hypothesis_against_goldset(h, MINOR_GRAIN_DROUGHT_DEMO)
    assert any(r.entity == "CAPS marker validation" for r in hits)


def test_generic_marker_word_alone_does_not_hit() -> None:
    h = _hyp(full_text="Use a marker-assisted selection route if a marker exists.")
    hits = score_hypothesis_against_goldset(h, MINOR_GRAIN_DROUGHT_DEMO)
    assert hits == []


def test_partial_marker_name_does_not_hit() -> None:
    h = _hyp(full_text="The candidate locus is 5G404 related but unresolved.")
    hits = score_hypothesis_against_goldset(h, MINOR_GRAIN_DROUGHT_DEMO)
    assert hits == []


def test_material_alias_hits_resource_core() -> None:
    h = _hyp(full_text="Jingu21 can serve as a recurrent parent.")
    hits = score_hypothesis_against_goldset(h, MINOR_GRAIN_RESOURCE_DEMO)
    assert any(r.entity == "Jingu 21" for r in hits)


def test_short_accession_boundary_prevents_false_positive() -> None:
    h_yes = _hyp(full_text="263A donor can be crossed into elite backgrounds.")
    h_no = _hyp(full_text="line X263AY is an unrelated identifier.")
    assert any(
        r.entity == "263A"
        for r in score_hypothesis_against_goldset(h_yes, MINOR_GRAIN_RESOURCE_DEMO)
    )
    assert score_hypothesis_against_goldset(h_no, MINOR_GRAIN_RESOURCE_DEMO) == []


def test_score_candidate_aggregates_per_entity() -> None:
    hyps = [
        _hyp(id="h1", summary="Seita.5G404900 route with CAPS validation"),
        _hyp(id="h2", full_text="qPH5.1 should be checked before advancement."),
    ]
    agg = score_candidate_against_goldset(hyps, MINOR_GRAIN_DROUGHT_DEMO)
    assert set(agg) == {"Seita.5G404900", "CAPS marker validation"}
    assert len(agg["Seita.5G404900"]) == 2


def test_score_candidate_full_recall_drought_core() -> None:
    hyps = [
        _hyp(full_text="Seita.5G404900 marker path"),
        _hyp(full_text="SiDREB2-like drought response mechanism"),
        _hyp(full_text="CAPS marker validation in parents"),
    ]
    agg = score_candidate_against_goldset(hyps, MINOR_GRAIN_DROUGHT_DEMO)
    assert set(agg.keys()) == {
        "Seita.5G404900",
        "SiDREB2-like",
        "CAPS marker validation",
    }


def test_empty_candidate_returns_empty() -> None:
    assert score_candidate_against_goldset([], MINOR_GRAIN_DROUGHT_DEMO) == {}


def test_drought_demo_goldset_has_three_entities() -> None:
    names = [e.name for e in MINOR_GRAIN_DROUGHT_DEMO.entities]
    assert names == ["Seita.5G404900", "SiDREB2-like", "CAPS marker validation"]


def test_resource_demo_goldset_has_practical_material_clues() -> None:
    names = {e.name for e in MINOR_GRAIN_RESOURCE_DEMO.entities}
    assert {"Jingu 21", "Zhangza 13", "263A", "BC1F1 validation"} <= names


def test_goldsets_registry_contains_minor_grain_demo_sets() -> None:
    assert GOLDSETS["minor-grain-drought-demo"] is MINOR_GRAIN_DROUGHT_DEMO
    assert GOLDSETS["minor-grain-resource-demo"] is MINOR_GRAIN_RESOURCE_DEMO


def test_custom_gold_set_with_aliases() -> None:
    gs = GoldSet(
        label="custom",
        description="test",
        entities=[
            GoldEntity(name="stay-green", aliases=("delayed senescence",)),
        ],
    )
    h = _hyp(full_text="delayed senescence under drought stress")
    hits = score_hypothesis_against_goldset(h, gs)
    assert len(hits) == 1
    assert hits[0].entity == "stay-green"
