"""Iteration Orchestrator agent - closes the review/evidence loop.

V1 is deterministic: it reads the latest review plus the focused DFRS evidence
package for one hypothesis and writes a small decision artifact. Later versions
can replace the scoring rules with an LLM- or policy-assisted decision layer.
"""

from __future__ import annotations

from collections import Counter
from datetime import UTC, datetime
from typing import Any, Literal

from ..models import Review, Task, TaskResult
from ..storage.artifacts import read_json, write_json
from ..storage.repos import hypotheses as hyp_repo
from ..storage.repos import reviews as rev_repo
from ..storage.repos import sessions as sess_repo
from .base import BaseAgent

IterationAction = Literal["keep", "revise", "expand", "pause", "reject"]


class IterationOrchestratorAgent(BaseAgent):
    """Decide what should happen after DFRS evidence is curated."""

    name = "Iteration Orchestrator"

    async def execute(self, task: Task) -> TaskResult:
        if task.action != "DecideIteration":
            raise ValueError(f"IterationOrchestratorAgent does not handle action {task.action!r}")
        if not task.target_id:
            raise ValueError("IterationOrchestratorAgent.execute requires target_id")

        session = await sess_repo.fetch(self.deps.db, task.session_id)
        if session is None:
            raise RuntimeError(f"session {task.session_id} missing")
        hypothesis = await hyp_repo.fetch(self.deps.db, task.target_id)
        if hypothesis is None:
            raise RuntimeError(f"hypothesis {task.target_id} missing")

        reviews = await rev_repo.list_for_hypothesis(self.deps.db, hypothesis.id)
        latest_review = reviews[0] if reviews else None
        package = await _load_package(self.deps.cfg, task.payload.get("evidence_package_path"))
        validation_plan = await _load_package(
            self.deps.cfg,
            task.payload.get("validation_plan_path"),
        )
        risk_review = await _load_package(self.deps.cfg, task.payload.get("risk_review_path"))
        hypothesis_artifact = await _load_package(self.deps.cfg, hypothesis.artifact_path)
        design_card_audit = _extract_design_card_audit(hypothesis_artifact)
        decision = _decide_iteration(
            hypothesis_id=hypothesis.id,
            review=latest_review,
            package=package,
            validation_plan=validation_plan,
            risk_review=risk_review,
            design_card_audit=design_card_audit,
        )
        decision.update(
            {
                "version": 1,
                "agent": self.name,
                "session_id": session.id,
                "hypothesis_id": hypothesis.id,
                "hypothesis_title": hypothesis.title,
                "created_at": datetime.now(UTC).isoformat(),
                "evidence_package_path": task.payload.get("evidence_package_path"),
                "breeding_evidence_graph_path": task.payload.get("breeding_evidence_graph_path"),
                "validation_plan_path": task.payload.get("validation_plan_path"),
                "risk_review_path": task.payload.get("risk_review_path"),
                "breeding_design_card_audit": decision.get("breeding_design_card_audit", {}),
                "review_id": latest_review.id if latest_review else None,
                "review_verdict": latest_review.verdict if latest_review else None,
                "review_scores": _review_scores(latest_review),
            }
        )
        decision_path = await write_json(
            self.deps.cfg,
            session.id,
            "iteration",
            f"decision_{task.id}",
            decision,
        )

        action = str(decision["action"])
        if action == "reject":
            await hyp_repo.set_state(self.deps.db, hypothesis.id, "rejected")
        elif action == "pause":
            await hyp_repo.set_state(self.deps.db, hypothesis.id, "quarantined")

        return TaskResult(
            kind="iteration_decision",
            hypothesis_ids=[hypothesis.id],
            extra={
                "action": action,
                "decision_path": decision_path,
                "evidence_package_path": task.payload.get("evidence_package_path"),
                "breeding_evidence_graph_path": task.payload.get("breeding_evidence_graph_path"),
                "validation_plan_path": task.payload.get("validation_plan_path"),
                "risk_review_path": task.payload.get("risk_review_path"),
                "gap_counts": decision.get("gap_counts", {}),
                "risk_counts": decision.get("risk_counts", {}),
                "breeding_design_card_audit": decision.get("breeding_design_card_audit", {}),
                "route_revision_intent": decision.get("route_revision_intent", {}),
                "evidence_gap_to_resolve": decision.get("evidence_gap_to_resolve", []),
                "new_hypothesis_direction": decision.get("new_hypothesis_direction", ""),
                "parent_hypothesis_id": decision.get("parent_hypothesis_id"),
                "do_not_repeat": decision.get("do_not_repeat", []),
                "review_gate": decision.get("review_gate"),
                "total_score": decision.get("total_score"),
            },
        )


