"""Tests for agent helper functions that don't require an LLM call."""

from __future__ import annotations

from types import SimpleNamespace

from co_scientist.agents.base import BaseAgent
from co_scientist.agents.breeding_designer import (
    _attach_breeding_design_card_audit,
    _build_session_context,
    _filter_to_seen_urls,
    _load_risk_review_context,
    _load_validation_plan_context,
    _render_hypothesis_md,
)
from co_scientist.agents.display import (
    agent_step_name,
    core_agent_name,
    decorate_agent_payload,
    hypothesis_lifecycle_label,
    localize_iteration_decision,
    public_event_name,
    public_result_kind,
    review_verdict_label,
)
from co_scientist.agents.evidence_review import _render_review_md
from co_scientist.agents.iteration_orchestrator_synthesis import _format_preflight_rag_context
from co_scientist.models import ResearchPlan
from co_scientist.storage.artifacts import write_json


def test_six_agent_public_terms_are_exposed() -> None:
    assert core_agent_name("breeding_designer") == "Breeding Designer"
    assert core_agent_name("iteration_orchestrator") == "Iteration Orchestrator"
    assert agent_step_name("breeding_designer", "DesignHypothesis") == "Hypothesis design"
    assert agent_step_name("risk_reviewer", "AssessHypothesisEvidence") == "Evidence review"
    assert (
        agent_step_name("iteration_orchestrator", "GenerateFinalBreedingOverview")
        == "Final synthesis"
    )
    assert hypothesis_lifecycle_label("calibration_pool") == "candidate"
    assert hypothesis_lifecycle_label("pinned") == "ready"
    assert public_event_name("hypothesis_created") == "hypothesis_designed"
    assert public_result_kind("pairwise_calibration_complete") == "pairwise_calibration_complete"
    assert public_result_kind("evidence_review_completed") == "evidence_review_completed"
    assert review_verdict_label("missing_piece") == "needs evidence"


def test_agent_payload_decoration_preserves_internal_names_and_adds_public_terms() -> None:
    payload = decorate_agent_payload(
        {
            "task_id": "task_1",
            "agent": "iteration_orchestrator",
            "action": "RunPairwiseCalibration",
            "kind": "pairwise_calibration_complete",
        }
    )

    assert payload is not None
    assert payload["agent"] == "Iteration Orchestrator"
    assert payload["agent_internal"] == "iteration_orchestrator"
    assert payload["action_internal"] == "RunPairwiseCalibration"
    assert payload["public_action"] == "Pairwise calibration"
    assert payload["agent_step"] == "Pairwise calibration"
    assert payload["kind_internal"] == "pairwise_calibration_complete"
    assert payload["public_kind"] == "pairwise_calibration_complete"


def test_iteration_decision_localizes_current_route_revision_reasons() -> None:
    decision = localize_iteration_decision(
        {
            "action": "revise",
            "review_gate": "mixed",
            "next_step_recommendation": "generate_revised_hypothesis_from_decision",
            "reasons": [
                "Review verdict is missing_piece; the route should be revised before prioritization.",
                "Evidence gaps are manageable and the hypothesis can enter prioritization.",
            ],
            "route_revision_intent": {
                "route_revision_intent": "repair_parent_route",
                "new_hypothesis_direction": "Resolve local marker validation before prioritization.",
                "evidence_gap_to_resolve": [
                    "genotype_or_marker_validation: marker needs local validation"
                ],
                "do_not_repeat": [
                    "Marker or genotype validation must be carried into the next validation plan."
                ],
            },
        }
    )

    assert decision["display"]["action_label"]
    assert decision["display"]["review_gate_label"]
    assert decision["display"]["next_step_label"]
    assert decision["display"]["reasons"][0]
    intent = decision["display_route_revision_intent"]
    assert intent["intent_label"]
    assert intent["direction_label"]
    assert intent["evidence_gap_to_resolve_labels"][0]


def test_citation_url_filter_keeps_only_seen() -> None:
    citations = [
        {"title": "A", "url": "https://a.example/paper1"},
        {"title": "B", "url": "https://hallucinated.example/paper2"},
        {"title": "C", "url": "https://c.example/paper3"},
        {"no_url": True},
    ]
    seen = {"https://a.example/paper1", "https://c.example/paper3"}
    out = _filter_to_seen_urls(citations, seen)
    urls = {c["url"] for c in out}
    assert urls == seen
    # hallucinated URL is dropped
    assert "https://hallucinated.example/paper2" not in urls


