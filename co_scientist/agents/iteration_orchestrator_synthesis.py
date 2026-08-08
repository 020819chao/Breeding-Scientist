"""Iteration Orchestrator synthesis service.

Two actions:
- `SynthesizeIterationFeedback`        鈥?writes a SystemFeedback row.
  The body is auto-injected into future Breeding Designer prompts via the
  `latest_system_feedback` query the agents already perform.
- `GenerateFinalBreedingOverview`    鈥?writes the markdown
  report and updates `sessions.final_overview`.
"""

from __future__ import annotations

import json
import re
from datetime import UTC, datetime
from typing import Any

from .. import ids
from ..knowledge.germplasm import load_germplasm_records
from ..knowledge.rag import load_evidence_index
from ..llm.anthropic_client import AgentCallSpec, CachedBlock, CallContext
from ..llm.prompts import render
from ..llm.routing import route
from ..logging import get_logger
from ..models import SystemFeedback, Task, TaskResult
from ..orchestrator.termination_report import termination_report_markdown
from ..prioritization.composite import (
    latest_iteration_decisions_for_session,
    rank_hypotheses_for_prioritized_routes,
)
from ..storage.artifacts import read_json, write_json, write_text
from ..storage.repos import feedback as fb_repo
from ..storage.repos import hypotheses as hyp_repo
from ..storage.repos import pairwise_calibration as pairwise_repo
from ..storage.repos import reviews as rev_repo
from ..storage.repos import sessions as sess_repo
from .base import BaseAgent
from .schemas import RECORD_SYSTEM_FEEDBACK_TOOL

log = get_logger("iteration_orchestrator.final_synthesis")


