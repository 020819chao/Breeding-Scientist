"""Validation Planner agent - turns a hypothesis into a breeding validation plan.

V1 is deterministic and artifact-first. It reads the hypothesis record plus the
latest review, then writes a structured plan that downstream evidence curation,
risk review, and iteration scoring can consume.
"""

from __future__ import annotations

from datetime import UTC, datetime
from typing import Any

from ..models import Review, Task, TaskResult
from ..storage.artifacts import read_json, write_json
from ..storage.repos import hypotheses as hyp_repo
from ..storage.repos import reviews as rev_repo
from ..storage.repos import sessions as sess_repo
from .base import BaseAgent


class ValidationPlannerAgent(BaseAgent):
    """Build a concrete validation route for one breeding hypothesis."""

    name = "Validation Planner"

    async def execute(self, task: Task) -> TaskResult:
        if task.action != "PlanValidation":
            raise ValueError(f"ValidationPlannerAgent does not handle action {task.action!r}")
        if not task.target_id:
            raise ValueError("ValidationPlannerAgent.execute requires target_id")

        session = await sess_repo.fetch(self.deps.db, task.session_id)
        if session is None:
            raise RuntimeError(f"session {task.session_id} missing")
        hypothesis = await hyp_repo.fetch(self.deps.db, task.target_id)
        if hypothesis is None:
            raise RuntimeError(f"hypothesis {task.target_id} missing")

        reviews = await rev_repo.list_for_hypothesis(self.deps.db, hypothesis.id)
        latest_review = reviews[0] if reviews else None
        hypothesis_record = await _load_record(self.deps.cfg, hypothesis.artifact_path)
        breeding_context = _preferred_breeding_context(hypothesis_record)
        evidence_package = await _load_record(
            self.deps.cfg,
            task.payload.get("evidence_package_path"),
        )
        breeding_context = _enrich_breeding_context(breeding_context, evidence_package)
        plan = _build_validation_plan(
            session_id=session.id,
            task_id=task.id,
            hypothesis_id=hypothesis.id,
            hypothesis_title=hypothesis.title,
            research_goal=session.research_goal,
            breeding_context=breeding_context,
            hypothesis_text=hypothesis.full_text,
            review=latest_review,
            evidence_package_path=task.payload.get("evidence_package_path"),
            evidence_package=evidence_package,
        )
        plan_path = await write_json(
            self.deps.cfg,
            session.id,
            "validation",
            f"plan_{task.id}",
            plan,
        )
        return TaskResult(
            kind="validation_planned",
            hypothesis_ids=[hypothesis.id],
            extra={
                "validation_plan_path": plan_path,
                "evidence_package_path": task.payload.get("evidence_package_path"),
                "breeding_evidence_graph_path": task.payload.get(
                    "breeding_evidence_graph_path"
                ),
                "source": task.payload.get("source"),
                "validation_readiness_score": plan["validation_readiness_score"],
                "readiness_level": plan["readiness_level"],
                "critical_gap_count": len(plan["critical_evidence_gaps"]),
            },
        )


async def _load_record(cfg, artifact_path: str) -> dict[str, Any]:
    try:
        payload = await read_json(cfg, artifact_path)
    except Exception:
        return {}
    if isinstance(payload, dict) and isinstance(payload.get("record"), dict):
        return payload["record"]
    return payload if isinstance(payload, dict) else {}


