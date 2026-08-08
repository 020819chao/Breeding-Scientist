"""Risk Reviewer agent - structured breeding-risk assessment.

V1 is deterministic and artifact-first. It consolidates risks from the
hypothesis record, validation plan, DFRS evidence package, and latest review so
the iteration layer can make a risk-aware decision.
"""

from __future__ import annotations

from collections import Counter
from datetime import UTC, datetime
from typing import Any

from ..models import Review, Task, TaskResult
from ..storage.artifacts import read_json, write_json
from ..storage.repos import hypotheses as hyp_repo
from ..storage.repos import reviews as rev_repo
from ..storage.repos import sessions as sess_repo
from .base import BaseAgent


class RiskReviewerAgent(BaseAgent):
    """Assess breeding risks for a reviewed and evidence-curated hypothesis."""

    name = "Risk Reviewer"

    async def execute(self, task: Task) -> TaskResult:
        if task.action != "ReviewRisk":
            raise ValueError(f"RiskReviewerAgent does not handle action {task.action!r}")
        if not task.target_id:
            raise ValueError("RiskReviewerAgent.execute requires target_id")

        session = await sess_repo.fetch(self.deps.db, task.session_id)
        if session is None:
            raise RuntimeError(f"session {task.session_id} missing")
        hypothesis = await hyp_repo.fetch(self.deps.db, task.target_id)
        if hypothesis is None:
            raise RuntimeError(f"hypothesis {task.target_id} missing")

        reviews = await rev_repo.list_for_hypothesis(self.deps.db, hypothesis.id)
        latest_review = reviews[0] if reviews else None
        hypothesis_record = await _load_artifact(self.deps.cfg, hypothesis.artifact_path)
        package = await _load_artifact(self.deps.cfg, task.payload.get("evidence_package_path"))
        validation_plan = await _load_artifact(self.deps.cfg, task.payload.get("validation_plan_path"))
        breeding_context = _preferred_breeding_context(hypothesis_record)
        risk_review = _build_risk_review(
            session_id=session.id,
            task_id=task.id,
            hypothesis_id=hypothesis.id,
            hypothesis_title=hypothesis.title,
            research_goal=session.research_goal,
            breeding_context=breeding_context,
            package=package,
            validation_plan=validation_plan,
            review=latest_review,
        )
        risk_review_path = await write_json(
            self.deps.cfg,
            session.id,
            "risk",
            f"review_{task.id}",
            risk_review,
        )
        return TaskResult(
            kind="risk_reviewed",
            hypothesis_ids=[hypothesis.id],
            extra={
                "risk_review_path": risk_review_path,
                "risk_control_score": risk_review["risk_control_score"],
                "risk_level": risk_review["risk_level"],
                "blocking_risk_count": risk_review["risk_counts"]["by_severity"].get("blocking", 0),
                "high_risk_count": risk_review["risk_counts"]["by_severity"].get("high", 0),
                "evidence_package_path": task.payload.get("evidence_package_path"),
                "breeding_evidence_graph_path": task.payload.get("breeding_evidence_graph_path"),
                "validation_plan_path": task.payload.get("validation_plan_path"),
            },
        )


async def _load_artifact(cfg, path: Any) -> dict[str, Any]:
    if not path:
        return {}
    try:
        payload = await read_json(cfg, str(path))
    except Exception:
        return {}
    if isinstance(payload, dict) and isinstance(payload.get("record"), dict):
        return payload["record"]
    return payload if isinstance(payload, dict) else {}


def _preferred_breeding_context(record: dict[str, Any]) -> dict[str, Any]:
    for key in ("breeding_context_zh", "breeding_context", "breeding_context_en"):
        value = record.get(key)
        if isinstance(value, dict) and value:
            return value
    return {}