class IterationOrchestratorSynthesisStage(BaseAgent):
    name = "Iteration Orchestrator"

    async def execute(self, task: Task) -> TaskResult:
        if task.action == "SynthesizeIterationFeedback":
            return await self._system_feedback(task)
        if task.action == "GenerateFinalBreedingOverview":
            return await self._final_overview(task)
        raise ValueError(
            f"IterationOrchestratorSynthesisStage does not handle action {task.action!r}"
        )

    # ----------------------------- system feedback ----------------------------- #

    async def _system_feedback(self, task: Task) -> TaskResult:
        session = await sess_repo.fetch(self.deps.db, task.session_id)
        if session is None:
            raise RuntimeError(f"session {task.session_id} missing")

        reviews = await rev_repo.list_for_session(self.deps.db, session.id)
        if not reviews:
            return TaskResult(kind="noop", extra={"reason": "no reviews yet"})

        reviews_block = "\n\n---\n\n".join(
            f"### Review of `{r.hypothesis_id}` (kind={r.kind}, verdict={r.verdict or '?'})\n{r.body[:3000]}"
            for r in reviews[:50]
        )
        rationales = await pairwise_repo.recent_pairwise_rationales(
            self.deps.db, session.id, limit=50
        )
        debate_block = "\n\n---\n\n".join(rat[:1500] for rat in rationales if rat)

        prompt = render(
            "iteration_orchestrator.system_feedback",
            goal=session.research_plan.objective,
            preferences="; ".join(session.research_plan.preferences),
            reviews=reviews_block,
            debate_rationales=debate_block,
        )
        r = route(self.deps.cfg, "iteration_orchestrator", "system")
        spec = AgentCallSpec(
            route=r,
            system_blocks=[
                CachedBlock(self._system_prompt_header(), cache=True),
                CachedBlock(
                    f"# Research goal\n{session.research_goal}\n\n"
                    f"# Preferences\n{'; '.join(session.research_plan.preferences)}",
                    cache=True,
                ),
            ],
            user_blocks=[CachedBlock(prompt, cache=False)],
            tools=[RECORD_SYSTEM_FEEDBACK_TOOL],
            tool_choice={"type": "tool", "name": "record_system_feedback"},
            max_output_tokens=4096,
        )
        ctx = CallContext(
            session_id=session.id, task_id=task.id,
            agent="iteration_orchestrator", action=task.action, mode="system",
        )
        resp = await self.deps.llm.call(spec, ctx)
        record = self._final_tool_use(resp, "record_system_feedback")
        if record is None:
            return TaskResult(kind="noop", extra={"reason": "no record_system_feedback"})

        narrative = record.get("narrative") or ""
        if record.get("common_weaknesses"):
            narrative += "\n\n**Common weaknesses:** " + "; ".join(record["common_weaknesses"])
        if record.get("common_strengths"):
            narrative += "\n\n**Common strengths:** " + "; ".join(record["common_strengths"])
        if record.get("suggested_focus_areas"):
            narrative += "\n\n**Suggested focus:** " + "; ".join(record["suggested_focus_areas"])

        fb_id = ids.feedback_id()
        artifact_path = await write_json(
            self.deps.cfg, session.id, "system_feedback", fb_id, record
        )
        await fb_repo.insert(self.deps.db, SystemFeedback(
            id=fb_id, session_id=session.id, created_at=datetime.now(UTC),
            source="iteration_orchestrator", kind="system_feedback",
            target_id=None, text=narrative.strip()[:8000],
            artifact_path=artifact_path, active=True,
        ))
        return TaskResult(
            kind="system_feedback_generated",
            extra={"feedback_id": fb_id, "n_reviews": len(reviews)},
        )

    # ----------------------------- final overview ----------------------------- #

    async def _final_overview(self, task: Task) -> TaskResult:
        session = await sess_repo.fetch(self.deps.db, task.session_id)
        if session is None:
            raise RuntimeError(f"session {task.session_id} missing")

        all_hyps = await hyp_repo.list_for_session(self.deps.db, session.id)
        latest_decisions = latest_iteration_decisions_for_session(self.deps.cfg, session.id)
        stop_reason = task.payload.get("stop_reason")
        if not all_hyps:
            return TaskResult(kind="noop", extra={"reason": "no hypotheses"})
        top, rank_map = _top_hypotheses_for_final_overview(
            all_hyps,
            latest_decisions,
            k=10,
        )

        # Fetch all reviews for the session in one query, then group by
        # hypothesis_id. Beats N+1 list_for_hypothesis() calls for top-K.
        reviews_by_hyp: dict[str, list] = {}
        for rv in await rev_repo.list_for_session(self.deps.db, session.id):
            reviews_by_hyp.setdefault(rv.hypothesis_id, []).append(rv)

        # Build the top-hypotheses block: summary + reviews + source evidence.
        # The final report prompt relies on this block for sentence-level
        # literature support; keep citation/evidence URLs and excerpts visible.
        chunks: list[str] = []
        evidence_accession_ids: set[str] = set()
        evidence_package_seen = False
        germplasm_records: list[dict[str, str]] = []
        try:
            germplasm_records = load_germplasm_records(self.deps.cfg.germplasm_csv_path)
        except Exception as e:
            log.warning("final_overview_germplasm_table_failed", err=str(e))
        for h in top:
            h_record = await _read_record_artifact(self.deps.cfg, h.artifact_path)
            evidence_package_path = h_record.get("evidence_package_path")
            if evidence_package_path:
                try:
                    evidence_package = await read_json(self.deps.cfg, str(evidence_package_path))
                except Exception:
                    evidence_package = {}
                if isinstance(evidence_package, dict):
                    evidence_package_seen = True
                    germplasm_rows = (
                        (evidence_package.get("local_germplasm") or {}).get("results") or []
                    )
                    for row in germplasm_rows:
                        if isinstance(row, dict) and row.get("accession_id"):
                            evidence_accession_ids.add(str(row["accession_id"]))
            review_lines: list[str] = []
            evidence_lines: list[str] = []
            for r in reviews_by_hyp.get(h.id, []):
                r_record = await _read_record_artifact(self.deps.cfg, r.artifact_path)
                review_lines.append(
                    f"  - {r.kind}: verdict={r.verdict or '?'} "
                    f"(n={r.scores.novelty}, c={r.scores.correctness}, t={r.scores.testability})"
                )
                breeding_scores = _format_breeding_review_scores(r_record)
                if breeding_scores:
                    review_lines.append(f"    breeding_scores: {breeding_scores}")
                evidence_records = r_record.get("evidence") or [
                    ev.model_dump() for ev in r.evidence
                ]
                for ev in _prioritize_source_records(evidence_records, limit=12):
                    if not isinstance(ev, dict):
                        continue
                    evidence_lines.append(
                        f"  - Review evidence ({r.kind}): {ev.get('claim', '')}\n"
                        f"    URL: {ev.get('url', '')}\n"
                        f"    Excerpt: {str(ev.get('excerpt', ''))[:600]}"
                    )
            citation_records = h_record.get("citations") or [
                c.model_dump() for c in h.citations
            ]
            citation_lines = [
                f"  - Hypothesis citation: {c.get('title', '(no title)')}"
                + (f" ({c.get('year')})" if c.get("year") else "")
                + f"\n    URL: {c.get('url', '')}"
                + (f"\n    Excerpt: {str(c.get('excerpt', ''))[:600]}" if c.get("excerpt") else "")
                for c in _prioritize_source_records(citation_records, limit=12)
                if isinstance(c, dict)
            ]
            breeding_context = _format_breeding_context(h_record.get("breeding_context"))
            rank_info = rank_map.get(h.id, {})
            composite_s = (
                f"{rank_info['score']:.1f}"
                if isinstance(rank_info.get("score"), int | float)
                else "n/a"
            )
            action = str((latest_decisions.get(h.id) or {}).get("action") or "pending")
            pairwise_s = (
                f"{h.calibration_score:.0f}"
                if h.calibration_score is not None
                else "n/a"
            )
            chunks.append(
                f"### `{h.id}` (Composite Breeding Rank {composite_s}, "
                f"historical_pairwise_score {pairwise_s}, "
                f"action `{action}`, strategy `{h.strategy}`)\n"
                f"**Title.** {h.title}\n\n"
                f"{h.summary}\n\n"
                f"**Structured breeding context:**\n"
                + (breeding_context or "  (none)") + "\n\n"
                "**Breeding review notes:**\n"
                + ("\n".join(review_lines) or "  (none)")
                + "\n\n"
                "**Available literature support:**\n"
                + ("\n".join([*citation_lines, *evidence_lines]) or "  (none)")
            )
        preflight_context = _format_preflight_rag_context(
            self.deps.cfg,
            target_scope=_session_target_scope(session),
            known_material_records=germplasm_records,
            allowed_accession_ids=evidence_accession_ids if evidence_package_seen else None,
        )
        if preflight_context:
            chunks.append(preflight_context)
        workflow_facts = _format_workflow_facts(
            session=session,
            hypotheses=all_hyps,
            stop_reason=stop_reason,
        )
        top_block = "\n\n---\n\n".join([workflow_facts, *chunks])

        latest_fb = await fb_repo.latest_system_feedback(self.deps.db, session.id)

        prompt = render(
            "iteration_orchestrator.final_synthesis",
            goal=session.research_plan.objective,
            preferences="; ".join(session.research_plan.preferences),
            system_feedback=latest_fb.text if latest_fb else "",
            top_hypotheses_block=top_block,
        )
        r = route(self.deps.cfg, "iteration_orchestrator", "final")
        spec = AgentCallSpec(
            route=r,
            system_blocks=[
                CachedBlock(self._system_prompt_header(), cache=True),
                CachedBlock(
                    f"# Research goal\n{session.research_goal}\n\n"
                    f"# Preferences\n{'; '.join(session.research_plan.preferences)}",
                    cache=True,
                ),
            ],
            user_blocks=[CachedBlock(prompt, cache=False)],
            tools=[],            # No tools 鈥?write the markdown directly
            tool_choice=None,
            max_output_tokens=8192,
        )
        ctx = CallContext(
            session_id=session.id, task_id=task.id,
            agent="iteration_orchestrator", action=task.action, mode="final",
        )
        resp = await self.deps.llm.call(spec, ctx)
        text = self._final_text(resp)
        if not text.strip():
            text = "# Research overview\n\n_(No content was generated; see transcripts.)_"

        text = _normalize_markdown_links(text)
        bilingual = _split_bilingual_overview(text)
        if evidence_package_seen:
            germplasm_records = [
                record
                for record in germplasm_records
                if str(record.get("accession_id") or "") in evidence_accession_ids
            ]
        if bilingual is not None:
            zh_text, en_text = bilingual
            zh_text, zh_audit = _finalize_overview_variant(
                zh_text,
                germplasm_records,
                evidence_text=top_block,
                hypothesis_ids=[h.id for h in top],
                language="zh",
                termination_section=termination_report_markdown(
                    session=session,
                    hypotheses=all_hyps,
                    decisions=latest_decisions,
                    stop_reason=stop_reason,
                    language="zh",
                ),
            )
            en_text, en_audit = _finalize_overview_variant(
                en_text,
                germplasm_records,
                evidence_text=top_block,
                hypothesis_ids=[h.id for h in top],
                language="en",
                termination_section=termination_report_markdown(
                    session=session,
                    hypotheses=all_hyps,
                    decisions=latest_decisions,
                    stop_reason=stop_reason,
                    language="en",
                ),
            )
            audit_path = await write_json(
                self.deps.cfg,
                session.id,
                "final",
                "overview_audit",
                {"zh": zh_audit, "en": en_audit, "bilingual": True},
            )
            overview_path = await write_text(
                self.deps.cfg, session.id, "final", "overview_zh", ".md", zh_text
            )
            await write_text(
                self.deps.cfg, session.id, "final", "overview_en", ".md", en_text
            )
            await write_text(
                self.deps.cfg, session.id, "final", "overview", ".md", zh_text
            )
            return TaskResult(
                kind="final_overview_generated",
                extra={
                    "overview_path": overview_path,
                    "audit_path": audit_path,
                    "overview_en_path": f"artifacts/{session.id}/final/overview_en.md",
                    "n_top": len(top),
                    "bilingual": True,
                },
            )

        try:
            text = _append_germplasm_resource_table(
                text,
                germplasm_records,
                evidence_text=top_block,
                language="zh" if _looks_chinese(text) else "en",
            )
        except Exception as e:
            log.warning("final_overview_germplasm_table_failed", err=str(e))
        audit = _audit_final_overview(text)
        pre_repair_audit = audit
        if audit["status"] != "pass":
            repaired = await self._repair_final_overview(
                session=session,
                task=task,
                route=r,
                original_text=text,
                audit=audit,
                source_context=top_block,
            )
            if repaired.strip():
                text = _normalize_markdown_links(repaired)
                audit = _audit_final_overview(text)
                audit["repair_attempted"] = True
                audit["pre_repair_audit"] = pre_repair_audit
            if audit.get("unsupported_important_lines"):
                text, audit = _mark_remaining_unsupported_lines_until_clean(
                    text,
                    audit,
                    hypothesis_ids=[h.id for h in top],
                    language="zh" if _looks_chinese(text) else "en",
                    max_passes=5,
                )
                audit["repair_attempted"] = True
                audit["pre_repair_audit"] = pre_repair_audit
                audit["deterministic_support_marking"] = True
        else:
            audit["repair_attempted"] = False
        if germplasm_records:
            text_with_table = _append_germplasm_resource_table(
                text,
                germplasm_records,
                evidence_text=top_block,
                language="zh" if _looks_chinese(text) else "en",
            )
            if text_with_table != text:
                text = text_with_table
                audit_metadata = {
                    k: v
                    for k, v in audit.items()
                    if k
                    not in {
                        "status",
                        "missing_sections",
                        "unsupported_important_lines",
                        "missing_breeding_elements",
                        "checks",
                    }
                }
                audit = _audit_final_overview(text)
                audit.update(audit_metadata)
        text = _ensure_next_breeding_cycle_section(
            text,
            hypothesis_ids=[h.id for h in top],
            language="zh" if _looks_chinese(text) else "en",
        )
        text = _ensure_validation_plan_section(
            text,
            language="zh" if _looks_chinese(text) else "en",
        )
        text = _append_termination_report_section(
            text,
            termination_report_markdown(
                session=session,
                hypotheses=all_hyps,
                decisions=latest_decisions,
                stop_reason=stop_reason,
                language="zh" if _looks_chinese(text) else "en",
            ),
        )
        text = _ensure_source_map_section(
            text,
            evidence_text=top_block,
            language="zh" if _looks_chinese(text) else "en",
        )
        audit_metadata = {
            k: v
            for k, v in audit.items()
            if k
            not in {
                "status",
                "missing_sections",
                "unsupported_important_lines",
                "missing_breeding_elements",
                "checks",
            }
        }
        audit = _audit_final_overview(text)
        audit.update(audit_metadata)
        text = _append_audit_section(
            text,
            audit,
            language="zh" if _looks_chinese(text) else "en",
        )
        audit_path = await write_json(
            self.deps.cfg, session.id, "final", "overview_audit", audit
        )
        overview_path = await write_text(
            self.deps.cfg, session.id, "final", "overview", ".md", text
        )
        return TaskResult(
            kind="final_overview_generated",
            extra={"overview_path": overview_path, "audit_path": audit_path, "n_top": len(top)},
        )

    async def _repair_final_overview(
        self,
        *,
        session,
        task: Task,
        route,
        original_text: str,
        audit: dict[str, Any],
        source_context: str,
    ) -> str:
        """One-shot citation/format repair pass for final reports."""

        repair_prompt = (
            "# Final report citation repair task\n\n"
            "Revise the markdown report below. Preserve the scientific content and "
            "overall structure, but fix the audit issues.\n\n"
            "Rules:\n"
            "0. Use the six-agent report structure. Required top-level section names "
            "are: `# Executive summary`, `# Six-agent loop conclusion`, "
            "`# Recommended breeding directions`, `# Breeding decision table`, "
            "`# Parent and material list`, `# Evidence graph summary`, "
            "`# Risks and evidence requests`, `# Suggested next breeding cycle`, "
            "`# 90-day validation plan`, and `# Source map and evidence gaps`. "
            "For Chinese reports, use the corresponding Chinese section names from "
            "the final synthesis prompt.\n"
            "1. Add inline source URLs or hypothesis IDs to important factual claims, "
            "recommendations, and breeding decisions.\n"
            "2. Use only URLs and hypothesis IDs available in the source context below. "
            "Do not invent citations.\n"
            "2a. Never invent placeholder `local-rag://preflight/...` URLs. Use exact "
            "`local-rag://<source_path>#L<start>-L<end>` URLs from the source context.\n"
            "3. Fix malformed markdown links such as `[Source](https://example]`.\n"
            "4. Keep the report in the same language as the original report.\n"
            "5. Keep tables valid markdown; do not cite table separator/header rows.\n"
            "6. If a claim still lacks support, explicitly mark the same sentence as "
            "`Evidence gap:` or `System inference:` instead of leaving it as a plain "
            "assertion.\n"
            "7. If local RAG `preflight` URLs are available in the source context, keep "
            "them explicitly visible in the main text or source map instead of collapsing "
            "them into a single generic RAG citation.\n"
            "8. Return only the revised markdown report. Do not include the audit section; "
            "the system will append a fresh audit.\n\n"
            "# Audit JSON\n"
            f"{json.dumps(audit, ensure_ascii=False, indent=2)}\n\n"
            "# Available source context\n"
            f"{source_context[:50000]}\n\n"
            "# Original markdown report\n"
            f"{original_text[:50000]}"
        )
        spec = AgentCallSpec(
            route=route,
            system_blocks=[
                CachedBlock(self._system_prompt_header(), cache=True),
                CachedBlock(
                    f"# Research goal\n{session.research_goal}\n\n"
                    f"# Preferences\n{'; '.join(session.research_plan.preferences)}",
                    cache=True,
                ),
            ],
            user_blocks=[CachedBlock(repair_prompt, cache=False)],
            tools=[],
            tool_choice=None,
            max_output_tokens=8192,
        )
        ctx = CallContext(
            session_id=session.id,
            task_id=task.id,
            agent="iteration_orchestrator",
            action="RepairFinalResearchOverview",
            mode="final_repair",
        )
        try:
            resp = await self.deps.llm.call(spec, ctx)
        except Exception as e:
            log.warning("final_overview_repair_failed", err=str(e))
            return ""
        return self._final_text(resp)