def _enrich_breeding_context(
    breeding_context: dict[str, Any],
    evidence_package: dict[str, Any],
) -> dict[str, Any]:
    """Fill planning inputs from curated evidence without claiming validation."""
    context = dict(breeding_context)
    if not evidence_package:
        return context

    germplasm = _results(evidence_package.get("local_germplasm"))
    marker_qtl = _results(evidence_package.get("local_marker_qtl"))
    protocols = _results(evidence_package.get("local_phenotype_protocols"))
    trials = _results(evidence_package.get("local_field_trials"))
    kg = _results(evidence_package.get("local_crop_kg"))

    context["evidence_package_available"] = True
    context["evidence_candidate_materials"] = _unique(
        [
            f"{row.get('name')} ({row.get('accession_id')})"
            for row in germplasm
            if row.get("name") or row.get("accession_id")
        ]
        + [
            str(row.get("name") or row.get("id"))
            for row in kg
            if str(row.get("type") or "").lower() in {"material", "germplasm", "variety"}
            and (row.get("name") or row.get("id"))
        ]
    )
    context["evidence_candidate_genes_qtl"] = _unique(
        [
            part.strip()
            for row in marker_qtl
            for part in str(row.get("gene_or_qtl") or "").replace(";", ",").split(",")
            if part.strip()
        ]
        + [
            str(row.get("marker_name"))
            for row in marker_qtl
            if row.get("marker_name")
        ]
        + [
            str(row.get("name") or row.get("id"))
            for row in kg
            if str(row.get("type") or "").lower() in {"gene", "qtl", "marker"}
            and (row.get("name") or row.get("id"))
        ]
    )
    if not _list_value(context.get("candidate_genes_qtl")):
        context["candidate_genes_qtl"] = context["evidence_candidate_genes_qtl"][:6]

    protocol = _best_record(protocols, ("local_protocol_ready", "testing_seed_protocol", "local_note"))
    if _looks_unknown(_value(context, "phenotyping_plan")) and protocol:
        context["phenotyping_plan"] = _join_fields(
            protocol,
            ("measurement_method", "scale_or_unit", "stage", "replication"),
        )
    if _looks_unknown(_value(context, "decision_thresholds")) and protocol:
        context["decision_thresholds"] = _value(
            protocol,
            "decision_thresholds",
            default="advance only after the protocol's trait and penalty thresholds are met",
        )

    marker = _best_record(marker_qtl, ("validated", "local_validation", "needs_local_parent_preflight"))
    if _looks_unknown(_value(context, "genotyping_plan")) and marker:
        context["genotyping_plan"] = _join_fields(
            marker,
            ("marker_name", "marker_type", "assay_protocol", "validation_status"),
        )

    trial = _best_record(trials, ("completed", "decision", "pending_local_validation", "requires_replicated_trial"))
    if _looks_unknown(_value(context, "validation_trial_design")) and trial:
        context["validation_trial_design"] = _join_fields(
            trial,
            ("environment", "test_design", "materials", "phenotype_summary", "decision_outcome"),
        )

    if germplasm and _looks_unknown(_value(context, "material_availability")):
        context["material_availability"] = "Candidate materials identified in the local library; seed lot, identity, and permission remain to be confirmed."
        context["material_availability_evidence_pending"] = True
    if _looks_unknown(_value(context, "germplasm")) and context.get("evidence_candidate_materials"):
        context["germplasm"] = "; ".join(context["evidence_candidate_materials"][:6])
    context["evidence_protocol_count"] = len(protocols)
    context["evidence_trial_count"] = len(trials)
    context["evidence_marker_count"] = len(marker_qtl)
    return context


def _results(source: Any) -> list[dict[str, Any]]:
    if not isinstance(source, dict) or not isinstance(source.get("results"), list):
        return []
    return [item for item in source["results"] if isinstance(item, dict)]


def _unique(values: list[str]) -> list[str]:
    out: list[str] = []
    seen: set[str] = set()
    for value in values:
        text = str(value).strip()
        if text and text.lower() not in seen:
            seen.add(text.lower())
            out.append(text)
    return out


def _best_record(records: list[dict[str, Any]], statuses: tuple[str, ...]) -> dict[str, Any]:
    if not records:
        return {}
    for status in statuses:
        for record in records:
            value = str(record.get("validation_status") or record.get("decision_outcome") or "").lower()
            if status in value:
                return record
    return records[0]


def _join_fields(record: dict[str, Any], fields: tuple[str, ...]) -> str:
    parts = [str(record.get(field)).strip() for field in fields if str(record.get(field) or "").strip()]
    return "; ".join(parts)


def _preferred_breeding_context(record: dict[str, Any]) -> dict[str, Any]:
    for key in ("breeding_context_zh", "breeding_context", "breeding_context_en"):
        value = record.get(key)
        if isinstance(value, dict) and value:
            return value
    return {}


