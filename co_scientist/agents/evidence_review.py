"""Risk Reviewer evidence review service."""

from __future__ import annotations

from datetime import UTC, datetime
from typing import Any

from .. import ids
from ..llm.anthropic_client import AgentCallSpec, CachedBlock, CallContext
from ..llm.prompts import render
from ..llm.routing import route
from ..llm.tool_loop import ToolLoopExhausted, run_tool_loop
from ..models import Review, ReviewScores, Task, TaskResult
from ..safety.quoting import quote_hypothesis
from ..storage.artifacts import read_json, write_json
from ..storage.repos import hypotheses as hyp_repo
from ..storage.repos import reviews as rev_repo
from ..storage.repos import sessions as sess_repo
from .base import BaseAgent
from .schemas import RECORD_REVIEW_TOOL


class EvidenceReviewAgent(BaseAgent):
    name = "Risk Reviewer"

    async def execute(self, task: Task) -> TaskResult:
        kind = task.payload.get("kind", "full")
        hypothesis_id = task.target_id
        if not hypothesis_id:
            raise ValueError("Risk Reviewer evidence review requires target_id (hypothesis_id)")

        session = await sess_repo.fetch(self.deps.db, task.session_id)
        if session is None:
            raise RuntimeError(f"session {task.session_id} missing")
        h = await hyp_repo.fetch(self.deps.db, hypothesis_id)
        if h is None:
            raise RuntimeError(f"hypothesis {hypothesis_id} missing")
        evidence_package_path, breeding_evidence_graph_path = await _hypothesis_evidence_paths(
            self.deps.cfg,
            h.artifact_path,
        )

        if kind != "full":
            raise NotImplementedError(f"review kind {kind!r} lands in a later milestone")

        review_language = "zh" if _extract_marker_block(h.full_text, "HYPOTHESIS_ZH") else "en"
        hypothesis_text = _hypothesis_text_for_language(h.full_text, review_language)
        prompt = render(
            "risk_reviewer.evidence_review",
            goal=session.research_plan.objective,
            preferences="; ".join(session.research_plan.preferences),
            hypothesis_id=h.id,
            hypothesis_text=quote_hypothesis(hypothesis_text, id_=h.id),
            output_language="Chinese" if review_language == "zh" else "English",
            articles_block=(
                "Use the available search tools (web_search, pubmed_search, "
                "arxiv_search, europe_pmc_search, web_fetch) to gather supporting "
                "and contradicting evidence. Use germplasm_search when the review "
                "depends on whether proposed parents, accessions, or donor materials "
                "are plausible local resource clues. Use crop_kg_search when the "
                "review depends on minor-grain relationships among germplasm, traits, "
                "genes/QTL, markers, environments, validation plans, or risks. "
                "Cite URLs that you actually fetched for literature evidence; treat "
                "germplasm_search and crop_kg_search results as local clues and "
                "preserve their IDs, accession IDs, edges, and source_refs."
            ),
        )

        sys_blocks = [
            CachedBlock(self._system_prompt_header(), cache=True),
            CachedBlock(
                f"# Research goal\n{session.research_goal}\n\n"
                f"# Preferences\n{'; '.join(session.research_plan.preferences)}",
                cache=True,
            ),
        ]
        user_blocks = [CachedBlock(prompt, cache=False)]

        r = route(self.deps.cfg, "risk_reviewer", "evidence_review")
        tools = [*self.deps.tools.anthropic_tools_for("risk_reviewer"), RECORD_REVIEW_TOOL]

        spec = AgentCallSpec(
            route=r,
            system_blocks=sys_blocks,
            user_blocks=user_blocks,
            tools=tools,
            tool_choice={"type": "auto"},
            max_output_tokens=8192,
        )
        ctx = CallContext(
            session_id=task.session_id, task_id=task.id,
            agent="risk_reviewer", action=task.action, mode="evidence_review",
        )

        try:
            loop_result = await run_tool_loop(
                self.deps.llm,
                spec=spec, ctx=ctx,
                registry=self.deps.tools,
                max_iters=self.deps.cfg.tool_loop.risk_reviewer_evidence_max_iters,
                parallel_cap=self.deps.cfg.tool_loop.parallel_cap,
                tool_timeout_s=self.deps.cfg.tool_loop.tool_timeout_seconds,
                force_terminal_tool="record_review",
            )
        except ToolLoopExhausted as e:
            raise RuntimeError(f"Risk Reviewer evidence review exhausted tool loop: {e}") from e

        record = self._final_tool_use(loop_result.response, "record_review")
        if record is None:
            raise RuntimeError("Risk Reviewer evidence review did not call record_review")

        # Drop evidence entries whose URL we never saw — keep the review honest.
        seen = loop_result.seen_urls
        record["evidence"] = [
            e for e in record.get("evidence", [])
            if isinstance(e, dict) and e.get("url") in seen
        ]
        if not record["evidence"]:
            record["evidence"] = _fallback_evidence_from_sources(
                loop_result.observed_sources,
                seen,
            )

        review_id = ids.review_id(h.id, "full", iteration=0)
        artifact_path = await write_json(
            self.deps.cfg, session.id, "reviews", review_id,
            {"hypothesis_id": h.id, "record": record},
        )
        body_md = _render_review_md(record, language=review_language)
        review = Review(
            id=review_id,
            hypothesis_id=h.id,
            session_id=session.id,
            created_at=datetime.now(UTC),
            kind="full",
            verdict=record.get("verdict"),       # type: ignore[arg-type]
            scores=ReviewScores(
                novelty=record.get("novelty"),
                correctness=record.get("correctness"),
                testability=record.get("testability"),
                feasibility=record.get("feasibility"),
            ),
            assumptions=record.get("assumptions") or [],
            evidence=record.get("evidence") or [],
            body=body_md,
            artifact_path=artifact_path,
        )
        await rev_repo.insert(self.deps.db, review)
        # Only promote draft → reviewed. If review re-fires on an
        # already-ranked/evolved/pinned hypothesis we must not drag it back.
        await hyp_repo.set_state_if(
            self.deps.db, h.id, new_state="reviewed", expected_states=("draft",),
        )

        return TaskResult(
            kind="evidence_review_completed",
            review_ids=[review_id],
            hypothesis_ids=[h.id],
            extra={
                "verdict": record.get("verdict"),
                "evidence_package_path": evidence_package_path,
                "breeding_evidence_graph_path": breeding_evidence_graph_path,
            },
        )