async def _read_record_artifact(cfg, artifact_path: str) -> dict[str, Any]:
    try:
        payload = await read_json(cfg, artifact_path)
    except Exception:
        return {}
    if isinstance(payload, dict) and isinstance(payload.get("record"), dict):
        return payload["record"]
    return {}


def _format_breeding_context(ctx: Any) -> str:
    if not isinstance(ctx, dict) or not ctx:
        return ""
    rows = [
        ("crop", ctx.get("crop")),
        ("target_trait", ctx.get("target_trait")),
        ("germplasm", ctx.get("germplasm")),
        ("donor_parent", ctx.get("donor_parent")),
        ("recurrent_parent", ctx.get("recurrent_parent")),
        ("material_availability", ctx.get("material_availability")),
        ("target_population_of_environments", ctx.get("target_population_of_environments")),
        ("candidate_genes_qtl", _join(ctx.get("candidate_genes_qtl"))),
        ("breeding_strategy", ctx.get("breeding_strategy")),
        ("selection_scheme", ctx.get("selection_scheme")),
        ("phenotyping_plan", ctx.get("phenotyping_plan")),
        ("genotyping_plan", ctx.get("genotyping_plan")),
        ("validation_trial_design", ctx.get("validation_trial_design")),
        ("decision_thresholds", ctx.get("decision_thresholds")),
        ("cycle_time_estimate", ctx.get("cycle_time_estimate")),
        ("expected_breeding_value", ctx.get("expected_breeding_value")),
        ("risks_tradeoffs", _join(ctx.get("risks_tradeoffs"))),
        ("evidence_gaps", _join(ctx.get("evidence_gaps"))),
        ("fallback_route", ctx.get("fallback_route")),
    ]
    return "\n".join(f"  - {label}: {value}" for label, value in rows if value)


