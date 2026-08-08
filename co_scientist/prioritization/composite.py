"""Composite breeding rank shared by web display and system selection."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from ..config import Config


def latest_iteration_decisions_for_session(
    cfg: Config,
    session_id: str,
) -> dict[str, dict[str, Any]]:
    base = cfg.data_dir.resolve()
    iteration_dir = cfg.data_dir / "artifacts" / session_id / "iteration"
    try:
        resolved_dir = iteration_dir.resolve()
        resolved_dir.relative_to(base)
    except (ValueError, OSError):
        return {}
    if not resolved_dir.is_dir():
        return {}

    latest: dict[str, dict[str, Any]] = {}
    for path in sorted(resolved_dir.glob("decision_*.json")):
        try:
            resolved_path = path.resolve()
            resolved_path.relative_to(resolved_dir)
            payload = json.loads(resolved_path.read_text(encoding="utf-8"))
        except (ValueError, OSError, json.JSONDecodeError):
            continue
        if not isinstance(payload, dict) or not payload.get("hypothesis_id"):
            continue
        hypothesis_id = str(payload["hypothesis_id"])
        item = iteration_decision_summary(payload)
        item["decision_path"] = resolved_path.relative_to(cfg.data_dir).as_posix()
        current = latest.get(hypothesis_id)
        if current is None or str(item.get("created_at") or "") > str(current.get("created_at") or ""):
            latest[hypothesis_id] = item
    return latest


def iteration_decision_summary(payload: dict[str, Any]) -> dict[str, Any]:
    reasons = [str(reason) for reason in payload.get("reasons") or [] if reason]
    package_path = payload.get("evidence_package_path")
    score = payload.get("total_score")
    design_audit = design_card_audit_summary(payload.get("breeding_design_card_audit"))
    route_revision_intent = (
        payload.get("route_revision_intent")
        if isinstance(payload.get("route_revision_intent"), dict)
        else {}
    )
    return {
        "hypothesis_id": str(payload.get("hypothesis_id") or ""),
        "action": str(payload.get("action") or "pending"),
        "total_score": score if isinstance(score, int | float) else None,
        "scorecard": payload.get("scorecard") if isinstance(payload.get("scorecard"), list) else [],
        "breeding_design_card_audit": design_audit,
        "route_revision_intent": route_revision_intent,
        "new_hypothesis_direction": str(
            payload.get("new_hypothesis_direction")
            or route_revision_intent.get("new_hypothesis_direction")
            or ""
        ),
        "evidence_gap_to_resolve": [
            str(item)
            for item in (
                payload.get("evidence_gap_to_resolve")
                or route_revision_intent.get("evidence_gap_to_resolve")
                or []
            )
            if item
        ],
        "do_not_repeat": [
            str(item)
                for item in (
                    payload.get("do_not_repeat")
                    or route_revision_intent.get("do_not_repeat")
                    or []
                )
            if item
        ],
        "review_gate": payload.get("review_gate"),
        "next_step_recommendation": payload.get("next_step_recommendation"),
        "created_at": payload.get("created_at"),
        "reason_summary": reasons[0] if reasons else "",
        "evidence_package_path": Path(package_path).as_posix() if isinstance(package_path, str) else "",
        "has_evidence_package": isinstance(package_path, str) and bool(package_path),
        "validation_plan_path": (
            Path(payload["validation_plan_path"]).as_posix()
            if isinstance(payload.get("validation_plan_path"), str)
            else ""
        ),
        "risk_review_path": (
            Path(payload["risk_review_path"]).as_posix()
            if isinstance(payload.get("risk_review_path"), str)
            else ""
        ),
    }


def iteration_audit_summary(decisions: dict[str, dict[str, Any]]) -> dict[str, Any]:
    action_counts = {
        action: 0
        for action in ("keep", "revise", "expand", "pause", "reject", "pending")
    }
    scored: list[tuple[str, float, dict[str, Any]]] = []
    priority_items: list[dict[str, Any]] = []

    for hypothesis_id, decision in decisions.items():
        action = str(decision.get("action") or "pending")
        action_counts[action if action in action_counts else "pending"] += 1
        score = decision.get("total_score")
        if isinstance(score, int | float):
            scored.append((hypothesis_id, float(score), decision))
        if action in {"pause", "reject", "revise"} or (
            isinstance(score, int | float) and float(score) < 70
        ):
            priority_items.append(
                {
                    "hypothesis_id": hypothesis_id,
                    "action": action,
                    "total_score": float(score) if isinstance(score, int | float) else None,
                    "reason_summary": decision.get("reason_summary") or "",
                }
            )

    priority_items = sorted(
        priority_items,
        key=lambda item: (
            action_priority(str(item["action"])),
            item["total_score"] if item["total_score"] is not None else 101.0,
            str(item["hypothesis_id"]),
        ),
    )[:8]
    avg_score = round(sum(score for _, score, _ in scored) / len(scored), 2) if scored else None
    lowest_scored = [
        {
            "hypothesis_id": hypothesis_id,
            "total_score": score,
            "action": decision.get("action") or "pending",
            "reason_summary": decision.get("reason_summary") or "",
        }
        for hypothesis_id, score, decision in sorted(scored, key=lambda item: item[1])[:5]
    ]
    return {
        "total_decisions": len(decisions),
        "action_counts": action_counts,
        "avg_score": avg_score,
        "priority_items": priority_items,
        "lowest_scored": lowest_scored,
    }


def action_priority(action: str) -> int:
    return {
        "reject": 0,
        "pause": 1,
        "revise": 2,
        "expand": 3,
        "pending": 4,
        "keep": 5,
    }.get(action, 4)


def rank_hypotheses_for_prioritized_routes(
    hypotheses: list[Any],
    decisions: dict[str, dict[str, Any]],
) -> tuple[list[Any], dict[str, dict[str, Any]]]:
    ranked = []
    rank_map: dict[str, dict[str, Any]] = {}
    for hypothesis in hypotheses:
        decision = decisions.get(hypothesis.id)
        composite = composite_breeding_rank_score(hypothesis, decision)
        rank_map[hypothesis.id] = composite
        if decision is not None:
            decision["composite_score"] = composite["score"]
            decision["composite_components"] = composite["components"]
        ranked.append((hypothesis, composite["score"]))
    ranked_hypotheses = [
        hypothesis
        for hypothesis, _score in sorted(
            ranked,
            key=lambda item: (
                -item[1],
                -(item[0].calibration_score or 0),
                item[0].title or item[0].id,
            ),
        )
    ]
    return ranked_hypotheses, rank_map


def route_admission_summary(
    hypothesis: Any,
    decision: dict[str, Any] | None,
    *,
    min_pairwise_calibrations: int = 3,
) -> dict[str, Any]:
    """Return one auditable admission decision for the formal route ranking.

    A route is formally rankable only after evidence review, an acceptable
    iteration gate, and enough pairwise calibration. Keeping this rule here
    makes the UI and future route-selection code agree on the same boundary.
    """
    state = str(getattr(hypothesis, "state", "") or "")
    action = str((decision or {}).get("action") or "pending")
    review_gate = str((decision or {}).get("review_gate") or "")
    played = max(0, int(getattr(hypothesis, "pairwise_calibrations_played", 0) or 0))
    required = max(1, int(min_pairwise_calibrations))
    has_calibration_score = getattr(hypothesis, "calibration_score", None) is not None

    base = {
        "eligible": False,
        "status": "pending",
        "status_label": "待处理",
        "reasons": [],
        "next_step": "",
        "next_step_code": "",
        "pairwise_played": played,
        "pairwise_required": required,
        "pairwise_ready": has_calibration_score and played >= required,
    }

    if state in {"rejected", "quarantined", "retired"}:
        base.update(
            status="blocked",
            status_label={
                "rejected": "已拒绝",
                "quarantined": "已阻断",
                "retired": "已归档",
            }[state],
            reasons=["路线生命周期状态不允许进入正式排名。"],
            next_step="保留审计记录, 不再安排正式排序任务。",
            next_step_code="no_op",
        )
        return base

    if decision is None:
        base.update(
            status="evidence_review_pending",
            status_label="待证据评审",
            reasons=["尚未形成该路线的证据评审与迭代决策。"],
            next_step="由 Risk Reviewer 完成证据闸门和风险评审。",
            next_step_code="complete_evidence_review",
        )
        return base

    if action in {"reject", "pause"}:
        base.update(
            status="blocked",
            status_label="已暂停" if action == "pause" else "已拒绝",
            reasons=[
                "当前迭代决策为暂停, 暂不进入正式排名。"
                if action == "pause"
                else "当前迭代决策为拒绝, 不进入正式排名。"
            ],
            next_step="等待新的证据或人工反馈后再决定是否恢复。"
            if action == "pause"
            else "如需恢复, 必须产生新的修订路线。",
            next_step_code="await_confirmation" if action == "pause" else "no_op",
        )
        return base

    if action in {"revise", "expand"} or review_gate in {
        "missing_piece",
        "mixed",
        "blocked",
        "reject",
    }:
        reason = (decision or {}).get("reason_summary") or "证据闸门尚未完全通过。"
        next_step = (decision or {}).get("new_hypothesis_direction") or "补齐关键证据后重新评审。"
        base.update(
            status="evidence_gap",
            status_label="待补证/修订",
            reasons=[str(reason)],
            next_step=str(next_step),
            next_step_code=str(
                (decision or {}).get("next_step_recommendation") or "revise_route"
            ),
        )
        return base

    if not has_calibration_score or played < required:
        base.update(
            status="pairwise_pending",
            status_label="待配对校准",
            reasons=[
                "路线已通过证据闸门, 但配对校准尚未达到正式排名所需次数。"
            ],
            next_step=f"继续安排配对校准 ({played}/{required} 次)。",
            next_step_code="run_pairwise_calibration",
        )
        return base

    base.update(
        eligible=True,
        status="ranked",
        status_label="正式入榜",
        reasons=["证据闸门、迭代决策和配对校准均已满足正式排名条件。"],
        next_step="进入正式路线排序, 并保留后续验证任务。",
        next_step_code="rank_route",
    )
    return base


def composite_breeding_rank_score(
    hypothesis: Any,
    decision: dict[str, Any] | None,
) -> dict[str, Any]:
    action = str((decision or {}).get("action") or "pending")
    scorecard = scorecard_by_dimension((decision or {}).get("scorecard") or [])
    iteration_score = bounded_score((decision or {}).get("total_score"), default=55.0)
    pairwise_calibration = calibration_score_to_ui_score(
        getattr(hypothesis, "calibration_score", None)
    )
    evidence_support = bounded_score(scorecard.get("evidence_support"), default=iteration_score)
    validation_actionability = bounded_score(
        scorecard.get("validation_actionability"),
        default=iteration_score,
    )
    review_strength = bounded_score(scorecard.get("review_strength"), default=iteration_score)
    risk_control = bounded_score(scorecard.get("risk_control"), default=iteration_score)
    action_multiplier = action_rank_multiplier(action)
    action_penalty = action_rank_penalty(action)
    design_audit = design_card_audit_summary((decision or {}).get("breeding_design_card_audit"))
    design_penalty = design_card_rank_penalty(design_audit)

    raw = (
        0.35 * evidence_support
        + 0.25 * validation_actionability
        + 0.20 * review_strength
        + 0.20 * risk_control
    )
    final_score = max(
        0.0,
        min(100.0, raw * action_multiplier - action_penalty - design_penalty),
    )
    return {
        "score": round(final_score, 2),
        "components": {
            "pairwise_calibration": round(pairwise_calibration, 2),
            "evidence_support": round(evidence_support, 2),
            "validation_actionability": round(validation_actionability, 2),
            "review_strength": round(review_strength, 2),
            "risk_control": round(risk_control, 2),
            "action_multiplier": action_multiplier,
            "action_penalty": action_penalty,
            "design_card_penalty": design_penalty,
            "design_card_completeness": design_audit.get("completeness_score"),
            "design_card_missing_critical_count": len(
                design_audit.get("missing_critical_fields") or []
            ),
        },
        "breeding_design_card_audit": design_audit,
    }


def design_card_audit_summary(value: Any) -> dict[str, Any]:
    if not isinstance(value, dict) or not value:
        return {}
    return {
        "status": value.get("status"),
        "completeness_score": _optional_bounded_score(value.get("completeness_score")),
        "missing_critical_fields": [
            str(field)
            for field in value.get("missing_critical_fields") or []
            if field
        ],
        "missing_fields": [
            str(field)
            for field in value.get("missing_fields") or []
            if field
        ],
        "penalty": _optional_bounded_score(value.get("penalty")),
    }


def design_card_rank_penalty(audit: dict[str, Any]) -> float:
    if not audit:
        return 0.0
    missing_critical_count = len(audit.get("missing_critical_fields") or [])
    missing_count = len(audit.get("missing_fields") or [])
    score = audit.get("completeness_score")
    completeness_gap = max(0.0, 80.0 - score) if isinstance(score, int | float) else 0.0
    iteration_penalty = audit.get("penalty")
    penalty = (
        missing_critical_count * 1.4
        + max(0, missing_count - missing_critical_count) * 0.35
        + completeness_gap * 0.05
    )
    if isinstance(iteration_penalty, int | float):
        penalty = max(penalty, float(iteration_penalty) * 0.25)
    if audit.get("status") == "needs_attention":
        penalty += 1.0
    return round(min(10.0, max(0.0, penalty)), 2)


def scorecard_by_dimension(rows: list[Any]) -> dict[str, float]:
    out: dict[str, float] = {}
    for row in rows:
        if not isinstance(row, dict):
            continue
        dimension = row.get("dimension")
        score = row.get("score")
        if isinstance(dimension, str) and isinstance(score, int | float):
            out[dimension] = float(score)
    return out


def bounded_score(value: Any, *, default: float) -> float:
    if not isinstance(value, int | float):
        return default
    return max(0.0, min(100.0, float(value)))


def _optional_bounded_score(value: Any) -> float | None:
    if not isinstance(value, int | float):
        return None
    return max(0.0, min(100.0, float(value)))


def calibration_score_to_ui_score(calibration_score: Any) -> float:
    if not isinstance(calibration_score, int | float):
        return 50.0
    return max(0.0, min(100.0, 50.0 + (float(calibration_score) - 1200.0) / 8.0))


def action_rank_multiplier(action: str) -> float:
    return {
        "keep": 1.0,
        "expand": 0.88,
        "revise": 0.72,
        "pending": 0.68,
        "pause": 0.35,
        "reject": 0.0,
    }.get(action, 0.68)


def action_rank_penalty(action: str) -> float:
    return {
        "keep": 0.0,
        "expand": 3.0,
        "revise": 8.0,
        "pending": 10.0,
        "pause": 25.0,
        "reject": 100.0,
    }.get(action, 10.0)
