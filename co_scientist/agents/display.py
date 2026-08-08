"""Public six-agent vocabulary for the breeding scientist system.

The UI and event stream use this module to present the agreed six-agent model.
"""

from __future__ import annotations

from typing import Any

SIX_AGENT_ORDER = (
    "Goal Interpreter",
    "Evidence Curator",
    "Breeding Designer",
    "Validation Planner",
    "Risk Reviewer",
    "Iteration Orchestrator",
)

INTERNAL_TO_CORE_AGENT = {
    "parse_goal": "Goal Interpreter",
    "goal_interpreter": "Goal Interpreter",
    "evidence_curator": "Evidence Curator",
    "breeding_designer": "Breeding Designer",
    "validation_planner": "Validation Planner",
    "risk_reviewer": "Risk Reviewer",
    "iteration_orchestrator": "Iteration Orchestrator",
    "supervisor": "Iteration Orchestrator",
}

INTERNAL_AGENT_STEPS = {
    "parse_goal": "Goal parsing",
    "goal_interpreter": "Goal parsing",
    "evidence_curator": "Evidence graph curation",
    "breeding_designer": "Hypothesis design",
    "validation_planner": "Validation planning",
    "risk_reviewer": "Risk review",
    "iteration_orchestrator": "Queue decision and closure",
    "supervisor": "Task orchestration",
}

ACTION_STEPS = {
    "CurateEvidencePackage": "Evidence graph curation",
    "DesignHypothesis": "Hypothesis design",
    "DirectHypothesisDesign": "Hypothesis design",
    "ReviseOrExpandRoute": "Route revision and expansion",
    "PlanValidation": "Validation planning",
    "ReviewRisk": "Risk review",
    "DecideIteration": "Queue decision and closure",
    "AssessHypothesisEvidence": "Evidence review",
    "QueuePairwiseCalibration": "Pairwise calibration",
    "RunPairwiseCalibration": "Pairwise calibration",
    "SynthesizeIterationFeedback": "System feedback",
    "GenerateFinalBreedingOverview": "Final synthesis",
}

RESULT_KIND_LABELS = {
    "evidence_curated": "evidence_graph_curated",
    "iteration_decision": "iteration_decision",
    "validation_planned": "validation_plan_ready",
    "risk_reviewed": "risk_review_ready",
    "hypothesis_created": "hypothesis_designed",
    "evidence_review_completed": "evidence_review_completed",
    "pairwise_calibration_queued": "pairwise_calibration_queued",
    "pairwise_calibration_complete": "pairwise_calibration_complete",
    "system_feedback_generated": "system_feedback_generated",
    "final_overview_generated": "final_synthesis_generated",
    "noop": "noop",
}

HYPOTHESIS_LIFECYCLE_LABELS = {
    "draft": "draft",
    "reviewed": "candidate",
    "calibration_pool": "candidate",
    "pinned": "ready",
    "quarantined": "blocked",
    "rejected": "rejected",
    "retired": "archived",
}

HYPOTHESIS_STRATEGY_LABELS = {
    "literature": "Evidence-backed route",
    "debate": "Alternative route",
    "combine": "Combined route",
    "simplify": "Simplified validation route",
    "out_of_box": "Expanded search route",
    "feasibility": "Feasibility repair route",
    "assumption": "Assumption route",
    "feedback_driven": "Iteration-driven route",
}

REVIEW_KIND_LABELS = {
    "full": "Evidence review",
    "verification": "Evidence verification",
    "observation": "Observation review",
    "simulation": "Simulation review",
}

REVIEW_VERDICT_LABELS = {
    "already_explained": "supported by existing route",
    "other_more_likely": "alternative route more likely",
    "missing_piece": "needs evidence",
    "neutral": "inconclusive",
    "disproved": "do not advance",
}

ACTION_LABELS_ZH = {
    "keep": "可推进",
    "revise": "需修订",
    "expand": "扩展探索",
    "pause": "暂停",
    "reject": "拒绝",
    "pending": "待处理",
}

NEXT_STEP_LABELS_ZH = {
    "generate_revised_hypothesis_from_decision": "生成修订版假设",
    "generate_expanded_hypothesis_from_decision": "生成扩展假设",
    "generate_simplified_hypothesis_from_decision": "生成简化假设",
    "no_op": "暂无下一步动作",
}

REVIEW_GATE_LABELS_ZH = {
    "pass": "通过",
    "mixed": "证据不完整",
    "missing_piece": "需补证",
    "blocked": "受阻",
    "reject": "不建议推进",
}

INTENT_LABELS_ZH = {
    "repair_parent_route": "修复父路线",
    "rank_without_successor": "不生成后继，进入综合排序",
    "broaden_search_space": "扩大候选空间",
    "expand_candidate_space": "扩大候选空间",
    "simplify_validation_path": "简化验证路径",
    "combine_routes": "合并路线",
    "await_confirmation": "等待确认",
    "terminate_route": "终止路线",
    "no_op": "暂无迭代动作",
}

DECISION_SENTENCE_ZH = {
    "Review verdict is missing_piece; the route should be revised before prioritization.": (
        "评审结论为需补证，进入综合排序前应先修订路线。"
    ),
    "Review verdict is missing_piece; revise the route before composite prioritization.": (
        "评审结论为需补证，进入综合排序前应先修订路线。"
    ),
    "Evidence gaps are manageable and the hypothesis can enter prioritization.": (
        "证据缺口可控，该假设可以进入综合优先级排序。"
    ),
    "Marker or genotype validation must be carried into the next validation plan.": (
        "标记或基因型验证必须纳入下一轮验证计划。"
    ),
    "Resolve the local marker validation gap.": "补齐本地标记验证缺口。",
    "Resolve local marker validation before prioritization.": "进入综合排序前先补齐本地标记验证。",
    "Resolve the CAPS marker validation gap.": "补齐 CAPS 标记验证缺口。",
    "Marker validation gap remains.": "本地标记验证缺口仍未解决。",
    "Revise the parent route around a locally testable marker/genotyping validation plan.": (
        "围绕本地可测试的标记/基因分型验证方案修订父路线。"
    ),
    "No successor hypothesis required; route can enter composite prioritization.": (
        "无需生成后继假设，该路线可以进入综合优先级排序。"
    ),
}