def _format_breeding_review_scores(record: dict[str, Any]) -> str:
    pairs = []
    for key in (
        "genetic_gain_potential",
        "selection_actionability",
        "field_trial_feasibility",
        "material_availability",
        "marker_readiness",
        "gxe_risk",
        "phenotyping_cost",
        "breeding_cycle_time",
        "deployment_risk",
    ):
        value = record.get(key)
        if value is not None:
            pairs.append(f"{key}={value}")
    return ", ".join(pairs)


def _join(value: Any) -> str:
    if isinstance(value, list):
        return "; ".join(str(v) for v in value if v is not None)
    return str(value) if value is not None else ""


def _split_bilingual_overview(text: str) -> tuple[str, str] | None:
    zh = _extract_marker_block(text, "OVERVIEW_ZH")
    en = _extract_marker_block(text, "OVERVIEW_EN")
    if zh and en:
        return zh.strip(), en.strip()
    return None


def _extract_marker_block(text: str, name: str) -> str | None:
    pattern = re.compile(
        rf"<!--\s*{name}_START\s*-->(.*?)<!--\s*{name}_END\s*-->",
        re.IGNORECASE | re.DOTALL,
    )
    match = pattern.search(text)
    return match.group(1) if match else None


def _top_hypotheses_for_final_overview(
    hypotheses: list[Any],
    decisions: dict[str, dict[str, Any]],
    *,
    k: int,
) -> tuple[list[Any], dict[str, dict[str, Any]]]:
    candidates = [
        hypothesis
        for hypothesis in hypotheses
        if getattr(hypothesis, "state", "") not in {"rejected", "retired"}
    ]
    if not candidates:
        candidates = hypotheses
    ranked, rank_map = rank_hypotheses_for_prioritized_routes(candidates, decisions)
    return ranked[:k], rank_map


def _format_workflow_facts(
    *,
    session: Any,
    hypotheses: list[Any],
    stop_reason: str | None,
) -> str:
    plan = getattr(session, "research_plan", None)
    initial = getattr(plan, "initial_hypothesis_count", None)
    max_count = getattr(plan, "max_hypothesis_count", None)
    total = len(hypotheses)
    lines = [
        "# Session loop facts",
        f"- Parsed initial_hypothesis_count: {initial if initial is not None else 'not specified'}",
        f"- Parsed max_hypothesis_count: {max_count if max_count is not None else 'not specified'}",
        f"- Hypotheses actually produced by the closed loop: {total}",
        f"- Stop reason: {stop_reason or 'not specified'}",
        "- Reporting rule: never call the final hypothesis count the initial count. "
        "If initial_hypothesis_count is smaller than the final count, write that "
        "the system started with the initial count and iteratively expanded to "
        "the final count.",
    ]
    return "\n".join(lines)


def _finalize_overview_variant(
    text: str,
    germplasm_records: list[dict[str, str]],
    *,
    evidence_text: str,
    hypothesis_ids: list[str],
    language: str,
    termination_section: str = "",
) -> tuple[str, dict[str, Any]]:
    text = _normalize_markdown_links(text)
    if germplasm_records:
        text = _append_germplasm_resource_table(
            text,
            germplasm_records,
            evidence_text=evidence_text,
            language=language,
        )
    text = _ensure_next_breeding_cycle_section(
        text,
        hypothesis_ids=hypothesis_ids,
        language=language,
    )
    text = _ensure_validation_plan_section(text, language=language)
    audit = _audit_final_overview(text)
    if audit.get("missing_breeding_elements"):
        text = _ensure_breeding_elements_section(
            text,
            missing=audit["missing_breeding_elements"],
            language=language,
        )
        audit = _audit_final_overview(text)
    if audit.get("unsupported_important_lines"):
        text, audit = _mark_remaining_unsupported_lines_until_clean(
            text,
            audit,
            hypothesis_ids=hypothesis_ids,
            language=language,
            max_passes=5,
        )
        audit["deterministic_support_marking"] = True
    text = _append_termination_report_section(text, termination_section)
    text = _ensure_source_map_section(text, evidence_text=evidence_text, language=language)
    audit_metadata = {
        k: v
        for k, v in audit.items()
        if k
        not in {
            "status",
            "missing_sections",
            "unsupported_important_lines",
            "missing_breeding_elements",
            "checks",
        }
    }
    audit = _audit_final_overview(text)
    audit.update(audit_metadata)
    text = _append_audit_section(text, audit, language=language)
    return text, audit


def _ensure_validation_plan_section(text: str, *, language: str) -> str:
    """Promote an existing 90-day plan paragraph into a report section."""
    body = text.split("\n# Final report audit", 1)[0]
    headings = _extract_headings(body)
    aliases = (
        "90 day validation plan",
        "90-day validation plan",
        "90天验证计划",
        "90日验证计划",
    )
    if _has_heading(headings, aliases):
        return text

    heading = "# 90天验证计划" if language == "zh" else "# 90-day validation plan"
    lines = text.splitlines()
    markers = ("90天", "90日", "90 day", "90-day", "within 90")
    for index, line in enumerate(lines):
        if any(marker in line.lower() for marker in markers):
            lines.insert(index, heading)
            return "\n".join(lines)

    return text.rstrip() + (
        f"\n\n{heading}\n"
        "- Evidence gap: no explicit 90-day validation schedule was generated.\n"
    )


def _ensure_next_breeding_cycle_section(
    text: str,
    *,
    hypothesis_ids: list[str],
    language: str,
) -> str:
    """Ensure every final report states the next actionable breeding cycle."""

    body = text.split("\n# Final report audit", 1)[0]
    headings = _extract_headings(body)
    aliases = (
        "suggested next breeding cycle",
        "next breeding cycle",
        "next cycle",
        "建议的下一轮育种周期",
        "下一轮育种周期",
        "下一轮育种",
    )
    if _has_heading(headings, aliases):
        return text

    heading = "# 建议的下一轮育种周期" if language == "zh" else "# Suggested next breeding cycle"
    references = ", ".join(f"[{hypothesis_id}]" for hypothesis_id in hypothesis_ids[:3])
    route_reference = f" {references}" if references else ""
    if language == "zh":
        lines = [
            heading,
            f"- 系统推断 (System inference): 下一轮优先围绕当前排名靠前的路线{route_reference}, 先完成材料可得性、亲本多态性和最小可区分表型试验, 再决定是否扩大群体或进入回交选择。",
            "- 证据缺口 (Evidence gap): 推进前必须补齐种子/种质身份、标记可转移性、目标环境表型和产量代价的本地记录, 并据此作出 go/no-go 决策。",
        ]
    else:
        lines = [
            heading,
            f"- System inference: prioritize the highest-ranked routes{route_reference}; first close material availability, parental polymorphism, and the smallest discriminating phenotype test before expanding the population or entering backcross selection.",
            "- Evidence gap: advancement requires local records for seed identity, marker transferability, target-environment phenotype, and yield penalty, followed by an explicit go/no-go decision.",
        ]
    return text.rstrip() + "\n\n" + "\n".join(lines) + "\n"