def _build_validation_plan(
    *,
    session_id: str,
    task_id: str,
    hypothesis_id: str,
    hypothesis_title: str,
    research_goal: str,
    breeding_context: dict[str, Any],
    hypothesis_text: str,
    review: Review | None,
    evidence_package_path: Any = None,
    evidence_package: dict[str, Any] | None = None,
) -> dict[str, Any]:
    gaps = _critical_gaps(breeding_context, review, hypothesis_text)
    readiness_score = _validation_readiness_score(breeding_context, review, gaps)
    crop = _value(breeding_context, "crop", default="target crop")
    trait = _value(breeding_context, "target_trait", default="target trait")
    donor = _value(breeding_context, "donor_parent", default="candidate donor or accession")
    recurrent = _value(
        breeding_context,
        "recurrent_parent",
        default="elite recurrent parent or target breeding background",
    )
    tpe = _value(
        breeding_context,
        "target_population_of_environments",
        default="target production environments",
    )
    genes = _list_value(breeding_context.get("candidate_genes_qtl"))
    markers = ", ".join(genes) if genes else "candidate marker/gene/QTL set"
    phenotyping_hint = _value(
        breeding_context,
        "phenotyping_plan",
        default=f"measure {trait} with field-ready protocols",
    )
    genotyping_hint = _value(
        breeding_context,
        "genotyping_plan",
        default=f"validate {markers} in donor, recurrent parent, and segregating progeny",
    )
    thresholds = _value(
        breeding_context,
        "decision_thresholds",
        default="advance only if trait gain is repeatable and no major agronomic penalty appears",
    )

    return {
        "version": 1,
        "agent": "validation_planner",
        "session_id": session_id,
        "task_id": task_id,
        "hypothesis_id": hypothesis_id,
        "hypothesis_title": hypothesis_title,
        "created_at": datetime.now(UTC).isoformat(),
        "research_goal": research_goal,
        "evidence_package_path": evidence_package_path,
        "evidence_basis": _evidence_basis(evidence_package or {}, breeding_context),
        "validation_readiness_score": readiness_score,
        "readiness_level": _readiness_level(readiness_score, gaps),
        "breeding_goal": {
            "crop": crop,
            "target_trait": trait,
            "target_environment": tpe,
            "donor_parent": donor,
            "recurrent_parent": recurrent,
            "candidate_genes_qtl_markers": genes,
        },
        "materials_plan": {
            "required_materials": [donor, recurrent, "segregating progeny or validation panel"],
            "controls": [
                recurrent,
                "known susceptible or baseline control",
                "locally adapted check variety",
            ],
            "availability_check": _value(
                breeding_context,
                "material_availability",
                default="confirm seed inventory, accession identity, and use permission",
            ),
            "candidate_materials_from_evidence": _list_value(
                breeding_context.get("evidence_candidate_materials")
            ),
            "minimum_population": "at least 80-120 segregants or a small validation panel in V1",
        },
        "genotyping_plan": {
            "objective": f"Confirm whether the proposed route is genetically trackable through {markers}.",
            "targets": genes,
            "assay": genotyping_hint,
            "samples": [donor, recurrent, "F1/BC1F1/F2 or candidate lines"],
            "go_no_go": "pause if donor/recurrent polymorphism or marker-trait direction cannot be confirmed",
        },
        "phenotyping_plan": {
            "objective": f"Measure whether {trait} changes in the expected direction.",
            "protocol": phenotyping_hint,
            "timepoints": ["key growth stage", "stress or dense-planting window", "harvest"],
            "quality_control": [
                "include replicated checks",
                "record stand density and management covariates",
                "separate target trait from yield or maturity penalties",
            ],
        },
        "field_trial_design": {
            "population": _value(
                breeding_context,
                "germplasm",
                default="candidate donor x recurrent parent progeny or validation panel",
            ),
            "environment": tpe,
            "design": _value(
                breeding_context,
                "validation_trial_design",
                default="randomized complete block or augmented design depending on seed amount",
            ),
            "replication": "2-3 replicates when seed allows; otherwise use a preflight nursery",
            "decision_thresholds": thresholds,
        },
        "cost_cycle_estimate": {
            "first_decisive_evidence": _value(
                breeding_context,
                "cycle_time_estimate",
                default="one controlled genotyping preflight plus one field season",
            ),
            "cost_tier": _cost_tier(breeding_context, gaps),
            "bottlenecks": _bottlenecks(breeding_context, gaps),
        },
        "risk_controls": _risk_controls(breeding_context, gaps),
        "critical_evidence_gaps": gaps,
        "gap_to_validation_action": _gap_action_map(gaps),
        "next_agent_requests": {
            "evidence_curator_focus": _curator_focus(trait, donor, recurrent, genes, gaps),
            "risk_reviewer_focus": "review GxE, material identity, marker transferability, and yield/quality tradeoffs",
            "iteration_orchestrator_focus": "use validation_readiness_score and blocking gaps when scoring validation_actionability",
        },
    }


