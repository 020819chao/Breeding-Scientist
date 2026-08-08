"""Breeding Designer initial hypothesis service.

M3 ships the `literature` strategy. `debate` / `assumption` / `feedback_driven`
hook into the same machinery and land in M5+.
"""

from __future__ import annotations

from collections.abc import Iterable
from datetime import UTC, datetime
from typing import Any

import numpy as np

from .. import ids
from ..llm.anthropic_client import AgentCallSpec, CachedBlock, CallContext
from ..llm.prompts import render
from ..llm.routing import route
from ..llm.tool_loop import ToolLoopExhausted, run_tool_loop
from ..logging import get_logger
from ..models import CitedPaper, Hypothesis, ResearchPlan, Task, TaskResult
from ..safety.quoting import quote_untrusted
from ..storage.artifacts import read_json, write_json
from ..storage.repos import embeddings as emb_repo
from ..storage.repos import feedback as fb_repo
from ..storage.repos import hypotheses as hyp_repo
from ..storage.repos import sessions as sess_repo
from ..vectors.embedder import make_embedder
from ..vectors.store import FaissStore
from .base import AgentDeps, BaseAgent
from .schemas import RECORD_HYPOTHESIS_TOOL

log = get_logger("breeding_designer")


class BreedingDesignerAgent(BaseAgent):
    name = "Breeding Designer"

    async def execute(self, task: Task) -> TaskResult:
        strategy = task.payload.get("strategy", "literature")
        n_target = int(task.payload.get("n", 3))

        session = await sess_repo.fetch(self.deps.db, task.session_id)
        if session is None:
            raise RuntimeError(f"session {task.session_id} missing")
        plan = session.research_plan

        if strategy != "literature":
            # M3 ships only the literature strategy.
            raise NotImplementedError(f"strategy {strategy!r} lands in a later milestone")

        # 1. Render the prompt and run the tool loop with `record_hypothesis` available.
        articles_block = (
            "You will gather literature using the available tools (web_search, "
            "pubmed_search, arxiv_search, europe_pmc_search, web_fetch) and local "
            "germplasm clues using germplasm_search when material or parent choice "
            "matters. Use crop_kg_search when the idea needs to connect minor-grain "
            "germplasm, traits, genes/QTL, markers, environments, validation plans, "
            "or risks. Pull abstracts for the most relevant items, then synthesize. "
            "Use evidence_search for local curated papers, notes, field observations, "
            "or advisor-provided materials that may support or challenge the breeding route. "
            "For grain breeding goals, explicitly search across crop genetics, "
            "QTL/GWAS, genomic selection, phenomics, agronomy, stress physiology, "
            "field trial evidence, and available germplasm resources. Treat "
            "germplasm_search and crop_kg_search results as local resource or graph "
            "clues rather than validated literature evidence; do not infer unlisted "
            "markers, availability, causal effects, or breeding value from them. After "
            "you have surveyed the evidence, call "
            "`record_hypothesis` exactly once with your proposed hypothesis.\n\n"
            "IMPORTANT — interpreting empty search results: an empty result set "
            "(no hits) is positive evidence that the literature you searched for "
            "does not exist. When the goal requires a candidate with NO prior "
            "published evidence, empty searches CONFIRM novelty — they are a "
            "reason to PROCEED, not to keep searching. Do not chase confirmation "
            "you will never get. After at most 2-3 searches that return no "
            "relevant hits for a candidate, treat its novelty as established and "
            "call `record_hypothesis`. A recorded hypothesis backed by a few "
            "empty searches is far better than running out of turns with nothing."
        )

        prompt = render(
            "breeding_designer.literature",
            goal=plan.objective,
            preferences="; ".join(plan.preferences),
            articles_with_reasoning=articles_block,
            instructions=(
                "Propose ONE hypothesis (the strongest you can justify) and "
                "register it via the record_hypothesis tool. Do not propose more "
                "than one — additional hypotheses come from separate design-step calls. "
                "You MUST end this task by calling record_hypothesis; do not keep "
                "searching indefinitely. Budget your literature search to a handful "
                "of queries, then commit. Frame the hypothesis as a breeding-actionable "
                "idea: name the crop or germplasm class when possible, the target "
                "trait(s), candidate genes/QTL/physiological mechanisms or management "
                "interactions, the selection or crossing strategy, and the expected "
                "field-measurable gain."
            ),
        )
        _ = n_target  # n_target controls how many parallel design-step tasks are enqueued, not per-call output

        evidence_context = await _load_evidence_package_context(
            self.deps.cfg,
            task.payload.get("evidence_package_path"),
        )
        iteration_context = await _load_iteration_decision_context(
            self.deps.cfg,
            task.payload.get("iteration_decision_path"),
        )
        route_revision_intent_context = _build_payload_route_revision_intent_context(
            task.payload
        )
        validation_context = await _load_validation_plan_context(
            self.deps.cfg,
            task.payload.get("validation_plan_path"),
        )
        risk_context = await _load_risk_review_context(
            self.deps.cfg,
            task.payload.get("risk_review_path"),
        )

        sys_blocks = [
            CachedBlock(self._system_prompt_header(), cache=True),
            CachedBlock(
                _build_session_context(session.research_goal, plan,
                                       await _latest_system_feedback(self.deps, session.id)),
                cache=True,
            ),
        ]
        if evidence_context:
            sys_blocks.append(CachedBlock(evidence_context, cache=True))
        if iteration_context:
            sys_blocks.append(CachedBlock(iteration_context, cache=True))
        if route_revision_intent_context:
            sys_blocks.append(CachedBlock(route_revision_intent_context, cache=True))
        if validation_context:
            sys_blocks.append(CachedBlock(validation_context, cache=True))
        if risk_context:
            sys_blocks.append(CachedBlock(risk_context, cache=True))
        user_blocks = [CachedBlock(prompt, cache=False)]

        r = route(self.deps.cfg, "breeding_designer", "literature")
        tools = [*self.deps.tools.anthropic_tools_for("breeding_designer"), RECORD_HYPOTHESIS_TOOL]

        spec = AgentCallSpec(
            route=r,
            system_blocks=sys_blocks,
            user_blocks=user_blocks,
            tools=tools,
            tool_choice={"type": "auto"},
            # A full record_hypothesis payload (statement + mechanism + entities
            # + outcomes + novelty + citations) is large; verbose / reasoning
            # models overran the old 4096 cap mid-JSON, so the arguments string
            # was truncated and unparseable. 8192 leaves room to complete it.
            max_output_tokens=16384,
        )
        ctx = CallContext(
            session_id=task.session_id, task_id=task.id,
            agent="breeding_designer", action=task.action, mode="literature",
        )

        try:
            loop_result = await run_tool_loop(
                self.deps.llm,
                spec=spec, ctx=ctx,
                registry=self.deps.tools,
                max_iters=self.deps.cfg.tool_loop.breeding_designer_max_iters,
                parallel_cap=self.deps.cfg.tool_loop.parallel_cap,
                tool_timeout_s=self.deps.cfg.tool_loop.tool_timeout_seconds,
                force_terminal_tool="record_hypothesis",
            )
        except ToolLoopExhausted as e:
            raise RuntimeError(f"Breeding Designer exhausted tool loop: {e}") from e

        # 2. Extract record_hypothesis from the final assistant message.
        record = self._final_tool_use(loop_result.response, "record_hypothesis")
        if record is None:
            raise RuntimeError("Breeding Designer did not call record_hypothesis")

        # 3. Validate every citation URL is in the union of URLs seen during the loop.
        record["citations"] = _filter_to_seen_urls(record.get("citations", []), loop_result.seen_urls)
        if not record["citations"]:
            record["citations"] = _fallback_citations_from_sources(
                loop_result.observed_sources,
                loop_result.seen_urls,
            )
        await _attach_evidence_provenance(
            self.deps.cfg,
            record,
            task.payload.get("evidence_package_path"),
        )
        await _attach_validation_and_risk_provenance(
            self.deps.cfg,
            record,
            validation_plan_path=task.payload.get("validation_plan_path"),
            risk_review_path=task.payload.get("risk_review_path"),
        )
        _attach_iteration_parentage(record, task.payload)
        _attach_breeding_design_card_audit(record)

        # 4. Persist + embed + dedup-check.
        hid, was_new = await self._persist(session.id, record, strategy="literature")
        return TaskResult(
            kind="hypothesis_created",
            hypothesis_ids=[hid] if was_new else [],
            extra={"tool_calls": loop_result.tool_calls, "iterations": loop_result.iterations},
        )

    # ---------------------------------------------------------------- #

    async def _persist(
        self, session_id: str, record: dict[str, Any], *, strategy: str
    ) -> tuple[str, bool]:
        statement = _primary_statement(record)
        if not statement:
            raise ValueError("record_hypothesis: missing statement")

        origin = f"breeding_designer/{strategy}"
        hid = ids.hypothesis_id(session_id, origin, statement)
        summary = (
            statement
            + "\n\n"
            + _primary_mechanism(record)
            + "\n\n"
            + _render_breeding_context_text(record.get("breeding_context") or {})
        )
        full_text = _render_hypothesis_md(record)

        # Write the JSON artifact first so the row points at a real file.
        artifact_path = await write_json(
            self.deps.cfg, session_id, "hypotheses", hid,
            {"strategy": strategy, "record": record},
        )

        citations = [
            CitedPaper(
                title=c.get("title", ""),
                url=c.get("url", ""),
                excerpt=c.get("excerpt"),
                doi=c.get("doi"),
                year=c.get("year"),
            )
            for c in record.get("citations", [])
            if isinstance(c, dict) and c.get("url")
        ]

        # Step 1: embed + near-neighbour check (does NOT mutate FAISS).
        try:
            dup_id, embed_payload = await self._dedup_query(session_id, summary)
        except Exception as e:
            log.warning("dedup_query_failed", err=str(e))
            dup_id, embed_payload = None, None

        if dup_id is not None and dup_id != hid:
            # Found a near-duplicate already in this session: skip insert + skip FAISS.
            return dup_id, False

        # Step 2: insert the hypothesis row. Deterministic IDs make this idempotent.
        h = Hypothesis(
            id=hid,
            session_id=session_id,
            created_at=datetime.now(UTC),
            created_by="breeding_designer",
            strategy=strategy,        # type: ignore[arg-type]
            parent_ids=record.get("parent_ids") or [],
            title=_primary_title(record)[:300],
            summary=statement[:1000],
            full_text=full_text,
            citations=citations,
            artifact_path=artifact_path,
            state="draft",
        )
        inserted = await hyp_repo.insert(self.deps.db, h)

        # Step 3: only add to FAISS if we actually inserted a new row, so FAISS and
        # the hypotheses table can never disagree (FK in embeddings_meta enforces it).
        if inserted and embed_payload is not None:
            try:
                await self._dedup_commit(session_id, hid, embed_payload)
            except Exception as e:
                log.warning("dedup_commit_failed", hypothesis_id=hid, err=str(e))

        return hid, inserted

    async def _dedup_query(
        self, session_id: str, text: str
    ) -> tuple[str | None, dict[str, Any] | None]:
        """Read-only: embed + nearest-neighbour search. No FAISS mutation.

        Returns (existing_duplicate_id_or_None, embed_payload_for_later_commit).
        """
        try:
            embedder = make_embedder(self.deps.cfg)
        except (RuntimeError, ValueError):
            return None, None
        vec = await embedder.embed([text])
        if vec.size == 0:
            return None, None
        v = vec[0]
        store = FaissStore(self.deps.cfg, session_id, dim=embedder.dim)
        await store.load_or_create()
        nearest = await store.search(np.asarray(v), k=1)
        thr = self.deps.cfg.vectors.dedup_cosine_threshold
        if nearest and nearest[0][1] >= thr:
            return nearest[0][0], None
        payload = {
            "vector": np.asarray(v),
            "model": embedder.model,
            "dim": embedder.dim,
            "text_hash": ids.text_hash(text),
        }
        return None, payload

    async def _dedup_commit(
        self, session_id: str, hypothesis_id: str, payload: dict[str, Any]
    ) -> None:
        """Write-side of dedup: add to FAISS + register the embedding."""
        store = FaissStore(self.deps.cfg, session_id, dim=payload["dim"])
        await store.load_or_create()
        offset = await store.add(hypothesis_id, payload["vector"])
        await store.save()
        await emb_repo.upsert(
            self.deps.db,
            id_=ids.embedding_id(hypothesis_id, payload["model"]),
            session_id=session_id,
            hypothesis_id=hypothesis_id,
            model=payload["model"],
            dim=payload["dim"],
            faiss_offset=offset,
            text_hash=payload["text_hash"],
        )