GAP_PREFIX_LABELS_ZH = {
    "general_evidence_gap": "一般证据缺口",
    "genotype_or_marker_validation": "基因型/标记验证",
    "material_availability": "材料可得性",
    "phenotyping_protocol": "表型鉴定方案",
    "field_trial_validation": "田间验证",
    "risk_control": "风险控制",
}

EVENT_LABELS = {
    "hypothesis_created": "hypothesis_designed",
    "evidence_review_completed": "evidence_review_completed",
}


def core_agent_name(agent: str | None) -> str | None:
    if not agent:
        return None
    return INTERNAL_TO_CORE_AGENT.get(agent, agent)


def agent_step_name(agent: str | None, action: str | None = None) -> str | None:
    if action:
        step = ACTION_STEPS.get(action)
        if step:
            return step
    if not agent:
        return None
    return INTERNAL_AGENT_STEPS.get(agent)


def hypothesis_lifecycle_label(state: Any) -> str:
    value = str(state or "")
    return HYPOTHESIS_LIFECYCLE_LABELS.get(value, value or "unknown")


def hypothesis_strategy_label(strategy: Any) -> str:
    value = str(strategy or "")
    return HYPOTHESIS_STRATEGY_LABELS.get(value, value.replace("_", " ") or "unknown")


def review_kind_label(kind: Any) -> str:
    value = str(kind or "review")
    return REVIEW_KIND_LABELS.get(value, value.replace("_", " ").title())


def review_verdict_label(verdict: Any) -> str:
    value = str(verdict or "unknown")
    return REVIEW_VERDICT_LABELS.get(value, value.replace("_", " "))


def public_event_name(event: str | None) -> str:
    value = str(event or "")
    return EVENT_LABELS.get(value, value)


def public_result_kind(kind: str | None) -> str | None:
    if not kind:
        return None
    return RESULT_KIND_LABELS.get(kind, kind)


def localize_iteration_decision(decision: dict[str, Any]) -> dict[str, Any]:
    """Add Chinese display labels for iteration decisions without changing stored data."""
    item = dict(decision)
    action = str(item.get("action") or "pending")
    next_step = str(item.get("next_step_recommendation") or "no_op")
    review_gate = str(item.get("review_gate") or "")
    item["display"] = {
        "action_label": ACTION_LABELS_ZH.get(action, _humanize_machine_token(action)),
        "next_step_label": NEXT_STEP_LABELS_ZH.get(
            next_step, _humanize_machine_token(next_step)
        ),
        "review_gate_label": REVIEW_GATE_LABELS_ZH.get(
            review_gate, _humanize_machine_token(review_gate)
        ),
        "reasons": [
            localize_decision_text(str(reason)) for reason in item.get("reasons") or []
        ],
    }
    intent = item.get("route_revision_intent")
    if isinstance(intent, dict):
        intent = dict(intent)
        intent_value = str(
            intent.get("route_revision_intent") or "no_op"
        )
        display_intent = dict(intent)
        display_intent["intent_label"] = INTENT_LABELS_ZH.get(
            intent_value,
            _humanize_machine_token(intent_value),
        )
        display_intent["direction_label"] = localize_decision_text(
            str(intent.get("new_hypothesis_direction") or "")
        )
        display_intent["evidence_gap_to_resolve_labels"] = [
            localize_gap_text(str(gap))
            for gap in intent.get("evidence_gap_to_resolve") or []
        ]
        display_intent["do_not_repeat_labels"] = [
            localize_decision_text(str(value))
            for value in intent.get("do_not_repeat") or []
        ]
        item["route_revision_intent"] = intent
        item["display_route_revision_intent"] = display_intent
    return item


def localize_decision_text(text: str) -> str:
    stripped = text.strip()
    if not stripped:
        return ""
    return DECISION_SENTENCE_ZH.get(stripped, stripped)


def localize_gap_text(text: str) -> str:
    stripped = text.strip()
    if not stripped:
        return ""
    if ":" in stripped:
        prefix, rest = stripped.split(":", 1)
        label = GAP_PREFIX_LABELS_ZH.get(prefix.strip())
        if label:
            return f"{label}：{rest.strip()}"
    return localize_decision_text(stripped)


def decorate_agent_payload(payload: dict[str, Any] | None) -> dict[str, Any] | None:
    """Add public six-agent fields while preserving internal routing metadata."""
    if payload is None:
        return None
    out = dict(payload)
    internal = out.get("agent") or out.get("agent_internal")
    action = str(out.get("action") or "")
    kind = str(out.get("kind") or "")
    if action:
        out.setdefault("action_internal", action)
        out["public_action"] = ACTION_STEPS.get(action, action)
    if kind:
        out.setdefault("kind_internal", kind)
        out["public_kind"] = public_result_kind(kind)
    if internal:
        out.setdefault("agent_internal", internal)
        core = core_agent_name(str(internal))
        out["agent"] = core
        out["core_agent"] = core
        step = agent_step_name(str(internal), action)
        if step:
            out["agent_step"] = step
    return out


def _humanize_machine_token(value: str) -> str:
    value = value.strip("_ ")
    return value.replace("_", " ") if value else "未知"