def _critical_gaps(
    breeding_context: dict[str, Any],
    review: Review | None,
    hypothesis_text: str,
) -> list[dict[str, str]]:
    gaps: list[dict[str, str]] = []
    for item in _list_value(breeding_context.get("evidence_gaps")):
        gaps.append({"type": _gap_type(item), "severity": _gap_severity(item), "message": item})

    if _looks_unknown(_value(breeding_context, "material_availability")):
        gaps.append(
            {
                "type": "material_availability",
                "severity": "medium" if breeding_context.get("evidence_candidate_materials") else "high",
                "message": "Named donor/recurrent materials need local availability confirmation.",
            }
        )
    if not _list_value(breeding_context.get("candidate_genes_qtl")):
        gaps.append(
            {
                "type": "marker_or_qtl_specificity",
                "severity": "medium",
                "message": "Candidate gene/QTL/marker route is not yet specific.",
            }
        )
    if _looks_unknown(_value(breeding_context, "validation_trial_design")):
        gaps.append(
            {
                "type": "trial_design_specificity",
                "severity": "medium",
                "message": "Validation trial design needs population, environment, and decision thresholds.",
            }
        )
    if review is not None and review.verdict in {"missing_piece", "other_more_likely"}:
        gaps.append(
            {
                "type": "review_missing_piece",
                "severity": "high",
                "message": f"Latest review verdict is {review.verdict}.",
            }
        )
    if "validation" in hypothesis_text.lower() and not gaps:
        gaps.append(
            {
                "type": "local_validation_confirmation",
                "severity": "medium",
                "message": "Hypothesis text mentions validation; keep local confirmation explicit.",
            }
        )
    return _dedupe_gaps(gaps)


def _validation_readiness_score(
    breeding_context: dict[str, Any],
    review: Review | None,
    gaps: list[dict[str, str]],
) -> float:
    score = 45.0
    if not _looks_unknown(_value(breeding_context, "material_availability")):
        score += 12
    if _list_value(breeding_context.get("candidate_genes_qtl")):
        score += 12
    if not _looks_unknown(_value(breeding_context, "phenotyping_plan")):
        score += 10
    if not _looks_unknown(_value(breeding_context, "genotyping_plan")):
        score += 8
    if not _looks_unknown(_value(breeding_context, "validation_trial_design")):
        score += 10
    if review is not None:
        if review.scores.testability is not None:
            score += (review.scores.testability - 0.5) * 18
        if review.scores.feasibility is not None:
            score += (review.scores.feasibility - 0.5) * 14

    if breeding_context.get("evidence_candidate_materials"):
        score += 5
    if breeding_context.get("evidence_protocol_count"):
        score += 3
    if breeding_context.get("evidence_trial_count"):
        score += 3

    counts = {severity: sum(1 for gap in gaps if gap.get("severity") == severity) for severity in ("blocking", "high", "medium", "low")}
    score -= min(28, counts["blocking"] * 28)
    score -= min(24, counts["high"] * 12)
    score -= min(24, counts["medium"] * 6)
    score -= min(12, counts["low"] * 3)
    return round(max(0.0, min(100.0, score)), 2)


def _evidence_basis(package: dict[str, Any], context: dict[str, Any]) -> dict[str, Any]:
    return {
        "germplasm_hits": len(_results(package.get("local_germplasm"))),
        "kg_hits": len(_results(package.get("local_crop_kg"))),
        "rag_hits": len(_results(package.get("local_rag"))),
        "marker_qtl_hits": len(_results(package.get("local_marker_qtl"))),
        "phenotype_protocol_hits": len(_results(package.get("local_phenotype_protocols"))),
        "field_trial_hits": len(_results(package.get("local_field_trials"))),
        "candidate_materials": _list_value(context.get("evidence_candidate_materials")),
        "candidate_genes_qtl_markers": _list_value(context.get("candidate_genes_qtl")),
        "boundary": "Local hits support a preflight plan; they do not prove local availability, marker transferability, or field performance.",
    }


def _readiness_level(score: float, gaps: list[dict[str, str]]) -> str:
    if any(gap.get("severity") == "blocking" for gap in gaps):
        return "blocked"
    if score >= 75:
        return "ready"
    if score >= 55:
        return "needs_preflight"
    return "weak"


def _risk_controls(breeding_context: dict[str, Any], gaps: list[dict[str, str]]) -> list[dict[str, str]]:
    risks = _list_value(breeding_context.get("risks_tradeoffs"))
    controls = [
        {
            "risk": risk,
            "control": "turn this into an explicit go/no-go observation in the first validation cycle",
        }
        for risk in risks
    ]
    if any(gap.get("type") == "material_availability" for gap in gaps):
        controls.append(
            {
                "risk": "material identity or availability uncertainty",
                "control": "confirm seed lot, accession identity, and parent polymorphism before field expansion",
            }
        )
    if not controls:
        controls.append(
            {
                "risk": "unobserved GxE or agronomic penalty",
                "control": "include local checks and measure yield, maturity, and plant architecture covariates",
            }
        )
    return controls