# --------------------------------------------------------------------------- #
# helpers


def _filter_to_seen_urls(
    citations: list[dict[str, Any]], seen: Iterable[str]
) -> list[dict[str, Any]]:
    seen_set = set(seen)
    return [c for c in citations if isinstance(c, dict) and c.get("url") in seen_set]


def _fallback_citations_from_sources(
    sources: Iterable[dict[str, str]],
    seen: Iterable[str],
    *,
    limit: int = 5,
) -> list[dict[str, Any]]:
    """Preserve real tool-observed URLs when the model emits an empty citation list.

    This is intentionally conservative: sources are copied only from tool
    results, and if a tool supplied no title/excerpt we use a transparent
    placeholder rather than inventing a bibliographic claim.
    """
    citations = []
    for source in sources:
        url = source.get("url")
        if not url:
            continue
        citations.append(
            {
                "title": source.get("title") or "Tool-observed literature/source URL",
                "url": url,
                "excerpt": source.get("excerpt") or (
                    "URL observed in a literature/search/fetch tool result during "
                    "Breeding Designer hypothesis design."
                ),
            }
        )
        if len(citations) >= limit:
            return citations
    for url in sorted(set(seen)):
        if any(c["url"] == url for c in citations):
            continue
        citations.append(
            {
                "title": "Tool-observed literature/source URL",
                "url": url,
                "excerpt": (
                    "URL observed in a literature/search/fetch tool result during "
                    "Breeding Designer hypothesis design; inspect the associated transcript or "
                    "paper artifact for the exact supporting passage."
                ),
            }
        )
        if len(citations) >= limit:
            break
    return citations