def _build_risk_review(
    *,
    session_id: str,
    task_id: str,
    hypothesis_id: str,
    hypothesis_title: str,
    research_goal: str,
    breeding_context: dict[str, Any],
    package: dict[str, Any],
    validation_plan: dict[str, Any],
    review: Review | None,
) -> dict[str, Any]:
    risks = _dedupe_risks(
        [
            *_risks_from_breeding_context(breeding_context),
            *_risks_from_validation_plan(validation_plan),
            *_risks_from_evidence_package(package),
            *_risks_from_review(review),
        ]
    )
    if not risks:
        risks.append(
            _risk(
                category="gxe",
                severity="medium",
                message="GxE stability and agronomic tradeoffs remain unobserved until field validation.",
                source="risk_reviewer_default",
                mitigation="Keep local checks and multi-environment or staged validation in the next cycle.",
            )
        )
    severity_counts = Counter(str(risk["severity"]) for risk in risks)
    category_counts = Counter(str(risk["category"]) for risk in risks)
    risk_control_score = _risk_control_score(severity_counts)
    return {
        "version": 1,
        "agent": "risk_reviewer",
        "session_id": session_id,
        "task_id": task_id,
        "hypothesis_id": hypothesis_id,
        "hypothesis_title": hypothesis_title,
        "created_at": datetime.now(UTC).isoformat(),
        "research_goal": research_goal,
        "risk_level": _risk_level(risk_control_score, severity_counts),
        "risk_control_score": risk_control_score,
        "risk_counts": {
            "by_severity": dict(sorted(severity_counts.items())),
            "by_category": dict(sorted(category_counts.items())),
        },
        "risk_items": risks,
        "must_resolve_before_prioritization": [
            risk
            for risk in risks
            if risk["severity"] == "blocking"
            or (
                risk["severity"] == "high"
                and risk["category"] in {"material", "genetic", "validation"}
            )
        ],
        "risk_to_validation_action": _risk_action_map(risks),
        "next_agent_requests": {
            "iteration_orchestrator_focus": (
                "blend risk_control_score into risk_control and pause if blocking risks remain"
            ),
            "validation_planner_focus": (
                "turn high material/genetic/validation risks into explicit go/no-go checks"
            ),
            "evidence_curator_focus": _evidence_focus_from_risks(risks),
        },
    }


def _risks_from_breeding_context(ctx: dict[str, Any]) -> list[dict[str, str]]:
    risks = []
    for item in _list_value(ctx.get("risks_tradeoffs")):
        risks.append(
            _risk(
                category=_risk_category(item),
                severity=_risk_severity(item, default="medium"),
                message=item,
                source="hypothesis_breeding_context",
                mitigation=_mitigation_for(_risk_category(item)),
            )
        )
    material = _value(ctx, "material_availability")
    if _looks_unknown(material) or "pending" in material.lower():
        risks.append(
            _risk(
                category="material",
                severity="high",
                message="Material availability or identity is not yet confirmed locally.",
                source="hypothesis_breeding_context",
                mitigation="Confirm seed inventory, accession identity, and use permission before expansion.",
            )
        )
    return risks


def _risks_from_validation_plan(plan: dict[str, Any]) -> list[dict[str, str]]:
    risks = []
    for control in plan.get("risk_controls") or []:
        if not isinstance(control, dict):
            continue
        message = str(control.get("risk") or "").strip()
        if not message:
            continue
        risks.append(
            _risk(
                category=_risk_category(message),
                severity=_risk_severity(message, default="medium"),
                message=message,
                source="validation_plan",
                mitigation=str(control.get("control") or _mitigation_for(_risk_category(message))),
            )
        )
    for gap in plan.get("critical_evidence_gaps") or []:
        if not isinstance(gap, dict):
            continue
        gap_type = str(gap.get("type") or "validation")
        message = str(gap.get("message") or gap_type)
        risks.append(
            _risk(
                category=_category_from_gap_type(gap_type),
                severity=_severity_from_gap(gap),
                message=message,
                source="validation_plan_gap",
                mitigation=_mitigation_for(_category_from_gap_type(gap_type)),
            )
        )
    return risks


def _risks_from_evidence_package(package: dict[str, Any]) -> list[dict[str, str]]:
    risks = []
    for gap in package.get("evidence_gaps") or []:
        if not isinstance(gap, dict):
            continue
        gap_type = str(gap.get("type") or "evidence")
        category = _category_from_gap_type(gap_type)
        risks.append(
            _risk(
                category=category,
                severity=_severity_from_gap(gap),
                message=str(gap.get("message") or gap_type),
                source="evidence_package_gap",
                mitigation=_mitigation_for(category),
            )
        )
    contradictions = package.get("conflict_evidence") or package.get("conflicting_evidence") or []
    for item in contradictions:
        message = str(item.get("message") if isinstance(item, dict) else item)
        risks.append(
            _risk(
                category="evidence",
                severity="high",
                message=message or "Contradictory evidence remains in the DFRS package.",
                source="evidence_package_conflict",
                mitigation=(
                    "Resolve contradiction before composite prioritization or "
                    "deployment-oriented planning."
                ),
            )
        )
    return risks


def _risks_from_review(review: Review | None) -> list[dict[str, str]]:
    if review is None:
        return []
    risks = []
    if review.verdict == "disproved":
        risks.append(
            _risk(
                category="evidence",
                severity="blocking",
                message="Latest review verdict is disproved.",
                source="risk_review",
                mitigation="Reject or rebuild the hypothesis before further prioritization.",
            )
        )
    elif review.verdict in {"missing_piece", "other_more_likely"}:
        risks.append(
            _risk(
                category="evidence",
                severity="high",
                message=f"Latest review verdict is {review.verdict}.",
                source="risk_review",
                mitigation="Revise the route and request targeted evidence before prioritization.",
            )
        )
    scores = review.scores
    if scores.feasibility is not None and scores.feasibility < 0.45:
        risks.append(
            _risk(
                category="validation",
                severity="high",
                message="Review feasibility score is below 0.45.",
                source="risk_review",
                mitigation="Reduce validation scope or confirm materials and protocol feasibility.",
            )
        )
    if scores.testability is not None and scores.testability < 0.45:
        risks.append(
            _risk(
                category="validation",
                severity="high",
                message="Review testability score is below 0.45.",
                source="risk_review",
                mitigation="Define a clearer phenotype/genotype go-no-go assay.",
            )
        )
    return risks