def _gap_action_map(gaps: list[dict[str, str]]) -> list[dict[str, str]]:
    actions = []
    for gap in gaps:
        gap_type = gap.get("type", "unknown")
        if "material" in gap_type:
            action = "verify donor/recurrent seed availability and identity"
        elif "marker" in gap_type or "qtl" in gap_type or "genotype" in gap_type:
            action = "run marker polymorphism and segregation preflight"
        elif "trial" in gap_type or "phenotyp" in gap_type:
            action = "define field layout, measurements, controls, and decision thresholds"
        else:
            action = "request focused evidence curation and advisor confirmation"
        actions.append({"gap_type": gap_type, "validation_action": action})
    return actions


def _curator_focus(
    trait: str,
    donor: str,
    recurrent: str,
    genes: list[str],
    gaps: list[dict[str, str]],
) -> str:
    pieces = [trait, donor, recurrent, " ".join(genes)]
    pieces.extend(gap.get("message", "") for gap in gaps[:4])
    return " ".join(piece for piece in pieces if piece).strip()


def _cost_tier(breeding_context: dict[str, Any], gaps: list[dict[str, str]]) -> str:
    text = " ".join(
        [
            _value(breeding_context, "phenotyping_plan"),
            _value(breeding_context, "genotyping_plan"),
            " ".join(gap.get("message", "") for gap in gaps),
        ]
    ).lower()
    if any(token in text for token in ("sequencing", "multi-environment", "multi environment")):
        return "medium_high"
    if any(token in text for token in ("marker", "caps", "kasp", "snp")):
        return "medium"
    return "low_medium"


def _bottlenecks(breeding_context: dict[str, Any], gaps: list[dict[str, str]]) -> list[str]:
    bottlenecks = []
    if _looks_unknown(_value(breeding_context, "material_availability")):
        bottlenecks.append("material availability and seed amount")
    if any("marker" in gap.get("type", "") for gap in gaps):
        bottlenecks.append("marker transferability and polymorphism")
    if any("trial" in gap.get("type", "") for gap in gaps):
        bottlenecks.append("field design specificity")
    return bottlenecks or ["field season timing and replicated phenotyping capacity"]


def _value(ctx: dict[str, Any], key: str, *, default: str = "") -> str:
    value = ctx.get(key)
    if isinstance(value, list):
        return ", ".join(str(item) for item in value if str(item).strip()) or default
    text = str(value or "").strip()
    return text or default


def _list_value(value: Any) -> list[str]:
    if isinstance(value, list):
        return [str(item).strip() for item in value if str(item).strip()]
    if isinstance(value, str) and value.strip():
        return [part.strip() for part in value.replace(";", ",").split(",") if part.strip()]
    return []


def _looks_unknown(value: str) -> bool:
    text = value.strip().lower()
    if not text:
        return True
    return (
        text in {"unknown", "not specified", "none", "n/a", "na"}
        or any(token in text for token in ("unknown", "pending", "unconfirmed", "to be confirmed"))
    )


def _gap_type(message: str) -> str:
    lower = message.lower()
    if any(token in lower for token in ("material", "seed", "donor", "accession", "parent")):
        return "material_availability"
    if any(token in lower for token in ("marker", "qtl", "gene", "genotyp", "caps", "kasp", "snp")):
        return "genotype_or_marker_validation"
    if any(token in lower for token in ("field", "trial", "environment", "phenotyp")):
        return "field_or_phenotype_validation"
    if any(token in lower for token in ("risk", "tradeoff", "yield", "gxe", "g x e")):
        return "risk_or_tradeoff"
    return "general_evidence_gap"


def _gap_severity(message: str) -> str:
    lower = message.lower()
    if any(token in lower for token in ("contradict", "disproved", "failed", "unavailable", "blocking")):
        return "blocking"
    if any(token in lower for token in ("pending", "needs", "requires", "confirm", "validation", "preflight", "missing")):
        return "medium"
    return "high"


def _dedupe_gaps(gaps: list[dict[str, str]]) -> list[dict[str, str]]:
    seen: set[tuple[str, str]] = set()
    out: list[dict[str, str]] = []
    for gap in gaps:
        key = (gap.get("type", ""), gap.get("message", "").lower())
        if key in seen:
            continue
        seen.add(key)
        out.append(gap)
    return out