def _primary_title(record: dict[str, Any]) -> str:
    return str(record.get("title_zh") or record.get("title") or record.get("title_en") or "")


def _primary_statement(record: dict[str, Any]) -> str:
    return str(
        record.get("statement_zh")
        or record.get("statement")
        or record.get("statement_en")
        or record.get("title_zh")
        or record.get("title")
        or ""
    )


def _primary_mechanism(record: dict[str, Any]) -> str:
    return str(record.get("mechanism_zh") or record.get("mechanism") or record.get("mechanism_en") or "")


def _render_hypothesis_md(record: dict[str, Any]) -> str:
    if _has_bilingual_hypothesis_fields(record):
        zh = _render_hypothesis_variant_md(record, language="zh")
        en = _render_hypothesis_variant_md(record, language="en")
        return (
            "<!-- HYPOTHESIS_ZH_START -->\n"
            f"{zh}\n"
            "<!-- HYPOTHESIS_ZH_END -->\n\n"
            "<!-- HYPOTHESIS_EN_START -->\n"
            f"{en}\n"
            "<!-- HYPOTHESIS_EN_END -->"
        )

    parts: list[str] = []
    if record.get("title"):
        parts.append(f"# {record['title']}")
    parts.append(f"**Hypothesis.** {record.get('statement', '')}")
    if record.get("breeding_context"):
        parts.append(_render_breeding_context_md(record["breeding_context"]))
    if record.get("mechanism"):
        parts.append(f"## Mechanism\n{record['mechanism']}")
    if record.get("entities"):
        parts.append("## Entities\n- " + "\n- ".join(record["entities"]))
    if record.get("anticipated_outcomes"):
        parts.append(f"## Anticipated outcomes\n{record['anticipated_outcomes']}")
    if record.get("novelty_argument"):
        parts.append(f"## Novelty\n{record['novelty_argument']}")
    if record.get("citations"):
        parts.append("## Citations")
        for c in record["citations"]:
            year = f" ({c.get('year')})" if c.get("year") else ""
            parts.append(f"- {c.get('title','(no title)')}{year} — {c.get('url','')}")
    return "\n\n".join(parts)