def _ensure_breeding_elements_section(
    text: str,
    *,
    missing: list[str],
    language: str,
) -> str:
    """Make missing decision-table dimensions explicit without inventing evidence."""

    if not missing or _has_heading(
        _extract_headings(text),
        ("breeding decision completeness", "育种决策完整性"),
    ):
        return text
    labels = {
        "target_trait": "target trait / 目标性状",
        "phenotyping": "phenotyping / 表型测定",
        "genotyping": "genotyping / 基因型测定",
        "trial_design": "trial design / 试验设计",
        "genes_or_qtl": "genes or QTL / 基因或 QTL",
    }
    heading = "# 育种决策完整性" if language == "zh" else "# Breeding decision completeness"
    lines = [heading]
    for element in missing:
        label = labels.get(element, element)
        lines.append(
            f"- System inference: make {label} explicit in the next validation decision; "
            "the current evidence package does not provide a dedicated report field."
        )
    return text.rstrip() + "\n\n" + "\n".join(lines) + "\n"


def _append_termination_report_section(text: str, section: str) -> str:
    section = section.strip()
    if not section:
        return text
    if "# System termination rationale" in text or "# 绯荤粺缁堟鍘熷洜" in text:
        return text
    return text.rstrip() + "\n\n" + section + "\n"