async def _hypothesis_evidence_paths(cfg, artifact_path: str) -> tuple[str | None, str | None]:
    try:
        payload = await read_json(cfg, artifact_path)
    except Exception:
        return None, None
    record = payload.get("record", payload) if isinstance(payload, dict) else {}
    if not isinstance(record, dict):
        return None, None
    return record.get("evidence_package_path"), record.get("breeding_evidence_graph_path")


def _render_review_md(record: dict[str, Any]) -> str:
    parts: list[str] = ["# Review"]
    if record.get("verdict"):
        parts.append(f"**Verdict.** {record['verdict']}")
    scores = []
    for s in ("novelty", "correctness", "testability", "feasibility"):
        if record.get(s) is not None:
            scores.append(f"{s} {record[s]:.2f}")
    if scores:
        parts.append("**Scores.** " + " · ".join(scores))
    breeding_scores = []
    for s in (
        "genetic_gain_potential",
        "selection_actionability",
        "field_trial_feasibility",
        "gxe_risk",
        "phenotyping_cost",
        "breeding_cycle_time",
        "deployment_risk",
    ):
        if record.get(s) is not None:
            breeding_scores.append(f"{s} {record[s]:.2f}")
    if breeding_scores:
        parts.append("**Breeding scores.** " + " · ".join(breeding_scores))
    if record.get("assumptions"):
        parts.append("## Assumptions")
        for a in record["assumptions"]:
            parts.append(
                f"- *{a.get('plausibility','?')}*: {a.get('assumption','')}\n  "
                f"  {a.get('rationale','')}"
            )
    if record.get("evidence"):
        parts.append("## Evidence")
        for e in record["evidence"]:
            parts.append(f"- {e.get('claim','')} — {e.get('url','')}\n  > {e.get('excerpt','')}")
    if record.get("notes"):
        parts.append(f"## Notes\n{record['notes']}")
    return "\n\n".join(parts)