def _has_bilingual_hypothesis_fields(record: dict[str, Any]) -> bool:
    return any(
        record.get(key)
        for key in (
            "title_zh",
            "title_en",
            "statement_zh",
            "statement_en",
            "mechanism_zh",
            "mechanism_en",
        )
    )


def _render_hypothesis_variant_md(record: dict[str, Any], *, language: str) -> str:
    suffix = "_zh" if language == "zh" else "_en"
    title = record.get(f"title{suffix}") or record.get("title") or record.get("title_en") or ""
    statement = record.get(f"statement{suffix}") or record.get("statement") or record.get("statement_en") or ""
    mechanism = record.get(f"mechanism{suffix}") or record.get("mechanism") or record.get("mechanism_en") or ""
    outcomes = (
        record.get(f"anticipated_outcomes{suffix}")
        or record.get("anticipated_outcomes")
        or record.get("anticipated_outcomes_en")
        or ""
    )
    novelty = (
        record.get(f"novelty_argument{suffix}")
        or record.get("novelty_argument")
        or record.get("novelty_argument_en")
        or ""
    )

    if language == "zh":
        labels = {
            "hypothesis": "假设",
            "mechanism": "机制",
            "entities": "实体",
            "outcomes": "预期结果",
            "novelty": "新颖性",
            "citations": "引用来源",
        }
    else:
        labels = {
            "hypothesis": "Hypothesis",
            "mechanism": "Mechanism",
            "entities": "Entities",
            "outcomes": "Anticipated outcomes",
            "novelty": "Novelty",
            "citations": "Citations",
        }

    parts: list[str] = []
    if title:
        parts.append(f"# {title}")
    parts.append(f"**{labels['hypothesis']}.** {statement}")
    context = record.get(f"breeding_context{suffix}") or record.get("breeding_context")
    if context:
        parts.append(_render_breeding_context_md(context, language=language))
    if mechanism:
        parts.append(f"## {labels['mechanism']}\n{mechanism}")
    if record.get("entities"):
        parts.append(f"## {labels['entities']}\n- " + "\n- ".join(record["entities"]))
    if outcomes:
        parts.append(f"## {labels['outcomes']}\n{outcomes}")
    if novelty:
        parts.append(f"## {labels['novelty']}\n{novelty}")
    if record.get("citations"):
        parts.append(f"## {labels['citations']}")
        for c in record["citations"]:
            year = f" ({c.get('year')})" if c.get("year") else ""
            parts.append(f"- {c.get('title','(no title)')}{year} - {c.get('url','')}")
    return "\n\n".join(parts)


def _render_breeding_context_md(ctx: Any, *, language: str = "en") -> str:
    if not isinstance(ctx, dict):
        text = str(ctx).strip()
        if not text:
            return ""
        heading = "## 育种项目背景" if language == "zh" else "## Breeding project context"
        return f"{heading}\n{text}"

    if language == "zh":
        rows = [
            ("作物 / 物种", ctx.get("crop")),
            ("目标性状", ctx.get("target_trait")),
            ("种质 / 亲本", ctx.get("germplasm")),
            ("供体亲本 / 材料", ctx.get("donor_parent")),
            ("轮回亲本 / 目标背景", ctx.get("recurrent_parent")),
            ("材料可得性", ctx.get("material_availability")),
            ("目标环境群体", ctx.get("target_population_of_environments")),
            ("候选基因 / QTL / 标记", _join_list(ctx.get("candidate_genes_qtl"))),
            ("育种策略", ctx.get("breeding_strategy")),
            ("选择路线", ctx.get("selection_scheme")),
            ("表型鉴定计划", ctx.get("phenotyping_plan")),
            ("基因型鉴定计划", ctx.get("genotyping_plan")),
            ("验证试验设计", ctx.get("validation_trial_design")),
            ("决策门槛", ctx.get("decision_thresholds")),
            ("周期估计", ctx.get("cycle_time_estimate")),
            ("预期育种价值", ctx.get("expected_breeding_value")),
            ("风险 / 权衡", _join_list(ctx.get("risks_tradeoffs"))),
            ("证据缺口", _join_list(ctx.get("evidence_gaps"))),
            ("备选路线", ctx.get("fallback_route")),
        ]
        lines = ["## 育种项目背景"]
    else:
        rows = [
            ("Crop / species", ctx.get("crop")),
            ("Target trait", ctx.get("target_trait")),
            ("Germplasm", ctx.get("germplasm")),
            ("Donor parent / source material", ctx.get("donor_parent")),
            ("Recurrent parent / target background", ctx.get("recurrent_parent")),
            ("Material availability", ctx.get("material_availability")),
            ("Target population of environments", ctx.get("target_population_of_environments")),
            ("Candidate genes / QTL / markers", _join_list(ctx.get("candidate_genes_qtl"))),
            ("Breeding strategy", ctx.get("breeding_strategy")),
            ("Selection scheme", ctx.get("selection_scheme")),
            ("Phenotyping plan", ctx.get("phenotyping_plan")),
            ("Genotyping plan", ctx.get("genotyping_plan")),
            ("Validation trial design", ctx.get("validation_trial_design")),
            ("Decision thresholds", ctx.get("decision_thresholds")),
            ("Cycle-time estimate", ctx.get("cycle_time_estimate")),
            ("Expected breeding value", ctx.get("expected_breeding_value")),
            ("Risks / tradeoffs", _join_list(ctx.get("risks_tradeoffs"))),
            ("Evidence gaps", _join_list(ctx.get("evidence_gaps"))),
            ("Fallback route", ctx.get("fallback_route")),
        ]
        lines = ["## Breeding project context"]
    for label, value in rows:
        if value:
            lines.append(f"- **{label}.** {value}")
    return "\n".join(lines)


