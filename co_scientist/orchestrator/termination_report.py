"""Human-readable termination rationale for final breeding reports."""

from __future__ import annotations

from typing import Any


def termination_report_markdown(
    *,
    session: Any,
    hypotheses: list[Any],
    decisions: dict[str, dict[str, Any]],
    stop_reason: Any,
    language: str,
) -> str:
    """Build a deterministic report section explaining why the run stopped."""

    reason = _reason_value(stop_reason)
    max_hypothesis_count = _positive_int_or_none(
        getattr(session.research_plan, "max_hypothesis_count", None)
    )
    hypothesis_count = len(hypotheses)
    action_counts = _action_counts(decisions)
    keep_ready = _keep_ready_count(decisions)
    revise_candidates = action_counts.get("revise", 0)
    expand_candidates = action_counts.get("expand", 0)
    total_decisions = len(decisions)
    hyp_count = f"{hypothesis_count}"
    if max_hypothesis_count is not None:
        hyp_count += f" / {max_hypothesis_count}"

    if language == "zh":
        explanation = _reason_explanation(reason, language="zh")
        lines = [
            "# 系统终止原因",
            f"- 终止原因: `{reason or 'unknown'}`",
            f"- 已生成假设数: {hyp_count}",
            f"- 迭代决策数: {total_decisions}",
            f"- 可直接推进路线数: {keep_ready}",
            f"- 需修订但仍有潜力路线数: {revise_candidates}",
            f"- 需扩展探索路线数: {expand_candidates}",
            "- 决策分布: " + _format_action_counts(action_counts),
            f"系统推断: {explanation}",
            "系统推断: `可直接推进路线数 = 0` 只表示当前没有假设达到 keep-ready "
            "阈值，并不等同于系统没有生成有价值的候选假设。",
        ]
        if reason == "breeding_max_hypotheses_reached":
            lines.append(
                "系统推断: 这是用户设定的假设池上限触发的运行控制结果，"
                "不是对育种目标本身的否定。"
            )
        return "\n".join(lines) + "\n"

    explanation = _reason_explanation(reason, language="en")
    lines = [
        "# System termination rationale",
        f"- Stop reason: `{reason or 'unknown'}`",
        f"- Hypotheses generated: {hyp_count}",
        f"- Iteration decisions: {total_decisions}",
        f"- Directly advanceable routes: {keep_ready}",
        f"- Revision-needed candidate routes: {revise_candidates}",
        f"- Expansion-needed candidate routes: {expand_candidates}",
        "- Action distribution: " + _format_action_counts(action_counts),
        f"System inference: {explanation}",
        "System inference: `Directly advanceable routes = 0` means no hypothesis "
        "has crossed the keep-ready threshold yet; it does not mean the system "
        "failed to produce useful candidate hypotheses.",
    ]
    if reason == "breeding_max_hypotheses_reached":
        lines.append(
            "System inference: This is an execution-control stop caused by the "
            "user-defined hypothesis cap; it is not biological evidence against "
            "the breeding objective."
        )
    return "\n".join(lines) + "\n"


def _reason_value(stop_reason: Any) -> str | None:
    if stop_reason is None:
        return None
    value = getattr(stop_reason, "value", stop_reason)
    if not isinstance(value, str):
        value = str(value)
    return _normalize_stop_reason(value)


def _normalize_stop_reason(reason: str | None) -> str | None:
    return reason


def _reason_explanation(reason: str | None, *, language: str) -> str:
    zh = {
        "breeding_success_ready": "系统已经找到足够数量、综合分较高且可进入最终审核的 keep-ready 路线。",
        "breeding_evidence_blocked": "多数路线因证据缺口、冲突证据或本地验证不足而被暂停或拒绝。",
        "breeding_no_composite_gain": "连续迭代没有产生综合评分足够强的新路线。",
        "breeding_max_hypotheses_reached": "已达到用户设定的最大假设池，但尚未形成足够数量的 keep-ready 路线。",
        "pairwise_calibration_stable": "优先路线经过成对校准后，在配置窗口内保持稳定。",
        "budget": "运行达到预算限制。",
        "wall_clock": "运行达到时间限制。",
        "idle": "任务队列已经耗尽。",
        "task_failure": "关键任务连续失败，系统未将本次运行判定为完成。",
        "external": "运行由用户暂停或终止。",
    }
    en = {
        "breeding_success_ready": (
            "The system found enough high-scoring keep-ready routes for final review."
        ),
        "breeding_evidence_blocked": (
            "Most routes were paused or rejected because evidence gaps, conflicts, "
            "or missing local validation remained."
        ),
        "breeding_no_composite_gain": (
            "Recent iterations did not produce a sufficiently strong composite-scored route."
        ),
        "breeding_max_hypotheses_reached": (
            "The user-defined hypothesis cap was reached before enough keep-ready routes "
            "were available."
        ),
        "pairwise_calibration_stable": (
            "The prioritized breeding routes stayed stable after pairwise calibration."
        ),
        "budget": "The run reached the configured budget limit.",
        "wall_clock": "The run reached the configured wall-clock limit.",
        "idle": "The task queue drained with no runnable tasks remaining.",
        "task_failure": "A critical task exhausted its retries; the run is not considered complete.",
        "external": "The run was paused or aborted by the user.",
    }
    table = zh if language == "zh" else en
    fallback = (
        "运行已经结束，但没有记录更详细的终止原因。"
        if language == "zh"
        else "The run completed without a detailed stop reason."
    )
    return table.get(reason or "", fallback)


def _action_counts(decisions: dict[str, dict[str, Any]]) -> dict[str, int]:
    counts = {action: 0 for action in ("keep", "expand", "revise", "pause", "reject", "pending")}
    for decision in decisions.values():
        action = str(decision.get("action") or "pending")
        counts[action] = counts.get(action, 0) + 1
    return counts


def _format_action_counts(counts: dict[str, int]) -> str:
    return "; ".join(f"{action}={count}" for action, count in counts.items() if count) or "none"


def _keep_ready_count(decisions: dict[str, dict[str, Any]]) -> int:
    count = 0
    for decision in decisions.values():
        if decision.get("action") != "keep":
            continue
        score = decision.get("total_score")
        if isinstance(score, int | float) and score >= 75.0:
            count += 1
    return count


def _positive_int_or_none(value: Any) -> int | None:
    if not isinstance(value, int):
        return None
    if value <= 0:
        return None
    return value