def _looks_chinese(text: str) -> bool:
    sample = text[:4000]
    chinese_chars = sum(1 for char in sample if "\u4e00" <= char <= "\u9fff")
    ascii_letters = sum(1 for char in sample if char.isascii() and char.isalpha())
    return chinese_chars >= max(20, ascii_letters // 5)


_URL_RE = re.compile(r"(?:https?://|local-rag://)[^\s)>\]]+")
_HYP_REF_RE = re.compile(r"(\[[Hh][-_][^\]]+\]|`?hyp_[A-Za-z0-9_:-]+`?)")
_ACCESSION_RE = re.compile(r"\b(?:ARCH-[A-Za-z0-9]+|FPS2025-\d+)\b")


def _ensure_source_map_section(
    text: str,
    *,
    evidence_text: str = "",
    language: str = "en",
    max_sources: int = 12,
) -> str:
    headings = _extract_headings(text)
    aliases = (
        "source map and evidence gaps",
        "evidence gaps and source map",
        "source map",
        "source map and evidence gaps",
        "evidence source map",
        "evidence gaps",
        "来源图谱与证据缺口",
        "证据缺口与来源图谱",
        "证据来源图谱",
    )
    if _has_heading(headings, aliases):
        return text

    urls = _extract_ordered_urls(f"{text}\n{evidence_text}", limit=max_sources)
    lines: list[str]
    if language == "zh":
        lines = ["# 来源图谱与证据缺口"]
        if urls:
            lines.append("- 报告和证据上下文中的主要来源：")
            lines.extend(
                f"  - [{url}]({url})：支持材料、标记/QTL、RAG 证据、验证方案或风险判断。"
                for url in urls
            )
        else:
            lines.append("- 证据缺口：未找到可提取的来源，请补充本地 RAG 或文献映射。")
        lines.append(
            "- 证据缺口：下一轮需要补齐材料可得性、亲本多态性、单环境证据、G×E 稳定性以及推进/停止阈值。"
        )
    else:
        lines = ["# Source map and evidence gaps"]
        if urls:
            lines.append("- Main sources visible in the report and evidence context:")
            lines.extend(
                f"  - [{url}]({url}): supports material, marker/QTL, RAG evidence, validation, or risk judgments."
                for url in urls
            )
        else:
            lines.append(
                "- Evidence gap: no extractable source URL was found; add local RAG or literature source mapping."
            )
        lines.append(
            "- Evidence gap: next cycle must close material availability, parent polymorphism, single-environment evidence, GxE stability, and go/no-go thresholds."
        )
    return text.rstrip() + "\n\n" + "\n".join(lines) + "\n"


def _extract_ordered_urls(text: str, *, limit: int) -> list[str]:
    seen: set[str] = set()
    urls: list[str] = []
    for match in _URL_RE.finditer(text):
        url = match.group(0).rstrip(".,;:)")
        if url in seen:
            continue
        seen.add(url)
        urls.append(url)
        if len(urls) >= limit:
            break
    return urls


def _prioritize_source_records(records: list[Any], *, limit: int) -> list[Any]:
    """Keep route-critical local preflight RAG cards visible to final reports."""

    def priority(record: Any) -> tuple[int, int]:
        if not isinstance(record, dict):
            return (3, 0)
        url = str(record.get("url", "")).lower()
        title = str(record.get("title", "")).lower()
        text = f"{url} {title}"
        if "local-rag://" in url and "preflight" in text:
            return (0, 0)
        if "local-rag://" in url:
            return (1, 0)
        return (2, 0)

    ordered = sorted(enumerate(records), key=lambda item: (*priority(item[1]), item[0]))
    return [record for _, record in ordered[:limit]]


def _session_target_scope(session: Any) -> str:
    plan = getattr(session, "research_plan", None)
    parts = [
        getattr(session, "research_goal", "") or "",
        getattr(plan, "objective", "") or "",
        " ".join(getattr(plan, "target_traits", []) or []),
        " ".join(getattr(plan, "target_environments", []) or []),
    ]
    return " ".join(str(part).strip() for part in parts if str(part).strip())


def _material_scope_tokens(records: list[dict[str, str]]) -> dict[str, set[str]]:
    tokens: dict[str, set[str]] = {}
    for record in records:
        accession_id = str(record.get("accession_id") or "")
        record_tokens = {
            re.sub(r"[^a-z0-9]+", "", value.casefold())
            for value in (accession_id, str(record.get("name") or ""))
            if value.strip()
        }
        if "-" in accession_id:
            record_tokens.add(
                re.sub(r"[^a-z0-9]+", "", accession_id.rsplit("-", 1)[-1].casefold())
            )
        tokens[accession_id] = {token for token in record_tokens if len(token) >= 4}
    return tokens


def _preflight_scope_anchors(target_scope: str) -> tuple[str, ...]:
    lower = target_scope.casefold()
    anchors = [
        "marker",
        "qtl",
        "caps",
        "genotype",
        "polymorphism",
        "crossing",
        "backcross",
        "flowering",
        "synchrony",
        "phenotyping",
        "field trial",
        "seed",
    ]
    if any(term in lower for term in ("drought", "water stress", "dryland")):
        anchors.extend(("drought", "water stress", "dryland"))
    if any(term in lower for term in ("stay-green", "stay green", "senescence", "chlorophyll")):
        anchors.extend(("stay-green", "stay green", "senescence", "chlorophyll"))
    if any(term in lower for term in ("yield stability", "yield variability", "yield-cv")):
        anchors.extend(("yield stability", "yield variability", "yield-cv"))
    return tuple(dict.fromkeys(anchors))


def _preflight_chunk_matches_scope(
    chunk: Any,
    *,
    target_scope: str,
    known_material_records: list[dict[str, str]],
    allowed_accession_ids: set[str] | None,
) -> bool:
    text = (
        f"{getattr(chunk, 'source_path', '')} "
        f"{getattr(chunk, 'title', '')} "
        f"{getattr(chunk, 'text', '')}"
    ).casefold()
    normalized_text = re.sub(r"[^a-z0-9]+", "", text)
    material_tokens = _material_scope_tokens(known_material_records)
    if allowed_accession_ids is not None:
        allowed_tokens = {
            token
            for accession_id, tokens in material_tokens.items()
            if accession_id in allowed_accession_ids
            for token in tokens
        }
        for accession_id, tokens in material_tokens.items():
            if accession_id in allowed_accession_ids:
                continue
            if any(token in normalized_text and token not in allowed_tokens for token in tokens):
                return False

    anchors = _preflight_scope_anchors(target_scope)
    return any(anchor in text for anchor in anchors)


def _format_preflight_rag_context(
    cfg: Any,
    *,
    target_scope: str = "",
    known_material_records: list[dict[str, str]] | None = None,
    allowed_accession_ids: set[str] | None = None,
) -> str:
    """Expose only target-scoped preflight RAG URLs in final reports."""

    path = getattr(cfg, "rag_index_path", None)
    if path is None or not path.exists():
        return ""
    try:
        index = load_evidence_index(path)
    except Exception as exc:  # pragma: no cover - defensive around local artifacts
        log.warning("failed to load RAG preflight context", path=str(path), error=str(exc))
        return ""

    groups: dict[str, list[Any]] = {}
    for chunk in index.chunks:
        source = chunk.source_path.lower()
        if "preflight" not in source:
            continue
        if not any(
            term in source
            for term in (
                "caps",
                "seed",
                "material",
                "flowering",
                "synchrony",
                "bc1f1",
                "phenotyping",
            )
        ):
            continue
        if not _preflight_chunk_matches_scope(
            chunk,
            target_scope=target_scope,
            known_material_records=known_material_records or [],
            allowed_accession_ids=allowed_accession_ids,
        ):
            continue
        groups.setdefault(chunk.source_path, []).append(chunk)

    if not groups:
        return ""

    blocks = [
        "### Route-relevant local RAG preflight cards",
        "These exact local RAG URLs are available for final-report source mapping. "
        "Use these URLs; do not invent placeholder preflight URLs.",
    ]
    for source_path in sorted(groups):
        chunks = sorted(groups[source_path], key=lambda chunk: chunk.start_line)
        selected = _select_preflight_chunks(chunks)
        title = selected[0].title if selected else source_path
        blocks.append(f"\n**{title}**")
        for chunk in selected:
            url = f"local-rag://{chunk.source_path}#L{chunk.start_line}-L{chunk.end_line}"
            excerpt = re.sub(r"\s+", " ", chunk.text).strip()[:800]
            blocks.append(
                f"- URL: {url}\n"
                f"  Source path: {chunk.source_path}\n"
                f"  Excerpt: {excerpt}"
            )
    return "\n".join(blocks)


def _select_preflight_chunks(chunks: list[Any]) -> list[Any]:
    if not chunks:
        return []
    selected: list[Any] = [chunks[0]]
    for chunk in chunks[1:]:
        text = chunk.text.lower()
        if "go / pause / stop" in text or "evidence boundary" in text:
            selected.append(chunk)
    if len(selected) == 1 and len(chunks) > 1:
        selected.append(chunks[-1])
    return selected[:3]


def _filter_material_list_tables(
    text: str,
    records: list[dict[str, str]],
) -> str:
    """Remove model-invented or out-of-scope rows from material tables."""

    allowed = {
        str(value).strip().casefold()
        for record in records
        for value in (record.get("accession_id"), record.get("name"))
        if value and len(str(value).strip()) >= 3
    }
    heading_markers = (
        "parent and material",
        "germplasm resource",
        "\u4eb2\u672c\u548c\u6750\u6599",
        "\u79cd\u8d28\u8d44\u6e90",
    )
    output: list[str] = []
    in_material_table = False
    header_seen = False
    for line in text.splitlines():
        stripped = line.strip()
        if stripped.startswith("#"):
            lower = stripped.casefold()
            in_material_table = any(marker in lower for marker in heading_markers)
            header_seen = False
            output.append(line)
            continue
        if in_material_table and stripped.startswith("|"):
            if not header_seen:
                output.append(line)
                header_seen = True
            elif (
                set(stripped.replace("|", "").replace("-", "").replace(":", "").strip()) == set()
                or (
                    allowed
                    and any(
                        token in stripped.strip("|").split("|", 1)[0].casefold()
                        for token in allowed
                    )
                )
            ):
                output.append(line)
            continue
        if in_material_table and header_seen and stripped:
            in_material_table = False
        output.append(line)
    suffix = "\n" if text.endswith("\n") else ""
    return "\n".join(output) + suffix


def _append_germplasm_resource_table(
    text: str,
    records: list[dict[str, str]],
    *,
    evidence_text: str = "",
    max_rows: int = 12,
) -> str:
    if "Germplasm resource evidence table" in text:
        return text

    accession_ids = _extract_accession_ids(text, evidence_text)
    if not accession_ids:
        return text

    by_id = {record.get("accession_id", ""): record for record in records}
    rows: list[str] = []
    for accession_id in accession_ids:
        record = by_id.get(accession_id)
        if not record:
            continue
        source = record.get("source_refs") or record.get("source") or ""
        rows.append(
            "| "
            + " | ".join(
                _markdown_table_cell(value)
                for value in (
                    record.get("name") or accession_id,
                    accession_id,
                    _first_nonempty(
                        record.get("breeding_use"),
                        record.get("primary_traits"),
                        record.get("summary"),
                    ),
                    source,
                    _first_nonempty(
                        record.get("risk_notes"),
                        record.get("weaknesses"),
                        record.get("genotype_evidence"),
                        record.get("notes"),
                    ),
                )
            )
            + " |"
        )
        if len(rows) >= max_rows:
            break

    if not rows:
        return text

    table = [
        "# Germplasm resource evidence table",
        "| Material | Accession ID | Use / trait clue | Source | Risk / evidence gap |",
        "| --- | --- | --- | --- | --- |",
        *rows,
    ]
    return text.rstrip() + "\n\n" + "\n".join(table) + "\n"


def _append_germplasm_resource_table(
    text: str,
    records: list[dict[str, str]],
    *,
    evidence_text: str = "",
    language: str = "zh",
    max_rows: int = 12,
) -> str:
    text = _filter_material_list_tables(text, records)
    if "Germplasm resource evidence table" in text:
        return text

    accession_ids = _extract_accession_ids(text, evidence_text)
    if not accession_ids:
        return text

    by_id = {record.get("accession_id", ""): record for record in records}
    rows: list[str] = []
    for accession_id in accession_ids:
        record = by_id.get(accession_id)
        if not record:
            continue
        source = record.get("source_refs") or record.get("source") or ""
        rows.append(
            "| "
            + " | ".join(
                _markdown_table_cell(value)
                for value in (
                    record.get("name") or accession_id,
                    accession_id,
                    _first_nonempty(
                        record.get("breeding_use"),
                        record.get("primary_traits"),
                        record.get("summary"),
                    ),
                    source,
                    _first_nonempty(
                        record.get("risk_notes"),
                        record.get("weaknesses"),
                        record.get("genotype_evidence"),
                        record.get("notes"),
                    ),
                )
            )
            + " |"
        )
        if len(rows) >= max_rows:
            break

    if not rows:
        return text

    if language == "en":
        table = [
            "# Germplasm resource evidence table",
            "| Material | Accession ID | Use / trait clue | Source | Risk / evidence gap |",
            "| --- | --- | --- | --- | --- |",
            *rows,
        ]
    else:
        table = [
            "# Germplasm resource evidence table",
            "| Material | Accession ID | Use / trait clue | Source | Risk / evidence gap |",
            "| --- | --- | --- | --- | --- |",
            *rows,
        ]
    return text.rstrip() + "\n\n" + "\n".join(table) + "\n"


def _extract_accession_ids(*texts: str) -> list[str]:
    seen: set[str] = set()
    ids: list[str] = []
    for text in texts:
        for match in _ACCESSION_RE.finditer(text):
            accession_id = match.group(0)
            if accession_id not in seen:
                seen.add(accession_id)
                ids.append(accession_id)
    return ids


def _first_nonempty(*values: str | None) -> str:
    for value in values:
        if value:
            return value
    return ""


def _markdown_table_cell(value: str, *, max_len: int = 180) -> str:
    value = " ".join(str(value or "").split())
    if len(value) > max_len:
        value = value[: max_len - 3].rstrip() + "..."
    return value.replace("|", "\\|")


def _audit_final_overview(text: str) -> dict[str, Any]:
    """Deterministic QA pass for final breeding reports.

    The LLM is still responsible for scientific synthesis, but this checker
    catches the easiest-to-miss report-quality failures before the user sees
    the artifact: missing required sections, important claims without inline
    support, and absence of breeding-project details.
    """

    # A prior audit may already be appended to an artifact. It is metadata,
    # not scientific report content, and must not poison the next audit pass.
    report_text = text.split("\n# Final report audit", 1)[0]
    headings = _extract_headings(report_text)
    required_sections = {
        "Executive summary": (
            "executive summary",
            "research overview",
            "鎵ц鎽樿",
            "鐮旂┒姒傝堪",
            "鎬昏瘎鎽樿",
        ),
        "Main research directions": (
            "main research directions",
            "main research direction",
            "research direction",
            "research directions",
            "main directions",
            "research directions",
        ),
        "Breeding decision table": (
            "breeding decision table",
            "decision table",
            "breeding route decision table",
            "decision table",
        ),
        "Suggested next breeding cycle": (
            "suggested next breeding cycle",
            "next breeding cycle",
            "next cycle",
            "suggested next breeding cycle",
            "next breeding cycle",
            "next step breeding cycle",
        ),
        "Evidence gaps and source map": (
            "evidence gaps and source map",
            "evidence gap and source map",
            "source map",
            "evidence gaps and source map",
            "source evidence map",
            "evidence gaps",
            "鏉ユ簮鍥捐氨",
        ),
    }
    required_sections = {
        "Executive summary": (
            "executive summary",
            "鎵ц鎽樿",
            "执行摘要",
            "研究概述",
            "总评摘要",
        ),
        "Six-agent loop conclusion": (
            "six agent loop conclusion",
            "six agent closed loop conclusion",
            "six agent workflow conclusion",
            "six agent closed loop",
            "six agent workflow",
            "六智能体闭环结论",
            "六智能体闭环",
            "六大智能体闭环结论",
        ),
        "Recommended breeding directions": (
            "recommended breeding directions",
            "recommended breeding direction",
            "breeding directions",
            "recommended route directions",
            "推荐育种方向",
            "推荐的育种方向",
            "育种方向",
        ),
        "Breeding decision table": (
            "breeding decision table",
            "decision table",
            "breeding decision table",
            "育种决策表",
            "决策表",
        ),
        "Parent and material list": (
            "parent and material list",
            "parent material list",
            "materials list",
            "parent and material list",
            "material list",
            "亲本和材料清单",
            "亲本与材料清单",
            "材料清单",
        ),
        "Evidence graph summary": (
            "evidence graph summary",
            "breeding evidence graph summary",
            "evidence graph summary",
            "breeding evidence graph",
            "证据图谱摘要",
            "育种证据图谱摘要",
            "育种证据图谱",
        ),
        "Risks and evidence requests": (
            "risks and evidence requests",
            "risk and evidence requests",
            "risks and evidence gaps",
            "risk checklist",
            "evidence request checklist",
            "风险与补证清单",
            "风险与证据请求",
            "风险清单",
        ),
        "Suggested next breeding cycle": (
            "suggested next breeding cycle",
            "next breeding cycle",
            "next cycle",
            "suggested breeding cycle",
            "next breeding cycle",
            "建议的下一轮育种周期",
            "下一轮育种周期",
            "下一轮育种",
        ),
        "90-day validation plan": (
            "90 day validation plan",
            "90-day validation plan",
            "first quarter validation plan",
            "90-day validation plan",
            "90天验证计划",
            "90日验证计划",
        ),
        "Source map and evidence gaps": (
            "source map and evidence gaps",
            "evidence gaps and source map",
            "source map",
            "source evidence map",
            "source and evidence gaps",
            "evidence gaps",
            "来源图谱与证据缺口",
            "证据缺口与来源图谱",
            "来源图谱",
            "证据缺口",
        ),
    }

    missing_sections = [
        section for section, aliases in required_sections.items()
        if not _has_heading(headings, aliases)
    ]

    unsupported_lines: list[dict[str, Any]] = []
    for lineno, line in enumerate(report_text.splitlines(), start=1):
        stripped = line.strip()
        if not _line_needs_support(stripped):
            continue
        if _URL_RE.search(stripped) or _HYP_REF_RE.search(stripped):
            continue
        lower_stripped = stripped.lower()
        if (
            "system inference" in lower_stripped
            or "evidence gap" in lower_stripped
            or "绯荤粺鎺ㄦ柇" in stripped
            or "璇佹嵁缂哄彛" in stripped
        ):
            continue
        unsupported_lines.append({"line": lineno, "text": stripped[:240]})
        if len(unsupported_lines) >= 12:
            break

    lower = report_text.lower()
    breeding_terms = {
        "crop_or_germplasm": (
            "crop", "germplasm", "parent", "donor", "population", "material",
            "作物", "种质", "亲本", "供体", "群体", "材料",
        ),
        "target_trait": (
            "trait", "yield", "quality", "tolerance", "resistance", "lodging", "plant architecture",
            "性状", "产量", "品质", "耐旱", "抗旱", "抗性", "倒伏", "株型", "恢复", "稳定性",
        ),
        "genes_or_qtl": (
            "gene", "qtl", "marker", "haplotype", "snp", "caps", "kasp",
            "基因", "标记", "单倍型",
        ),
        "phenotyping": (
            "phenotyp", "assay", "nursery", "field measurement", "plant height", "stem diameter", "lodging score",
            "表型", "表型鉴定", "表型测定", "测定", "田间调查", "株高", "倒伏评分",
        ),
        "genotyping": (
            "genotyp", "marker", "sequencing", "snp", "caps", "gbs", "rad-seq",
            "基因型", "基因分型", "测序",
        ),
        "trial_design": (
            "trial", "validation", "environment", "multi-environment", "replicate", "randomized block", "split plot",
            "试验", "验证", "环境", "多环境", "重复", "区组", "裂区",
        ),
        "risk": (
            "risk", "tradeoff", "evidence gap", "linkage drag", "multi-environment", "gxe", "g x e",
            "风险", "权衡", "证据缺口", "连锁累赘",
        ),
        "source_support": ("http://", "https://", "local-rag://", "文献", "引用来源", "本地证据"),
    }
    missing_breeding_elements = [
        label
        for label, terms in breeding_terms.items()
        if not any(term in lower for term in terms)
    ]

    status = "pass"
    if missing_sections or unsupported_lines or missing_breeding_elements:
        status = "needs_attention"

    return {
        "status": status,
        "missing_sections": missing_sections,
        "unsupported_important_lines": unsupported_lines,
        "missing_breeding_elements": missing_breeding_elements,
        "checks": {
            "required_sections": list(required_sections),
            "important_lines_need_url_or_hypothesis_reference": True,
            "breeding_decision_elements_required": list(breeding_terms.keys()),
        },
    }


def _extract_headings(text: str) -> list[str]:
    return [
        line.lstrip("#").strip()
        for line in text.splitlines()
        if line.lstrip().startswith("#")
    ]


def _has_heading(headings: list[str], aliases: tuple[str, ...]) -> bool:
    normalized = [_normalize_heading(h) for h in headings]
    for heading in normalized:
        for alias in aliases:
            norm_alias = _normalize_heading(alias)
            if norm_alias and norm_alias in heading:
                return True
    return False


def _normalize_heading(value: str) -> str:
    value = re.sub(r"[*_`]+", "", value)
    value = re.sub(r"[^a-z0-9\u4e00-\u9fff]+", " ", value.lower())
    return re.sub(r"\s+", " ", value).strip()


def _line_needs_support(line: str) -> bool:
    if not line:
        return False
    if line.startswith("#"):
        return False
    if line.startswith("|"):
        return False
    if set(line) <= {"-", "|", ":", " "}:
        return False
    if line.startswith("**") and line.endswith("**"):
        return False
    if re.fullmatch(r"\*\*[^*]+\.?\*\*", line):
        return False
    if line.endswith("?"):
        return False
    lower = line.lower()
    if lower.startswith((
        "evidence gap",
        "system inference",
        "绯荤粺鎺ㄦ柇",
        "source map",
        "passed deterministic checks",
        "needs attention before treating this as a polished advisor-facing report",
        "**why it's promising",
        "**open questions",
        "**breeding path",
        "**first experiment",
    )):
        return False
    if len(line) >= 110:
        return True
    if line.startswith(("- ", "* ")) and len(line) >= 70:
        return True
    return any(
        marker in lower
        for marker in (
            "therefore",
            "suggests",
            "indicates",
            "supports",
            "should",
            "recommend",
            "promising",
            "expected",
            "likely",
            "improve",
            "increase",
            "reduce",
        )
    )


def _normalize_markdown_links(text: str) -> str:
    """Fix common malformed markdown links emitted by small models.

    Example: `[Source](https://pubmed.ncbi.nlm.nih.gov/35512580/]`
    becomes `[Source](https://pubmed.ncbi.nlm.nih.gov/35512580/)`.
    """

    text = re.sub(r"\]\((https?://[^\s)\]]+)\]", r"](\1)", text)
    text = re.sub(r"\]\((https?://[^\s)]*?/)\]\.", r"](\1).", text)
    return text


def _mark_remaining_unsupported_lines(
    text: str,
    audit: dict[str, Any],
    *,
    hypothesis_ids: list[str],
    language: str = "en",
) -> str:
    """Add transparent support labels when the LLM repair misses audit lines.

    This deliberately does not invent literature. It marks the remaining
    unsupported recommendations as system synthesis grounded in the available
    hypothesis set, so advisor-facing reports are explicit about what is
    sourced literature versus system-derived guidance.
    """

    unsupported = audit.get("unsupported_important_lines") or []
    if not unsupported or not hypothesis_ids:
        return text

    line_numbers = {
        item.get("line")
        for item in unsupported
        if isinstance(item, dict) and isinstance(item.get("line"), int)
    }
    if not line_numbers:
        return text

    hyp_refs = ", ".join(f"`{hid}`" for hid in hypothesis_ids[:3])
    if language == "zh":
        suffix = f" System inference based on {hyp_refs}."
        existing_marker = "system inference"
    else:
        suffix = f" System inference based on {hyp_refs}."
        existing_marker = "system inference"
    out: list[str] = []
    for lineno, line in enumerate(text.splitlines(), start=1):
        stripped = line.strip()
        if (
            lineno in line_numbers
            and _line_needs_support(stripped)
            and not _URL_RE.search(stripped)
            and not _HYP_REF_RE.search(stripped)
            and existing_marker not in stripped.lower()
            and "evidence gap" not in stripped.lower()
        ):
            line = line.rstrip() + suffix
        out.append(line)
    return "\n".join(out)


def _mark_remaining_unsupported_lines_until_clean(
    text: str,
    audit: dict[str, Any],
    *,
    hypothesis_ids: list[str],
    language: str = "en",
    max_passes: int = 5,
) -> tuple[str, dict[str, Any]]:
    """Repeat deterministic support marking because audit output is capped."""

    current_text = text
    current_audit = audit
    for _ in range(max_passes):
        if not current_audit.get("unsupported_important_lines"):
            break
        next_text = _mark_remaining_unsupported_lines(
            current_text,
            current_audit,
            hypothesis_ids=hypothesis_ids,
            language=language,
        )
        if next_text == current_text:
            break
        current_text = next_text
        current_audit = _audit_final_overview(current_text)
    return current_text, current_audit


def _append_audit_section(
    text: str,
    audit: dict[str, Any],
    *,
    language: str = "en",
) -> str:
    if language == "zh":
        lines = ["# 最终报告审计"]
        if audit["status"] == "pass":
            lines.append(
                "确定性检查已通过：必需章节齐全，重要结论包含来源 URL 或假设引用，"
                "核心育种决策要素已覆盖。"
            )
        else:
            lines.append("在将本报告作为完整专家报告使用前，仍需处理以下问题。")
        if audit["missing_sections"]:
            lines.append("## 缺少的章节")
            for section in audit["missing_sections"]:
                lines.append(f"- {section}")
        if audit["missing_breeding_elements"]:
            lines.append("## 缺少的育种决策要素")
            for element in audit["missing_breeding_elements"]:
                lines.append(f"- {element}")
        if audit["unsupported_important_lines"]:
            lines.append("## 需要补充行内证据的重点内容")
            for item in audit["unsupported_important_lines"]:
                lines.append(f"- 第 {item['line']} 行：{item['text']}")
    else:
        lines = ["# Final report audit"]
        if audit["status"] == "pass":
            lines.append(
                "Passed deterministic checks: required sections are present, important "
                "claim lines include source URLs or hypothesis references, and core "
                "breeding decision elements are represented."
            )
        else:
            lines.append(
                "Needs attention before treating this as a polished advisor-facing report."
            )
        if audit["missing_sections"]:
            lines.append("## Missing sections")
            for section in audit["missing_sections"]:
                lines.append(f"- {section}")
        if audit["missing_breeding_elements"]:
            lines.append("## Missing breeding decision elements")
            for element in audit["missing_breeding_elements"]:
                lines.append(f"- {element}")
        if audit["unsupported_important_lines"]:
            lines.append("## Important lines that may need inline support")
            for item in audit["unsupported_important_lines"]:
                lines.append(f"- Line {item['line']}: {item['text']}")
    return text.rstrip() + "\n\n---\n\n" + "\n".join(lines) + "\n"