def _render_breeding_context_text(ctx: Any) -> str:
    if isinstance(ctx, str):
        return ctx.strip()
    if not isinstance(ctx, dict) or not ctx:
        return ""
    parts = []
    for key in (
        "crop",
        "target_trait",
        "germplasm",
        "donor_parent",
        "recurrent_parent",
        "material_availability",
        "target_population_of_environments",
        "candidate_genes_qtl",
        "breeding_strategy",
        "selection_scheme",
        "phenotyping_plan",
        "genotyping_plan",
        "validation_trial_design",
        "decision_thresholds",
        "cycle_time_estimate",
        "expected_breeding_value",
        "risks_tradeoffs",
        "evidence_gaps",
        "fallback_route",
    ):
        value = ctx.get(key)
        if value:
            parts.append(f"{key}: {_join_list(value)}")
    return "\n".join(parts)


def _join_list(value: Any) -> str:
    if isinstance(value, list):
        return "; ".join(str(v) for v in value if v is not None)
    return str(value) if value is not None else ""


def _build_session_context(goal: str, plan: ResearchPlan, sys_feedback_text: str | None) -> str:
    fb = ""
    if sys_feedback_text:
        fb = "\n\n# Researcher / Iteration Orchestrator Feedback\n" + quote_untrusted(
            sys_feedback_text, id_="system_feedback:latest"
        )
    return (
        f"# Research goal\n{goal}\n\n"
        f"# Parsed plan\n"
        f"- Objective: {plan.objective}\n"
        f"- Preferences: {'; '.join(plan.preferences) or '(none)'}\n"
        f"- Idea attributes: {'; '.join(plan.idea_attributes) or '(none)'}\n"
        f"- Constraints: {'; '.join(plan.constraints) or '(none)'}\n"
        f"- Crop: {plan.crop or '(unknown)'}\n"
        f"- Target traits: {'; '.join(plan.target_traits) or '(none)'}\n"
        f"- Target environments: {'; '.join(plan.target_environments) or '(none)'}\n"
        f"- Material constraints: {'; '.join(plan.material_constraints) or '(none)'}\n"
        f"- Preferred breeding strategies: {'; '.join(plan.preferred_breeding_strategies) or '(none)'}\n"
        f"- Validation constraints: {'; '.join(plan.validation_constraints) or '(none)'}\n"
        f"- Success criteria: {'; '.join(plan.success_criteria) or '(none)'}\n"
        f"- Local-first evidence: {plan.local_first}\n"
        f"- Initial hypothesis count: {plan.initial_hypothesis_count if plan.initial_hypothesis_count is not None else '(unspecified)'}\n"
        f"- Max hypothesis count: {plan.max_hypothesis_count if plan.max_hypothesis_count is not None else '(unspecified)'}\n"
        f"{fb}"
    )


async def _load_evidence_package_context(cfg, evidence_package_path: Any) -> str:
    if not evidence_package_path:
        return ""
    try:
        package = await read_json(cfg, str(evidence_package_path))
    except Exception:
        return ""
    if not isinstance(package, dict):
        return ""

    parts: list[str] = [
        "# Curated breeding evidence package",
        (
            "Use this package as the local-first evidence boundary for hypothesis "
            "hypothesis design. Local germplasm, KG, and RAG clues must be preserved with "
            "their uncertainty; do not turn pending local validation into proof."
        ),
    ]

    germplasm = ((package.get("local_germplasm") or {}).get("results") or [])[:8]
    if germplasm:
        parts.append("## Candidate germplasm/resources")
        for record in germplasm:
            if not isinstance(record, dict):
                continue
            parts.append(
                "- "
                f"{record.get('accession_id') or record.get('name')}: "
                f"{record.get('summary') or record.get('primary_traits') or ''} "
                f"(availability={record.get('availability') or 'unknown'}, "
                f"confidence={record.get('data_confidence') or 'unknown'}, "
                f"markers={record.get('markers') or 'none'})"
            )

    kg_package = package.get("local_crop_kg") or {}
    kg = (kg_package.get("results") or [])[:10]
    if kg:
        parts.append("## Local KG clues")
        for node in kg:
            if not isinstance(node, dict):
                continue
            parts.append(
                "- "
                f"{node.get('id')}: {node.get('name')} "
                f"[{node.get('type')}; confidence={node.get('data_confidence') or 'unknown'}] "
                f"{node.get('summary') or ''}"
            )
            for edge in (node.get("edges") or [])[:3]:
                if isinstance(edge, dict):
                    parts.append(
                        "  - edge: "
                        f"{edge.get('subject_name') or edge.get('subject')} "
                        f"{edge.get('predicate')} "
                        f"{edge.get('object_name') or edge.get('object')} "
                        f"(confidence={edge.get('data_confidence') or 'unknown'})"
                    )

    rag = ((package.get("local_rag") or {}).get("results") or [])[:8]
    if rag:
        parts.append("## Local RAG evidence")
        for item in rag:
            if not isinstance(item, dict):
                continue
            excerpt = " ".join(str(item.get("text") or "").split())[:500]
            parts.append(
                "- "
                f"{item.get('url')}: {item.get('title') or item.get('source_path')}\n"
                f"  {excerpt}"
            )

    gaps = (package.get("evidence_gaps") or [])[:12]
    if gaps:
        parts.append("## Evidence gaps to carry into the hypothesis")
        for gap in gaps:
            if isinstance(gap, dict):
                parts.append(
                    "- "
                    f"{gap.get('severity') or 'unknown'} / {gap.get('type') or 'gap'}: "
                    f"{gap.get('target') or ''} {gap.get('message') or ''}".strip()
                )

    guidance = package.get("downstream_guidance") or []
    if guidance:
        parts.append("## Downstream guidance")
        for item in guidance[:8]:
            parts.append(f"- {item}")

    return "\n".join(parts)