def test_breeding_designer_session_context_includes_breeding_boundaries() -> None:
    context = _build_session_context(
        "Improve lodging resistance in foxtail millet under dense planting",
        ResearchPlan(
            objective="Improve lodging resistance",
            crop="foxtail millet",
            target_traits=["lodging resistance"],
            target_environments=["dense planting"],
            material_constraints=["local germplasm only"],
            preferred_breeding_strategies=["MAS"],
            validation_constraints=["CAPS marker preflight"],
            success_criteria=["reduce lodging without yield penalty"],
            initial_hypothesis_count=2,
            max_hypothesis_count=5,
            local_first=True,
        ),
        None,
    )

    assert "Crop: foxtail millet" in context
    assert "Target traits: lodging resistance" in context
    assert "Target environments: dense planting" in context
    assert "Material constraints: local germplasm only" in context
    assert "Preferred breeding strategies: MAS" in context
    assert "Success criteria: reduce lodging without yield penalty" in context


def test_final_tool_use_recovers_truncated_raw_arguments() -> None:
    raw = (
        '{"title": "T", "statement": "S", "statement_zh": "涓枃鍋囪", '
        '"mechanism": "M", "entities": ["263A", "Seita.5G404900"], '
        '"breeding_context": {"crop": "foxtail millet", "target_trait": "lodging"'
    )
    response = SimpleNamespace(
        raw=SimpleNamespace(
            content=[
                SimpleNamespace(
                    type="tool_use",
                    name="record_hypothesis",
                    input={"_raw_arguments": raw},
                )
            ]
        )
    )

    record = BaseAgent._final_tool_use(response, "record_hypothesis")

    assert record is not None
    assert record["statement"] == "S"
    assert record["statement_zh"] == "涓枃鍋囪"
    assert record["mechanism"] == "M"
    assert record["entities"] == ["263A", "Seita.5G404900"]
    assert record["_recovered_from_raw_arguments"] is True


def test_preflight_rag_context_uses_exact_local_urls(tmp_path) -> None:
    index_path = tmp_path / "evidence_index.json"
    index_path.write_text(
        """{
  "version": 1,
  "source_dir": "docs/rag_sources",
  "chunk_count": 2,
  "chunks": [
    {
      "chunk_id": "seita5g404900_caps_validation_preflight_2026-07.md#chunk-1",
      "source_path": "seita5g404900_caps_validation_preflight_2026-07.md",
      "title": "CAPS Preflight",
      "text": "# CAPS Preflight\\nGO / PAUSE / STOP Rules",
      "start_line": 1,
      "end_line": 20
    },
    {
      "chunk_id": "263a_jingu21_zhangza13_seed_confirmation_preflight_2026-07.md#chunk-1",
      "source_path": "263a_jingu21_zhangza13_seed_confirmation_preflight_2026-07.md",
      "title": "Seed Preflight",
      "text": "# Seed Preflight\\nEvidence Boundary",
      "start_line": 1,
      "end_line": 30
    }
  ]
}""",
        encoding="utf-8",
    )

    context = _format_preflight_rag_context(SimpleNamespace(rag_index_path=index_path))

    assert "Route-relevant local RAG preflight cards" in context
    assert (
        "local-rag://seita5g404900_caps_validation_preflight_2026-07.md#L1-L20"
        in context
    )
    assert (
        "local-rag://263a_jingu21_zhangza13_seed_confirmation_preflight_2026-07.md#L1-L30"
        in context
    )
    assert "placeholder" in context

    scoped_context = _format_preflight_rag_context(
        SimpleNamespace(rag_index_path=index_path),
        target_scope="foxtail millet stay-green and yield stability under drought marker validation",
        known_material_records=[
            {"accession_id": "ARCH-263A", "name": "263A"},
            {"accession_id": "ARCH-Jingu21", "name": "Jingu 21"},
            {"accession_id": "ARCH-Zhangza13", "name": "Zhangza 13"},
        ],
        allowed_accession_ids={"ARCH-263A"},
    )
    assert "local-rag://seita5g404900_caps_validation_preflight_2026-07.md#L1-L20" in scoped_context
    assert "263a_jingu21_zhangza13_seed_confirmation_preflight" not in scoped_context


def test_hypothesis_md_renders_sections() -> None:
    md = _render_hypothesis_md(
        {
            "title": "T",
            "statement": "S",
            "mechanism": "M",
            "entities": ["E1", "E2"],
            "anticipated_outcomes": "AO",
            "breeding_context": {
                "crop": "wheat",
                "target_trait": "drought tolerance",
                "germplasm": "elite winter wheat",
                "donor_parent": "drought donor D1",
                "recurrent_parent": "elite line R1",
                "material_availability": "D1 and R1 available in local nursery",
                "target_population_of_environments": "rainfed environments",
                "candidate_genes_qtl": ["QTL-1"],
                "breeding_strategy": "genomic selection",
                "selection_scheme": "F2 screen followed by genomic selection",
                "phenotyping_plan": "managed drought nursery",
                "genotyping_plan": "SNP array",
                "validation_trial_design": "multi-environment trial",
                "decision_thresholds": "advance if yield stability improves by 5%",
                "cycle_time_estimate": "one season to first evidence",
                "expected_breeding_value": "improved yield stability",
                "risks_tradeoffs": ["GxE instability"],
                "evidence_gaps": ["needs donor validation"],
                "fallback_route": "switch to broader diversity panel if D1 fails",
            },
            "novelty_argument": "N",
            "citations": [
                {"title": "Paper", "url": "https://example.com/x", "year": 2024}
            ],
        }
    )
    for marker in ("# T", "**Hypothesis.** S", "## Mechanism", "## Entities",
                   "## Breeding project context", "wheat", "genomic selection",
                   "drought donor D1", "elite line R1", "F2 screen",
                   "advance if yield stability improves by 5%",
                   "switch to broader diversity panel",
                   "## Anticipated outcomes", "## Novelty", "## Citations",
                   "https://example.com/x"):
        assert marker in md