async def _load_package(cfg, path: Any) -> dict[str, Any]:
    if not path:
        return {}
    try:
        package = await read_json(cfg, str(path))
    except Exception:
        return {}
    return package if isinstance(package, dict) else {}


def _extract_design_card_audit(hypothesis_artifact: dict[str, Any]) -> dict[str, Any]:
    record = hypothesis_artifact.get("record")
    candidates = []
    if isinstance(record, dict):
        candidates.append(record.get("breeding_design_card_audit"))
    candidates.append(hypothesis_artifact.get("breeding_design_card_audit"))
    for audit in candidates:
        if isinstance(audit, dict) and audit:
            return audit
    return {}


def _decide_iteration(
    *,
    hypothesis_id: str,
    review: Review | None,
    package: dict[str, Any],
    validation_plan: dict[str, Any] | None = None,
    risk_review: dict[str, Any] | None = None,
    design_card_audit: dict[str, Any] | None = None,
) -> dict[str, Any]:
    validation_plan = validation_plan or {}
    risk_review = risk_review or {}
    design_card_audit = design_card_audit or {}
    gaps = [gap for gap in package.get("evidence_gaps", []) if isinstance(gap, dict)]
    validation_gaps = [
        gap
        for gap in validation_plan.get("critical_evidence_gaps", [])
        if isinstance(gap, dict)
    ]
    all_gaps = [*gaps, *validation_gaps]
    severity_counts = Counter(str(gap.get("severity") or "unknown") for gap in all_gaps)
    type_counts = Counter(str(gap.get("type") or "unknown") for gap in all_gaps)
    risk_items = [risk for risk in risk_review.get("risk_items", []) if isinstance(risk, dict)]
    risk_severity_counts = Counter(
        str(risk.get("severity") or "unknown")
        for risk in risk_items
    )
    review_gate = _review_gate(review)
    contradiction_count = _count_contradictions(package)
    local_support_count = _count_local_support(package)
    scorecard = _build_scorecard(
        review=review,
        gaps=gaps,
        validation_plan=validation_plan,
        risk_review=risk_review,
        design_card_audit=design_card_audit,
        risk_severity_counts=risk_severity_counts,
        severity_counts=severity_counts,
        type_counts=type_counts,
        local_support_count=local_support_count,
        contradiction_count=contradiction_count,
    )
    total_score = _weighted_total(scorecard)

    reasons: list[str] = []
    action: IterationAction = "keep"

    if review is not None and review.verdict == "disproved":
        action = "reject"
        reasons.append("Review verdict is disproved.")
    elif contradiction_count > 0 and review_gate == "weak":
        action = "reject"
        reasons.append("Contradictory evidence is present and review scores are weak.")
    elif severity_counts["blocking"] > 0 or risk_severity_counts["blocking"] > 0:
        action = "pause"
        reasons.append("Blocking evidence or risk gaps require human or local confirmation.")
    elif review is not None and review.verdict in {"missing_piece", "other_more_likely"}:
        if _review_supports_prioritization(
            review=review,
            validation_plan=validation_plan,
            severity_counts=severity_counts,
            risk_severity_counts=risk_severity_counts,
            contradiction_count=contradiction_count,
        ):
            action = "keep"
            reasons.append(
                "Review found a resolvable preflight gap; retain the route for composite "
                "prioritization while keeping its validation gate explicit."
            )
        else:
            action = "revise"
            reasons.append(
                f"Review verdict is {review.verdict}; revise the route before composite prioritization."
            )
    elif severity_counts["high"] >= 2 or risk_severity_counts["high"] >= 3:
        action = "revise"
        reasons.append("Multiple high-severity evidence or risk gaps remain after DFRS.")
    elif local_support_count == 0 and gaps:
        action = "expand"
        reasons.append("DFRS found gaps but no strong local support; explore alternative routes.")
    elif review_gate == "weak":
        action = "revise"
        reasons.append("Review score gate is weak.")
    elif total_score < 70:
        action = "revise"
        reasons.append("Weighted iteration score is below the keep threshold.")
    elif _critical_design_gap_count(design_card_audit) >= 4:
        action = "revise"
        reasons.append("Breeding design card is missing several critical fields.")
    else:
        action = "keep"
        reasons.append("Evidence gaps are manageable and the hypothesis can enter prioritization.")

    if action in {"revise", "expand"} and "missing_local_germplasm_hits" in type_counts:
        reasons.append("Material route should be widened because local germplasm hits are missing.")
    if action in {"revise", "pause"} and "genotype_or_marker_validation" in type_counts:
        reasons.append("Marker or genotype validation must be carried into the next validation plan.")
    if design_card_audit.get("status") == "needs_attention":
        reasons.append("Breeding design card audit requires attention before this route is treated as mature.")

    route_revision_intent = _build_route_revision_intent(
        hypothesis_id=hypothesis_id,
        action=action,
        reasons=reasons,
        gaps=all_gaps,
        risk_items=risk_items,
        design_card_audit=design_card_audit,
        type_counts=type_counts,
    )

    return {
        "hypothesis_id": hypothesis_id,
        "action": action,
        "review_gate": review_gate,
        "route_revision_intent": route_revision_intent,
        "evidence_gap_to_resolve": route_revision_intent["evidence_gap_to_resolve"],
        "new_hypothesis_direction": route_revision_intent["new_hypothesis_direction"],
        "parent_hypothesis_id": hypothesis_id,
        "do_not_repeat": route_revision_intent["do_not_repeat"],
        "gap_counts": {
            "by_severity": dict(sorted(severity_counts.items())),
            "by_type": dict(sorted(type_counts.items())),
            "evidence_package": len(gaps),
            "validation_plan": len(validation_gaps),
        },
        "risk_counts": {
            "by_severity": dict(sorted(risk_severity_counts.items())),
            "total": len(risk_items),
        },
        "breeding_design_card_audit": _design_card_audit_summary(design_card_audit),
        "local_support_count": local_support_count,
        "contradiction_count": contradiction_count,
        "scorecard": scorecard,
        "total_score": total_score,
        "decision_thresholds": {
            "keep": (
                "score >= 70, or strong review plus a validation readiness score >= 50 "
                "with no blocking gap or contradiction; keep-ready still requires the "
                "higher termination score threshold"
            ),
            "revise": "score < 70 or high evidence gaps, but route remains salvageable",
            "expand": "local support is sparse and gaps suggest widening the route",
            "pause": "blocking gap requires human/local confirmation",
            "reject": "disproved or contradiction-dominated route",
        },
        "next_step_recommendation": _next_step_for(action),
        "reasons": reasons,
    }