async def _attach_evidence_provenance(
    cfg,
    record: dict[str, Any],
    evidence_package_path: Any,
) -> None:
    if not evidence_package_path:
        return
    path = str(evidence_package_path)
    record["evidence_package_path"] = path
    try:
        package = await read_json(cfg, path)
    except Exception:
        return
    if not isinstance(package, dict):
        return
    graph_path = package.get("breeding_evidence_graph_path")
    if graph_path:
        record["breeding_evidence_graph_path"] = graph_path
    kg_package = package.get("local_crop_kg") or {}
    record["evidence_package_counts"] = {
        "germplasm": len((package.get("local_germplasm") or {}).get("results") or []),
        "kg": len((kg_package.get("results")) or []),
        "rag": len((package.get("local_rag") or {}).get("results") or []),
        "gaps": len(package.get("evidence_gaps") or []),
    }
    gap_types = []
    for gap in package.get("evidence_gaps") or []:
        if isinstance(gap, dict) and gap.get("type"):
            gap_types.append(str(gap["type"]))
    if gap_types:
        record["evidence_gap_types"] = sorted(set(gap_types))


async def _attach_validation_and_risk_provenance(
    cfg,
    record: dict[str, Any],
    *,
    validation_plan_path: Any,
    risk_review_path: Any,
) -> None:
    if validation_plan_path:
        path = str(validation_plan_path)
        record["validation_plan_path"] = path
        try:
            plan = await read_json(cfg, path)
        except Exception:
            plan = {}
        if isinstance(plan, dict):
            record["validation_plan_summary"] = {
                "validation_readiness_score": plan.get("validation_readiness_score"),
                "readiness_level": plan.get("readiness_level"),
                "critical_gap_count": len(plan.get("critical_evidence_gaps") or []),
            }
    if risk_review_path:
        path = str(risk_review_path)
        record["risk_review_path"] = path
        try:
            review = await read_json(cfg, path)
        except Exception:
            review = {}
        if isinstance(review, dict):
            risk_counts = review.get("risk_counts") if isinstance(review.get("risk_counts"), dict) else {}
            record["risk_review_summary"] = {
                "risk_control_score": review.get("risk_control_score"),
                "risk_level": review.get("risk_level"),
                "risk_counts": risk_counts,
                "must_resolve_count": len(
                    review.get("must_resolve_before_prioritization") or []
                ),
            }


def _attach_iteration_parentage(record: dict[str, Any], payload: dict[str, Any]) -> None:
    parent_id = payload.get("parent_hypothesis_id")
    action = payload.get("iteration_action")
    if not isinstance(parent_id, str) or not parent_id:
        return
    if action not in {"revise", "expand"}:
        return
    parent_ids = [
        str(item)
        for item in record.get("parent_ids") or []
        if str(item).strip()
    ]
    if parent_id not in parent_ids:
        parent_ids.append(parent_id)
    record["parent_ids"] = parent_ids
    record["parent_hypothesis_id"] = parent_id
    route_revision_intent = payload.get("route_revision_intent") or {}
    record["route_revision_intent"] = route_revision_intent
    record["new_hypothesis_direction"] = payload.get("new_hypothesis_direction") or ""
    record["evidence_gap_to_resolve"] = payload.get("evidence_gap_to_resolve") or []
    record["do_not_repeat"] = payload.get("do_not_repeat") or []