def _risk(
    *,
    category: str,
    severity: str,
    message: str,
    source: str,
    mitigation: str,
) -> dict[str, str]:
    return {
        "category": category,
        "severity": severity,
        "message": message,
        "source": source,
        "mitigation": mitigation,
    }


def _risk_control_score(severity_counts: Counter[str]) -> float:
    score = (
        100.0
        - severity_counts["blocking"] * 45
        - severity_counts["high"] * 18
        - severity_counts["medium"] * 8
        - severity_counts["low"] * 3
        - severity_counts["unknown"] * 5
    )
    return round(max(0.0, min(100.0, score)), 2)


def _risk_level(score: float, severity_counts: Counter[str]) -> str:
    if severity_counts["blocking"] > 0:
        return "blocked"
    if severity_counts["high"] >= 2 or score < 45:
        return "high"
    if score < 70:
        return "moderate"
    return "controlled"


def _risk_action_map(risks: list[dict[str, str]]) -> list[dict[str, str]]:
    return [
        {
            "category": risk["category"],
            "severity": risk["severity"],
            "validation_action": _mitigation_for(risk["category"]),
        }
        for risk in risks
    ]


def _evidence_focus_from_risks(risks: list[dict[str, str]]) -> str:
    return " ".join(
        risk["message"]
        for risk in risks
        if risk["severity"] in {"blocking", "high"}
    )[:2000]


def _dedupe_risks(risks: list[dict[str, str]]) -> list[dict[str, str]]:
    seen: set[tuple[str, str]] = set()
    out = []
    for risk in risks:
        key = (risk.get("category", ""), risk.get("message", "").strip().lower())
        if key in seen:
            continue
        seen.add(key)
        out.append(risk)
    return out


def _category_from_gap_type(gap_type: str) -> str:
    lower = gap_type.lower()
    if "material" in lower or "germplasm" in lower:
        return "material"
    if any(token in lower for token in ("marker", "qtl", "gene", "genotype")):
        return "genetic"
    if any(token in lower for token in ("phenotype", "trial", "validation")):
        return "validation"
    if "risk" in lower:
        return "deployment"
    return "evidence"


def _risk_category(text: str) -> str:
    lower = text.lower()
    if any(token in lower for token in ("material", "seed", "accession", "parent", "donor")):
        return "material"
    if any(token in lower for token in ("marker", "qtl", "gene", "genotyp", "linkage")):
        return "genetic"
    if any(token in lower for token in ("phenotyp", "trial", "measurement", "cost", "cycle")):
        return "validation"
    if any(token in lower for token in ("gxe", "g x e", "environment", "stability")):
        return "gxe"
    if any(token in lower for token in ("yield", "quality", "tradeoff", "penalty")):
        return "tradeoff"
    return "deployment"


def _risk_severity(text: str, *, default: str) -> str:
    lower = text.lower()
    if any(token in lower for token in ("block", "disproved", "cannot", "unavailable")):
        return "blocking"
    if any(token in lower for token in ("high", "penalty", "not confirmed", "pending", "missing")):
        return "high"
    if any(token in lower for token in ("low", "minor")):
        return "low"
    return default


def _severity_from_gap(gap: dict[str, Any]) -> str:
    severity = str(gap.get("severity") or "medium").lower()
    if severity in {"blocking", "high", "medium", "low"}:
        return severity
    return "medium"


def _mitigation_for(category: str) -> str:
    return {
        "material": "confirm material identity, availability, seed amount, and crossing permission",
        "genetic": "run marker polymorphism, segregation, and background-dependence checks",
        "validation": "turn the risk into a preflight assay with explicit go/no-go thresholds",
        "gxe": "validate under target environments with local checks and management covariates",
        "tradeoff": "measure yield, quality, maturity, and architecture alongside the target trait",
        "deployment": "define target ecology, adoption constraints, and fallback deployment route",
        "evidence": "request focused evidence curation and advisor confirmation",
    }.get(category, "request focused evidence curation and advisor confirmation")


def _value(ctx: dict[str, Any], key: str) -> str:
    value = ctx.get(key)
    if isinstance(value, list):
        return ", ".join(str(item) for item in value if str(item).strip())
    return str(value or "").strip()


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
    return text in {"unknown", "not specified", "none", "n/a", "na"} or "unknown" in text