def _build_route_revision_intent(
    *,
    hypothesis_id: str,
    action: IterationAction,
    reasons: list[str],
    gaps: list[dict[str, Any]],
    risk_items: list[dict[str, Any]],
    design_card_audit: dict[str, Any],
    type_counts: Counter[str],
) -> dict[str, Any]:
    prioritized_gaps = _prioritized_gap_messages(gaps)
    risk_focus = _prioritized_risk_messages(risk_items)
    missing_critical = [
        str(field)
        for field in design_card_audit.get("missing_critical_fields") or []
        if field
    ]
    evidence_gap_to_resolve = prioritized_gaps[:4] or risk_focus[:3] or reasons[:3]
    do_not_repeat = _do_not_repeat_guidance(
        action=action,
        type_counts=type_counts,
        missing_critical=missing_critical,
    )
    direction = _new_hypothesis_direction(
        action=action,
        type_counts=type_counts,
        missing_critical=missing_critical,
    )
    return {
        "parent_hypothesis_id": hypothesis_id,
        "action": action,
        "route_revision_intent": _intent_label(action),
        "evidence_gap_to_resolve": evidence_gap_to_resolve,
        "new_hypothesis_direction": direction,
        "do_not_repeat": do_not_repeat,
        "risk_focus": risk_focus[:4],
        "missing_design_card_fields": missing_critical[:8],
    }


def _prioritized_gap_messages(gaps: list[dict[str, Any]]) -> list[str]:
    severity_rank = {"blocking": 0, "high": 1, "medium": 2, "low": 3}
    ordered = sorted(
        gaps,
        key=lambda gap: (
            severity_rank.get(str(gap.get("severity") or "unknown"), 4),
            str(gap.get("type") or ""),
            str(gap.get("target") or ""),
        ),
    )
    messages: list[str] = []
    for gap in ordered:
        gap_type = str(gap.get("type") or "unknown")
        target = str(gap.get("target") or "").strip()
        message = str(gap.get("message") or gap.get("description") or "").strip()
        text = gap_type
        if target:
            text += f" on {target}"
        if message:
            text += f": {message}"
        if text not in messages:
            messages.append(text)
    return messages