def _attach_breeding_design_card_audit(record: dict[str, Any]) -> None:
    context = _preferred_breeding_context(record)
    missing = [
        field
        for field in _BREEDING_DESIGN_CARD_FIELDS
        if not _field_has_content(context, field)
    ]
    present = len(_BREEDING_DESIGN_CARD_FIELDS) - len(missing)
    score = round(present / len(_BREEDING_DESIGN_CARD_FIELDS) * 100, 2)
    hard_missing = [
        field
        for field in _BREEDING_DESIGN_CRITICAL_FIELDS
        if field in missing
    ]
    record["breeding_design_card_audit"] = {
        "version": 1,
        "status": "complete" if not hard_missing and score >= 80 else "needs_attention",
        "completeness_score": score,
        "present_field_count": present,
        "required_field_count": len(_BREEDING_DESIGN_CARD_FIELDS),
        "missing_fields": missing,
        "missing_critical_fields": hard_missing,
        "context_sources": {
            "evidence_package": bool(record.get("evidence_package_path")),
            "validation_plan": bool(record.get("validation_plan_path")),
            "risk_review": bool(record.get("risk_review_path")),
        },
        "checks": {
            "material_route_explicit": _field_has_content(context, "donor_parent")
            and _field_has_content(context, "recurrent_parent"),
            "marker_or_qtl_explicit": _field_has_content(context, "candidate_genes_qtl"),
            "validation_route_explicit": _field_has_content(context, "validation_trial_design"),
            "risk_and_fallback_explicit": _field_has_content(context, "risks_tradeoffs")
            and _field_has_content(context, "fallback_route"),
            "evidence_gaps_preserved": _field_has_content(context, "evidence_gaps")
            or bool(record.get("evidence_gap_types")),
        },
    }


_BREEDING_DESIGN_CARD_FIELDS = (
    "crop",
    "target_trait",
    "germplasm",
    "donor_parent",
    "recurrent_parent",
    "material_availability",
    "target_population_of_environments",
    "candidate_genes_qtl",
    "breeding_strategy",
    "selection_scheme",
    "phenotyping_plan",
    "genotyping_plan",
    "validation_trial_design",
    "decision_thresholds",
    "cycle_time_estimate",
    "expected_breeding_value",
    "risks_tradeoffs",
    "evidence_gaps",
    "fallback_route",
)
_BREEDING_DESIGN_CRITICAL_FIELDS = (
    "crop",
    "target_trait",
    "donor_parent",
    "recurrent_parent",
    "candidate_genes_qtl",
    "breeding_strategy",
    "selection_scheme",
    "phenotyping_plan",
    "genotyping_plan",
    "validation_trial_design",
    "risks_tradeoffs",
    "evidence_gaps",
    "fallback_route",
)


def _preferred_breeding_context(record: dict[str, Any]) -> dict[str, Any]:
    for key in ("breeding_context_zh", "breeding_context", "breeding_context_en"):
        value = record.get(key)
        if isinstance(value, dict) and value:
            return value
    return {}


def _field_has_content(context: dict[str, Any], field: str) -> bool:
    value = context.get(field)
    if isinstance(value, list):
        return any(str(item).strip() for item in value)
    text = str(value or "").strip()
    if not text:
        return False
    return text.lower() not in {"unknown", "not specified", "none", "n/a", "na"}


async def _load_iteration_decision_context(cfg, iteration_decision_path: Any) -> str:
    if not iteration_decision_path:
        return ""
    try:
        decision = await read_json(cfg, str(iteration_decision_path))
    except Exception:
        return ""
    if not isinstance(decision, dict):
        return ""

    parts = [
        "# Iteration decision guidance",
        (
            "Use this decision as the reason for generating the next hypothesis. "
            "If the action is revise, preserve the strongest parts of the parent "
            "route while resolving the listed gaps. If the action is expand, use "
            "the evidence graph to propose a meaningfully different route."
        ),
        f"- Parent hypothesis: {decision.get('hypothesis_id') or '(unknown)'}",
        f"- Action: {decision.get('action') or '(unknown)'}",
        f"- Total score: {decision.get('total_score') if decision.get('total_score') is not None else '(unknown)'}",
        f"- Recommendation: {decision.get('next_step_recommendation') or '(none)'}",
    ]
    scorecard = decision.get("scorecard") or []
    if scorecard:
        parts.append("## Scorecard")
        for row in scorecard[:8]:
            if not isinstance(row, dict):
                continue
            parts.append(
                "- "
                f"{row.get('dimension')}: {row.get('score')}/100 "
                f"(weight={row.get('weight')}) - {row.get('rationale') or ''}"
            )
    reasons = decision.get("reasons") or []
    if reasons:
        parts.append("## Reasons")
        for reason in reasons[:8]:
            parts.append(f"- {reason}")
    gap_counts = decision.get("gap_counts") or {}
    if gap_counts:
        parts.append("## Gap counts")
        parts.append(str(gap_counts))
    intent = decision.get("route_revision_intent")
    if isinstance(intent, dict) and intent:
        parts.append("## Successor route intent")
        parts.append(
            "- Intent: "
            f"{intent.get('route_revision_intent') or '(unknown)'}"
        )
        parts.append(f"- Direction: {intent.get('new_hypothesis_direction') or '(none)'}")
        gaps = intent.get("evidence_gap_to_resolve") or []
        if gaps:
            parts.append("- Evidence gaps to resolve:")
            for gap in gaps[:6]:
                parts.append(f"  - {gap}")
        do_not_repeat = intent.get("do_not_repeat") or []
        if do_not_repeat:
            parts.append("- Do not repeat:")
            for item in do_not_repeat[:6]:
                parts.append(f"  - {item}")
    return "\n".join(parts)