def test_hypothesis_md_accepts_string_breeding_context() -> None:
    md = _render_hypothesis_md(
        {
            "title": "T",
            "statement": "S",
            "breeding_context": "CAPS validation pending; seed inventory pending.",
        }
    )

    assert "## Breeding project context" in md
    assert "CAPS validation pending" in md


def test_breeding_design_card_audit_flags_missing_critical_fields() -> None:
    record = {
        "statement": "Use a CAPS marker route.",
        "breeding_context": {
            "crop": "foxtail millet",
            "target_trait": "lodging resistance",
            "donor_parent": "ARCH-263A",
            "candidate_genes_qtl": ["Si5G404900C CAPS"],
            "phenotyping_plan": "dense planting lodging score",
            "evidence_gaps": ["marker needs local validation"],
        },
        "evidence_package_path": "artifacts/s/evidence/package.json",
        "validation_plan_path": "artifacts/s/validation/plan.json",
        "risk_review_path": "artifacts/s/risk/review.json",
    }

    _attach_breeding_design_card_audit(record)

    audit = record["breeding_design_card_audit"]
    assert audit["status"] == "needs_attention"
    assert "recurrent_parent" in audit["missing_critical_fields"]
    assert audit["checks"]["marker_or_qtl_explicit"] is True
    assert audit["context_sources"]["risk_review"] is True


async def test_breeding_designer_loads_validation_and_risk_context(tmp_cfg) -> None:
    validation_path = await write_json(
        tmp_cfg,
        "ses_design_context",
        "validation",
        "plan",
        {
            "validation_readiness_score": 82,
            "readiness_level": "ready",
            "breeding_goal": {
                "crop": "foxtail millet",
                "target_trait": "lodging resistance",
                "donor_parent": "ARCH-263A",
                "candidate_genes_qtl_markers": ["Si5G404900C CAPS"],
            },
            "genotyping_plan": {"assay": "CAPS marker preflight"},
            "critical_evidence_gaps": [
                {
                    "type": "genotype_or_marker_validation",
                    "severity": "high",
                    "message": "Marker needs local validation.",
                }
            ],
        },
    )
    risk_path = await write_json(
        tmp_cfg,
        "ses_design_context",
        "risk",
        "review",
        {
            "risk_control_score": 66,
            "risk_level": "moderate",
            "risk_items": [
                {
                    "category": "genetic",
                    "severity": "high",
                    "message": "Marker transferability is not confirmed.",
                }
            ],
            "must_resolve_before_prioritization": [
                {
                    "category": "genetic",
                    "severity": "high",
                    "message": "Marker transferability is not confirmed.",
                    "mitigation": "run marker polymorphism preflight",
                }
            ],
        },
    )

    validation_context = await _load_validation_plan_context(tmp_cfg, validation_path)
    risk_context = await _load_risk_review_context(tmp_cfg, risk_path)

    assert "Validation Planner guidance" in validation_context
    assert "CAPS marker preflight" in validation_context
    assert "Marker needs local validation" in validation_context
    assert "Risk Reviewer guidance" in risk_context
    assert "Marker transferability is not confirmed" in risk_context
    assert "run marker polymorphism preflight" in risk_context


def test_review_md_renders_sections() -> None:
    md = _render_review_md(
        {
            "verdict": "missing_piece",
            "novelty": 0.7, "correctness": 0.5, "testability": 0.6,
            "assumptions": [
                {"assumption": "A1", "plausibility": "plausible", "rationale": "R1"}
            ],
            "evidence": [
                {"claim": "claim1", "url": "https://e.example/p", "excerpt": "quote"}
            ],
            "notes": "n",
        }
    )
    assert "Verdict" in md
    assert "novelty 0.70" in md
    assert "plausible" in md
    assert "https://e.example/p" in md
    assert "n" in md


def test_review_md_accepts_string_scores_from_model_output() -> None:
    md = _render_review_md(
        {
            "verdict": "strong",
            "novelty": "0.70",
            "correctness": "0.55",
            "testability": "0.80",
            "feasibility": "0.65",
            "genetic_gain_potential": "0.60",
        }
    )
    assert "novelty 0.70" in md
    assert "genetic_gain_potential 0.60" in md