def _hypothesis_text_for_language(text: str, language: str) -> str:
    marker = "HYPOTHESIS_ZH" if language == "zh" else "HYPOTHESIS_EN"
    block = _extract_marker_block(text, marker)
    return block if block is not None else text


def _extract_marker_block(text: str, name: str) -> str | None:
    start = f"<!-- {name}_START -->"
    end = f"<!-- {name}_END -->"
    start_idx = text.find(start)
    if start_idx < 0:
        return None
    body_start = start_idx + len(start)
    end_idx = text.find(end, body_start)
    if end_idx < 0:
        return None
    return text[body_start:end_idx].strip()


def _render_review_md(record: dict[str, Any], *, language: str = "en") -> str:
    labels = (
        {
            "title": "审稿意见",
            "verdict": "结论",
            "scores": "评分",
            "breeding_scores": "育种评分",
            "assumptions": "假设前提",
            "evidence": "证据",
            "notes": "备注",
        }
        if language == "zh"
        else {
            "title": "Review",
            "verdict": "Verdict",
            "scores": "Scores",
            "breeding_scores": "Breeding scores",
            "assumptions": "Assumptions",
            "evidence": "Evidence",
            "notes": "Notes",
        }
    )

    parts: list[str] = [f"# {labels['title']}"]
    if record.get("verdict"):
        parts.append(f"**{labels['verdict']}.** {record['verdict']}")
    scores = []
    for s in ("novelty", "correctness", "testability", "feasibility"):
        if record.get(s) is not None:
            scores.append(f"{s} {_format_score(record[s])}")
    if scores:
        parts.append(f"**{labels['scores']}.** " + " / ".join(scores))
    breeding_scores = []
    for s in (
        "genetic_gain_potential",
        "selection_actionability",
        "field_trial_feasibility",
        "gxe_risk",
        "phenotyping_cost",
        "breeding_cycle_time",
        "deployment_risk",
    ):
        if record.get(s) is not None:
            breeding_scores.append(f"{s} {_format_score(record[s])}")
    if breeding_scores:
        parts.append(f"**{labels['breeding_scores']}.** " + " / ".join(breeding_scores))
    if record.get("assumptions"):
        parts.append(f"## {labels['assumptions']}")
        for a in record["assumptions"]:
            parts.append(
                f"- *{a.get('plausibility','?')}*: {a.get('assumption','')}\n  "
                f"  {a.get('rationale','')}"
            )
    if record.get("evidence"):
        parts.append(f"## {labels['evidence']}")
        for e in record["evidence"]:
            parts.append(f"- {e.get('claim','')} - {e.get('url','')}\n  > {e.get('excerpt','')}")
    if record.get("notes"):
        parts.append(f"## {labels['notes']}\n{record['notes']}")
    return "\n\n".join(parts)


def _format_score(value: Any) -> str:
    try:
        return f"{float(value):.2f}"
    except (TypeError, ValueError):
        return str(value)


def _fallback_evidence_from_sources(
    sources: list[dict[str, str]],
    seen: set[str],
    *,
    limit: int = 5,
) -> list[dict[str, str]]:
    evidence = []
    for source in sources:
        url = source.get("url")
        if not url:
            continue
        evidence.append(
            {
                "claim": f"Tool-observed source consulted during hypothesis review: {source.get('title') or url}",
                "url": url,
                "excerpt": source.get("excerpt") or (
                    "URL observed in a literature/search/fetch tool result during review."
                ),
            }
        )
        if len(evidence) >= limit:
            return evidence
    for url in sorted(set(seen)):
        if any(e["url"] == url for e in evidence):
            continue
        evidence.append(
            {
                "claim": "Tool-observed source consulted during hypothesis review.",
                "url": url,
                "excerpt": (
                    "URL observed in a literature/search/fetch tool result during "
                    "review; inspect the associated transcript or paper artifact "
                    "for the exact supporting passage."
                ),
            }
        )
        if len(evidence) >= limit:
            break
    return evidence