def _build_payload_route_revision_intent_context(payload: dict[str, Any]) -> str:
    intent = payload.get("route_revision_intent")
    direction = payload.get("new_hypothesis_direction")
    gaps = payload.get("evidence_gap_to_resolve")
    do_not_repeat = payload.get("do_not_repeat")
    if not any((intent, direction, gaps, do_not_repeat)):
        return ""

    if isinstance(intent, dict):
        intent_label = intent.get("route_revision_intent")
        direction = direction or intent.get("new_hypothesis_direction")
        gaps = gaps or intent.get("evidence_gap_to_resolve")
        do_not_repeat = do_not_repeat or intent.get("do_not_repeat")
    else:
        intent_label = intent

    parts = [
        "# Required successor route intent",
        (
            "The next hypothesis must visibly iterate from the parent decision. "
            "Do not generate a generic or near-duplicate hypothesis."
        ),
        f"- Parent hypothesis: {payload.get('parent_hypothesis_id') or '(unknown)'}",
        f"- Iteration action: {payload.get('iteration_action') or '(unknown)'}",
        f"- Successor intent: {intent_label or '(unknown)'}",
        f"- New hypothesis direction: {direction or '(none)'}",
    ]
    gap_list = _as_text_list(gaps)
    if gap_list:
        parts.append("## Evidence gaps the successor route must resolve")
        for gap in gap_list[:8]:
            parts.append(f"- {gap}")
    avoid_list = _as_text_list(do_not_repeat)
    if avoid_list:
        parts.append("## Do not repeat")
        for item in avoid_list[:8]:
            parts.append(f"- {item}")
    return "\n".join(parts)


def _as_text_list(value: Any) -> list[str]:
    if isinstance(value, list):
        return [str(item) for item in value if str(item).strip()]
    if value:
        return [str(value)]
    return []


async def _load_validation_plan_context(cfg, validation_plan_path: Any) -> str:
    if not validation_plan_path:
        return ""
    try:
        plan = await read_json(cfg, str(validation_plan_path))
    except Exception:
        return ""
    if not isinstance(plan, dict):
        return ""

    parts = [
        "# Validation Planner guidance",
        (
            "Use this validation plan to make the next breeding hypothesis more "
            "experimentally actionable. Preserve explicit materials, marker assays, "
            "field design, decision thresholds, and validation gaps."
        ),
        f"- Validation readiness: {plan.get('validation_readiness_score', '(unknown)')}",
        f"- Readiness level: {plan.get('readiness_level') or '(unknown)'}",
    ]
    goal = plan.get("breeding_goal")
    if isinstance(goal, dict):
        parts.append("## Breeding goal")
        for key in (
            "crop",
            "target_trait",
            "target_environment",
            "donor_parent",
            "recurrent_parent",
            "candidate_genes_qtl_markers",
        ):
            value = goal.get(key)
            if value:
                parts.append(f"- {key}: {_join_list(value)}")
    for section in (
        "materials_plan",
        "genotyping_plan",
        "phenotyping_plan",
        "field_trial_design",
        "cost_cycle_estimate",
    ):
        value = plan.get(section)
        if isinstance(value, dict):
            parts.append(f"## {section}")
            for key, item in value.items():
                if item:
                    parts.append(f"- {key}: {_join_list(item)}")
    gaps = plan.get("critical_evidence_gaps") or []
    if gaps:
        parts.append("## Critical validation gaps")
        for gap in gaps[:10]:
            if isinstance(gap, dict):
                parts.append(
                    "- "
                    f"{gap.get('severity') or 'unknown'} / {gap.get('type') or 'gap'}: "
                    f"{gap.get('message') or ''}"
                )
    return "\n".join(parts)


async def _load_risk_review_context(cfg, risk_review_path: Any) -> str:
    if not risk_review_path:
        return ""
    try:
        review = await read_json(cfg, str(risk_review_path))
    except Exception:
        return ""
    if not isinstance(review, dict):
        return ""

    parts = [
        "# Risk Reviewer guidance",
        (
            "Use this risk review to revise or expand the breeding route without "
            "hiding unresolved material, genetic, GxE, deployment, or validation risks."
        ),
        f"- Risk control score: {review.get('risk_control_score', '(unknown)')}",
        f"- Risk level: {review.get('risk_level') or '(unknown)'}",
    ]
    counts = review.get("risk_counts")
    if counts:
        parts.append(f"- Risk counts: {counts}")
    must_resolve = review.get("must_resolve_before_prioritization") or []
    if must_resolve:
        parts.append("## Must resolve before composite prioritization")
        for risk in must_resolve[:8]:
            if isinstance(risk, dict):
                parts.append(
                    "- "
                    f"{risk.get('severity') or 'unknown'} / {risk.get('category') or 'risk'}: "
                    f"{risk.get('message') or ''} "
                    f"Mitigation: {risk.get('mitigation') or ''}"
                )
    risks = review.get("risk_items") or []
    if risks:
        parts.append("## Risk items")
        for risk in risks[:12]:
            if isinstance(risk, dict):
                parts.append(
                    "- "
                    f"{risk.get('severity') or 'unknown'} / {risk.get('category') or 'risk'}: "
                    f"{risk.get('message') or ''}"
                )
    return "\n".join(parts)


async def _latest_system_feedback(deps: AgentDeps, session_id: str) -> str | None:
    fb = await fb_repo.latest_system_feedback(deps.db, session_id)
    return fb.text if fb is not None else None