def _prioritized_risk_messages(risk_items: list[dict[str, Any]]) -> list[str]:
    severity_rank = {"blocking": 0, "high": 1, "medium": 2, "low": 3}
    ordered = sorted(
        risk_items,
        key=lambda risk: (
            severity_rank.get(str(risk.get("severity") or "unknown"), 4),
            str(risk.get("category") or ""),
        ),
    )
    messages: list[str] = []
    for risk in ordered:
        category = str(risk.get("category") or "risk")
        message = str(risk.get("message") or risk.get("description") or "").strip()
        text = category if not message else f"{category}: {message}"
        if text not in messages:
            messages.append(text)
    return messages


def _do_not_repeat_guidance(
    *,
    action: IterationAction,
    type_counts: Counter[str],
    missing_critical: list[str],
) -> list[str]:
    guidance: list[str] = []
    if type_counts["genotype_or_marker_validation"]:
        guidance.append("Do not restate marker claims without a local validation route.")
    if type_counts["missing_local_germplasm_hits"] or type_counts["material_availability"]:
        guidance.append("Do not rely on unavailable or unconfirmed germplasm as the only route.")
    if type_counts["single_environment_evidence"]:
        guidance.append("Do not treat single-environment observations as deployment-ready evidence.")
    if missing_critical:
        guidance.append(
            "Do not omit critical breeding design fields: "
            + ", ".join(missing_critical[:5])
            + "."
        )
    if action == "expand":
        guidance.append("Do not generate a near-duplicate of the parent route.")
    return guidance or ["Do not ignore the parent decision's listed evidence gaps."]


def _new_hypothesis_direction(
    *,
    action: IterationAction,
    type_counts: Counter[str],
    missing_critical: list[str],
) -> str:
    if action == "revise":
        if type_counts["genotype_or_marker_validation"]:
            return "Revise the parent route around a locally testable marker/genotyping validation plan."
        if missing_critical:
            return "Revise the parent route into a complete breeding design card with explicit materials, validation, and fallback route."
        return "Revise the parent route while preserving its strongest evidence-supported mechanism."
    if action == "expand":
        if type_counts["missing_local_germplasm_hits"] or type_counts["material_availability"]:
            return "Expand toward alternative locally available germplasm or a substitute parent route."
        return "Expand toward a distinct mechanism, material, or validation route supported by the evidence graph."
    if action == "pause":
        return "Wait for local/advisor confirmation before generating a successor hypothesis."
    if action == "reject":
        return "Do not generate from this parent route unless new contradicting evidence is overturned."
    return "No successor hypothesis required; route can enter composite prioritization."


def _intent_label(action: IterationAction) -> str:
    return {
        "keep": "rank_without_successor",
        "revise": "repair_parent_route",
        "expand": "broaden_search_space",
        "pause": "await_confirmation",
        "reject": "terminate_route",
    }[action]


def _review_gate(review: Review | None) -> str:
    if review is None:
        return "missing"
    scores = review.scores
    values = [
        value
        for value in (scores.correctness, scores.feasibility, scores.testability)
        if value is not None
    ]
    if not values:
        return "missing"
    avg = sum(values) / len(values)
    if avg >= 0.7 and min(values) >= 0.5:
        return "strong"
    if avg >= 0.45 and min(values) >= 0.3:
        return "mixed"
    return "weak"


def _review_supports_prioritization(
    *,
    review: Review,
    validation_plan: dict[str, Any],
    severity_counts: Counter[str],
    risk_severity_counts: Counter[str],
    contradiction_count: int,
) -> bool:
    """Allow a strong, testable route into ranking without calling it deployment-ready."""

    if review.verdict != "missing_piece":
        return False
    if _review_gate(review) != "strong":
        return False
    if (
        contradiction_count > 0
        or severity_counts["blocking"] > 0
        or risk_severity_counts["blocking"] > 0
    ):
        return False
    readiness = _validation_readiness_score(validation_plan)
    return readiness is not None and readiness >= 50.0


def _count_local_support(package: dict[str, Any]) -> int:
    kg_package = package.get("local_crop_kg") or {}
    return (
        len((package.get("local_germplasm") or {}).get("results") or [])
        + len((kg_package.get("results")) or [])
        + len((package.get("local_rag") or {}).get("results") or [])
    )


def _count_contradictions(package: dict[str, Any]) -> int:
    return len(package.get("conflict_evidence") or package.get("conflicting_evidence") or [])


def _build_scorecard(
    *,
    review: Review | None,
    gaps: list[dict[str, Any]],
    validation_plan: dict[str, Any],
    risk_review: dict[str, Any],
    design_card_audit: dict[str, Any],
    risk_severity_counts: Counter[str],
    severity_counts: Counter[str],
    type_counts: Counter[str],
    local_support_count: int,
    contradiction_count: int,
) -> list[dict[str, Any]]:
    review_scores = _review_scores(review)
    correctness = _score_value(review_scores.get("correctness"), default=0.5)
    feasibility = _score_value(review_scores.get("feasibility"), default=0.5)
    testability = _score_value(review_scores.get("testability"), default=0.5)
    novelty = _score_value(review_scores.get("novelty"), default=0.5)

    evidence_support = max(0.0, min(100.0, local_support_count / 6 * 100 - contradiction_count * 25))
    review_strength = (correctness + feasibility + testability) / 3
    gap_burden = max(
        0.0,
        100.0
        - severity_counts["blocking"] * 60
        - severity_counts["high"] * 25
        - severity_counts["medium"] * 10
        - severity_counts["unknown"] * 5,
    )
    design_penalty = _design_card_penalty(design_card_audit)
    resource_readiness = max(
        0.0,
        _resource_readiness_score(local_support_count, type_counts) - design_penalty * 0.35,
    )
    validation_readiness = _validation_readiness_score(validation_plan)
    inferred_actionability = max(
        0.0,
        (testability * 0.65 + feasibility * 0.35)
        - type_counts["genotype_or_marker_validation"] * 15,
    )
    validation_actionability = (
        inferred_actionability
        if validation_readiness is None
        else max(0.0, min(100.0, inferred_actionability * 0.45 + validation_readiness * 0.55))
    )
    validation_actionability = max(0.0, validation_actionability - design_penalty * 0.50)
    inferred_risk_control = max(
        0.0,
        100.0
        - contradiction_count * 40
        - severity_counts["blocking"] * 30
        - sum(count for gap_type, count in type_counts.items() if "risk" in gap_type) * 20
        - risk_severity_counts["blocking"] * 35
        - risk_severity_counts["high"] * 12,
    )
    reviewed_risk_control = _risk_control_score(risk_review)
    risk_control = (
        inferred_risk_control
        if reviewed_risk_control is None
        else max(0.0, min(100.0, inferred_risk_control * 0.35 + reviewed_risk_control * 0.65))
    )
    risk_control = max(0.0, risk_control - design_penalty * 0.40)

    return [
        _score_row(
            "evidence_support",
            evidence_support,
            0.22,
            f"{local_support_count} local germplasm/KG/RAG hits; {contradiction_count} contradictions.",
        ),
        _score_row(
            "review_strength",
            review_strength,
            0.18,
            "Average of correctness, feasibility, and testability review scores.",
        ),
        _score_row(
            "local_resource_readiness",
            resource_readiness,
            0.15,
            _resource_readiness_rationale(design_penalty),
        ),
        _score_row(
            "validation_actionability",
            validation_actionability,
            0.15,
            _validation_actionability_rationale(validation_readiness, design_penalty),
        ),
        _score_row(
            "evidence_gap_burden",
            gap_burden,
            0.15,
            f"{len(gaps)} gaps after DFRS; lower score means heavier gap burden.",
        ),
        _score_row(
            "novelty",
            novelty,
            0.08,
            "Novelty score from the latest review, or neutral default when missing.",
        ),
        _score_row(
            "risk_control",
            risk_control,
            0.07,
            _risk_control_rationale(reviewed_risk_control, design_penalty),
        ),
    ]


def _resource_readiness_score(local_support_count: int, type_counts: Counter[str]) -> float:
    if type_counts["missing_local_germplasm_hits"] > 0:
        return 20.0
    if type_counts["material_availability"] > 0:
        return 55.0 if local_support_count else 30.0
    if local_support_count >= 2:
        return 85.0
    if local_support_count == 1:
        return 65.0
    return 35.0


def _design_card_audit_summary(audit: dict[str, Any]) -> dict[str, Any]:
    if not audit:
        return {}
    return {
        "status": audit.get("status"),
        "completeness_score": audit.get("completeness_score"),
        "missing_critical_fields": audit.get("missing_critical_fields") or [],
        "missing_fields": audit.get("missing_fields") or [],
        "penalty": _design_card_penalty(audit),
    }


def _design_card_penalty(audit: dict[str, Any]) -> float:
    if not audit:
        return 0.0
    missing_critical = _critical_design_gap_count(audit)
    missing_fields = len(audit.get("missing_fields") or [])
    completeness_gap = max(0.0, 80.0 - _audit_score(audit)) * 0.25
    penalty = missing_critical * 5.0 + max(0, missing_fields - missing_critical) * 1.0
    if audit.get("status") == "needs_attention":
        penalty += 4.0
    return round(min(35.0, penalty + completeness_gap), 2)


def _critical_design_gap_count(audit: dict[str, Any]) -> int:
    return len(audit.get("missing_critical_fields") or [])


def _audit_score(audit: dict[str, Any]) -> float:
    value = audit.get("completeness_score")
    try:
        return max(0.0, min(100.0, float(value)))
    except (TypeError, ValueError):
        return 100.0


def _validation_readiness_score(validation_plan: dict[str, Any]) -> float | None:
    value = validation_plan.get("validation_readiness_score")
    if value is None:
        return None
    try:
        return max(0.0, min(100.0, float(value)))
    except (TypeError, ValueError):
        return None


def _resource_readiness_rationale(design_penalty: float) -> str:
    rationale = "Readiness inferred from local support and material availability gaps."
    if design_penalty:
        rationale += f" Breeding design card incompleteness penalty applied ({design_penalty:.2f})."
    return rationale


def _validation_actionability_rationale(
    validation_readiness: float | None,
    design_penalty: float,
) -> str:
    if validation_readiness is None:
        rationale = "Testability/feasibility score penalized for marker or genotype validation gaps."
    else:
        rationale = (
            "Blend of review testability/feasibility and Validation Planner "
            f"readiness score ({validation_readiness:.2f})."
        )
    if design_penalty:
        rationale += f" Breeding design card incompleteness penalty applied ({design_penalty:.2f})."
    return rationale


def _risk_control_score(risk_review: dict[str, Any]) -> float | None:
    value = risk_review.get("risk_control_score")
    if value is None:
        return None
    try:
        return max(0.0, min(100.0, float(value)))
    except (TypeError, ValueError):
        return None


def _risk_control_rationale(
    reviewed_risk_control: float | None,
    design_penalty: float,
) -> str:
    if reviewed_risk_control is None:
        rationale = "Penalty for contradictions, blocking gaps, and explicit risk gap types."
    else:
        rationale = (
            "Blend of inferred contradiction/gap penalties and Risk Reviewer "
            f"risk_control_score ({reviewed_risk_control:.2f})."
        )
    if design_penalty:
        rationale += f" Breeding design card incompleteness penalty applied ({design_penalty:.2f})."
    return rationale


def _score_value(value: float | None, *, default: float) -> float:
    if value is None:
        return default * 100
    return max(0.0, min(100.0, float(value) * 100))


def _score_row(dimension: str, score: float, weight: float, rationale: str) -> dict[str, Any]:
    rounded_score = round(score, 2)
    return {
        "dimension": dimension,
        "score": rounded_score,
        "weight": weight,
        "weighted_score": round(rounded_score * weight, 2),
        "rationale": rationale,
    }


def _weighted_total(scorecard: list[dict[str, Any]]) -> float:
    return round(sum(float(row["weighted_score"]) for row in scorecard), 2)


def _review_scores(review: Review | None) -> dict[str, float | None]:
    if review is None:
        return {}
    return {
        "novelty": review.scores.novelty,
        "correctness": review.scores.correctness,
        "testability": review.scores.testability,
        "feasibility": review.scores.feasibility,
    }


def _next_step_for(action: str) -> str:
    if action == "keep":
        return "queue_pairwise_calibration"
    if action == "revise":
        return "generate_revised_hypothesis_from_decision"
    if action == "expand":
        return "generate_alternative_hypothesis_from_evidence_graph"
    if action == "pause":
        return "request_local_confirmation_or_advisor_review"
    if action == "reject":
        return "do_not_rank_or_expand_this_route"
    return "no_op"
