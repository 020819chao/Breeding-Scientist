"""Supervisor 鈥?durable task scheduler for the multi-agent system.

Responsibilities:
1. Parse the scientist's goal into a ResearchPlan.
2. Bootstrap the session (insert row, reclaim expired leases on resume).
3. Run a bounded asyncio worker pool that claims tasks from the DB-backed queue.
4. Apply follow-up scheduling rules after each task completes.
5. Periodically run `decide_next_steps` when the queue is idle:
   - Pairwise calibration.
   - Hypothesis repair / expansion when the prioritized pool is mature.
   - Periodic system feedback for the iteration loop.
6. Check the termination predicate after every task; on stop, cancel pending
   work and run a single final synthesis for the overview.
7. Honor pause / abort via DB-flagged session.status.
"""

from __future__ import annotations

import asyncio
import contextlib
import json
import time
import traceback
from datetime import UTC, datetime
from typing import Any

import aiosqlite

from .. import ids
from ..config import Config
from ..knowledge.snapshot import (
    capture_knowledge_snapshot,
    config_for_knowledge_snapshot,
    materialize_knowledge_snapshot,
)
from ..llm.anthropic_client import (
    AgentCallSpec,
    CachedBlock,
    CallContext,
)
from ..llm.budgets import BudgetExceeded, TokenBudget
from ..llm.prompts import render
from ..llm.provider import get_provider
from ..llm.routing import route
from ..logging import bind, get_logger
from ..models import CALIBRATION_POOL_STATE, ResearchPlan, Session, Task
from ..orchestrator.breeding_termination import should_stop_breeding
from ..orchestrator.events import GLOBAL_BUS
from ..orchestrator.termination import (
    StabilityTracker,
    StopReason,
    should_stop,
    snapshot_top_k_pairwise_calibration,
)
from ..orchestrator.termination_report import termination_report_markdown
from ..prioritization.composite import (
    latest_iteration_decisions_for_session,
    route_admission_summary,
)
from ..storage import db as db_mod
from ..storage.artifacts import write_json, write_text
from ..storage.repos import events as events_repo
from ..storage.repos import feedback as fb_repo
from ..storage.repos import hypotheses as hyp_repo
from ..storage.repos import reviews as rev_repo
from ..storage.repos import sessions as sess_repo
from ..storage.repos import tasks as task_repo
from ..tools.registry import ToolRegistry
from .base import AgentDeps
from .breeding_designer import BreedingDesignerAgent
from .display import core_agent_name, decorate_agent_payload
from .evidence_curator import EvidenceCuratorAgent
from .evidence_review import EvidenceReviewAgent
from .iteration_orchestrator import IterationOrchestratorAgent
from .iteration_orchestrator_ranking import IterationOrchestratorRankingStage
from .iteration_orchestrator_synthesis import IterationOrchestratorSynthesisStage
from .risk_reviewer import RiskReviewerAgent
from .schemas import RECORD_RESEARCH_PLAN_TOOL
from .validation_planner import ValidationPlannerAgent

log = get_logger("supervisor")


class _ActionRouter:
    """Dispatch a public six-agent queue identity to action-specific executors."""

    def __init__(self, routes: dict[str, object]) -> None:
        self.routes = routes

    async def execute(self, task: Task):
        agent = self.routes.get(task.action)
        if agent is None:
            raise ValueError(f"No six-agent executor route for action {task.action!r}")
        return await agent.execute(task)


# ----------------------------- public API ----------------------------- #


class Supervisor:
    """One-process Supervisor; CLI invokes via `await supervisor.run_session(...)`."""

    def __init__(self, cfg: Config) -> None:
        self.cfg = cfg

    async def run_session(
        self,
        goal: str,
        *,
        preferences_text: str | None = None,
        n_initial: int | None = None,
        max_hypothesis_count: int | None = None,
        wall_clock_seconds: int | None = None,
        resume_session_id: str | None = None,
    ) -> str:
        acceptance_cfg = self.cfg
        conn = await db_mod.connect(self.cfg)
        session: Session | None = None
        try:
            if resume_session_id is None:
                requested_initial = _positive_int_or_none(n_initial) or 3
                session = await self._create_session(conn, goal, preferences_text, wall_clock_seconds)
                self.cfg = config_for_knowledge_snapshot(
                    acceptance_cfg,
                    session.config_snapshot.get("knowledge_snapshot", {}),
                )
                bind(session_id=session.id)
                log.info(
                    "session_started",
                    goal=goal[:120], session_id=session.id,
                    budget_usd=session.budget_usd, n_initial=requested_initial,
                    max_hypothesis_count=max_hypothesis_count,
                )
                await self._emit(conn, session.id, "session_started", {
                    "goal": goal[:200], "n_initial": requested_initial,
                    "max_hypothesis_count": max_hypothesis_count,
                    "budget_usd": session.budget_usd,
                })
                budget = TokenBudget(
                    cfg=self.cfg,
                    budget_tokens=session.budget_tokens,
                    budget_usd=session.budget_usd,
                )
                llm = get_provider(self.cfg, db=conn, budget=budget)
                tools = ToolRegistry(self.cfg).discover()
                deps = AgentDeps(cfg=self.cfg, db=conn, llm=llm, tools=tools)

                plan = await self._parse_goal(deps, session, goal, preferences_text)
                plan = _apply_explicit_hypothesis_bounds(
                    plan,
                    requested_initial=n_initial,
                    requested_max=max_hypothesis_count,
                )
                await self._apply_plan(conn, session, plan)
                session = await sess_repo.fetch(conn, session.id)
                assert session is not None
                effective_n_initial = _resolve_initial_hypothesis_count(
                    plan,
                    requested=requested_initial,
                    run_max=self.cfg.run.max_ideas,
                )

                await task_repo.enqueue(conn, Task(
                    id=ids.task_id(), session_id=session.id,
                    created_at=datetime.now(UTC),
                    agent="evidence_curator", action="CurateEvidencePackage",
                    payload={"mode": "bfrs", "n_initial": effective_n_initial},
                    priority=90, status="pending",
                    idempotency_key=f"{session.id}::evidence_curator::initial",
                ))
            else:
                session = await sess_repo.fetch(conn, resume_session_id)
                if session is None:
                    raise RuntimeError(f"no such session: {resume_session_id}")
                snapshot = session.config_snapshot.get("knowledge_snapshot")
                if not isinstance(snapshot, dict) or not snapshot.get("runtime_catalog_path"):
                    raise RuntimeError(
                        "cannot safely resume this legacy Session: it has no immutable "
                        "knowledge snapshot; create a new Session instead"
                    )
                self.cfg = config_for_knowledge_snapshot(
                    acceptance_cfg,
                    snapshot,
                )
                bind(session_id=session.id)
                log.info("session_resumed", session_id=session.id, status=session.status)
                reclaimed = await task_repo.reclaim_expired_leases(
                    conn, session.id, max_attempts=self.cfg.lease.max_attempts,
                )
                log.info("leases_reclaimed", **reclaimed)
                if session.status not in ("running", "paused"):
                    await sess_repo.set_status(conn, session.id, "running")
                budget = TokenBudget(
                    cfg=self.cfg,
                    budget_tokens=session.budget_tokens,
                    budget_usd=session.budget_usd,
                )
                llm = get_provider(self.cfg, db=conn, budget=budget)
                tools = ToolRegistry(self.cfg).discover()
                deps = AgentDeps(cfg=self.cfg, db=conn, llm=llm, tools=tools)

            tracker = StabilityTracker(
                k=self.cfg.termination.effective_pairwise_calibration_stability_k,
                n=self.cfg.termination.effective_pairwise_calibration_stability_n,
                eps=self.cfg.termination.effective_pairwise_calibration_stability_eps,
                min_ideas=self.cfg.termination.min_ideas_before_stable,
                min_pairwise_calibrations=(
                    self.cfg.termination.effective_min_pairwise_calibrations_before_stable
                ),
                min_pairwise_calibrations_per_hypothesis=(
                    self.cfg.termination.effective_min_pairwise_calibrations_per_hypothesis
                ),
            )

            stop_reason = await self._main_loop(conn, deps, session, tracker)
            log.info("main_loop_exit", stop_reason=stop_reason.value if stop_reason else "none")

            await self._finalize(
                conn,
                deps,
                session,
                stop_reason,
                acceptance_cfg=acceptance_cfg,
            )
            return session.id
        except Exception as exc:
            if session is not None:
                try:
                    await sess_repo.set_status(conn, session.id, "failed")
                    await self._emit(
                        conn,
                        session.id,
                        "session_failed",
                        {
                            "error": str(exc)[:1000],
                            "exception_type": type(exc).__name__,
                            "traceback": traceback.format_exc()[-4000:],
                        },
                    )
                except Exception:
                    log.exception("session_failure_status_update_failed", session_id=session.id)
            log.exception(
                "session_run_failed",
                session_id=session.id if session is not None else None,
                err=str(exc),
            )
            raise
        finally:
            await conn.close()

    # ----------------------------- session bootstrap ----------------------------- #

    async def _create_session(
        self,
        conn: aiosqlite.Connection,
        goal: str,
        preferences_text: str | None,
        wall_clock_seconds: int | None,
    ) -> Session:
        sid = ids.session_id()
        now = datetime.now(UTC)
        wall = wall_clock_seconds or self.cfg.run.wall_clock_seconds
        from datetime import timedelta

        plan = ResearchPlan(objective=goal.strip(), preferences=[], idea_attributes=[])
        snap: dict[str, Any] = json.loads(json.dumps(self.cfg.model_dump(exclude={"secrets"})))
        snap["knowledge_snapshot"] = materialize_knowledge_snapshot(
            self.cfg,
            capture_knowledge_snapshot(self.cfg),
        )
        s = Session(
            id=sid, created_at=now, updated_at=now, status="running",
            research_goal=goal, research_plan=plan,
            config_snapshot=snap,
            budget_tokens=self.cfg.run.budget_tokens, budget_usd=self.cfg.run.budget_usd,
            wall_deadline=now + timedelta(seconds=wall),
        )
        await sess_repo.insert(conn, s)
        await write_json(
            self.cfg,
            s.id,
            "meta",
            "knowledge_snapshot",
            snap["knowledge_snapshot"],
        )
        if preferences_text:
            await fb_repo.insert(conn, _human_preference(s.id, preferences_text))
        return s

    async def _parse_goal(
        self,
        deps: AgentDeps,
        session: Session,
        goal: str,
        preferences_text: str | None,
    ) -> ResearchPlan:
        prompt = render(
            "goal_interpreter.parse_goal", goal=goal,
            preferences_text=preferences_text or "",
        )
        r = route(self.cfg, "goal_interpreter", None)
        spec = AgentCallSpec(
            route=r,
            system_blocks=[CachedBlock(
                "You parse crop-improvement and grain-breeding research goals into structured plans.",
                cache=True,
            )],
            user_blocks=[CachedBlock(prompt, cache=False)],
            tools=[RECORD_RESEARCH_PLAN_TOOL],
            tool_choice={"type": "tool", "name": "record_research_plan"},
            max_output_tokens=1024,
        )
        ctx = CallContext(
            session_id=session.id, task_id=None,
            agent="goal_interpreter", action="parse_goal", mode=None,
        )
        resp = await deps.llm.call(spec, ctx)
        record: dict[str, Any] | None = None
        for b in resp.raw.content:
            if getattr(b, "type", None) == "tool_use" and getattr(b, "name", "") == "record_research_plan":
                inp = getattr(b, "input", None)
                if isinstance(inp, dict):
                    record = inp
                    break
        if record is None:
            log.warning("parse_goal_no_record", note="falling back to bare ResearchPlan")
            return ResearchPlan(objective=goal.strip(), preferences=[], idea_attributes=[])
        return ResearchPlan(
            objective=record.get("objective", goal.strip()),
            preferences=record.get("preferences", []),
            constraints=record.get("constraints", []),
            idea_attributes=record.get("idea_attributes", []),
            crop=record.get("crop") or None,
            target_traits=record.get("target_traits", []),
            target_environments=record.get("target_environments", []),
            material_constraints=record.get("material_constraints", []),
            preferred_breeding_strategies=record.get("preferred_breeding_strategies", []),
            validation_constraints=record.get("validation_constraints", []),
            success_criteria=record.get("success_criteria", []),
            initial_hypothesis_count=record.get("initial_hypothesis_count"),
            max_hypothesis_count=record.get("max_hypothesis_count"),
            local_first=bool(record.get("local_first", True)),
            domain_hint=record.get("domain_hint") or None,
            notes=record.get("notes") or None,
        )

    async def _apply_plan(
        self, conn: aiosqlite.Connection, session: Session, plan: ResearchPlan
    ) -> None:
        await conn.execute(
            "UPDATE sessions SET research_plan=?, updated_at=? WHERE id=?",
            (plan.model_dump_json(), datetime.now(UTC).isoformat(), session.id),
        )
        await conn.commit()

    # ----------------------------- main loop ----------------------------- #

    async def _main_loop(
        self,
        conn: aiosqlite.Connection,
        deps: AgentDeps,
        session: Session,
        tracker: StabilityTracker,
    ) -> StopReason | None:
        agents = self._build_agents(deps)
        sem = asyncio.Semaphore(self.cfg.run.concurrency)
        inflight: set[asyncio.Task] = set()
        worker_seq = 0
        last_decide_at = 0.0
        # Calibration counts start at zero. Using zero here makes snapshots
        # land on 5, 10, 15... rather than 4, 9, 14..., so the minimum-count
        # stability guard gets an opportunity to evaluate at its threshold.
        last_snapshot_pairwise_calibration_count = 0

        async def _run_task(t: Task) -> None:
            try:
                bind(
                    session_id=session.id,
                    task_id=t.id,
                    agent=core_agent_name(t.agent),
                    agent_internal=t.agent,
                )
                async with sem:
                    await task_repo.mark_in_progress(conn, t.id)
                    await self._emit(conn, session.id, "task_started",
                                     {"task_id": t.id, "agent": t.agent, "action": t.action,
                                      "target": t.target_id})
                    await self._emit(
                        conn,
                        session.id,
                        "agent_progress",
                        {
                            "task_id": t.id,
                            "agent": t.agent,
                            "action": t.action,
                            "target": t.target_id,
                            "phase": "working",
                            "message": "正在处理当前任务，整理相关证据和阶段性结果。",
                        },
                    )
                    agent = agents.get(t.agent)
                    if agent is None:
                        await task_repo.fail(conn, t.id, error=f"no agent: {t.agent}",
                                              max_attempts=self.cfg.lease.max_attempts)
                        return
                    try:
                        result = await agent.execute(t)
                    except BudgetExceeded as e:
                        # Budget exhaustion is local to this task. Preserve the
                        # unresolved route as pending review and let the rest of
                        # the Session reach synthesis instead of dead-lettering
                        # the whole run after repeated futile retries.
                        await task_repo.cancel(conn, t.id, error=f"pending_review: {e}")
                        log.warning(
                            "task_deferred_budget",
                            task_id=t.id,
                            agent=t.agent,
                            action=t.action,
                            target=t.target_id,
                            err=str(e),
                        )
                        await self._emit(
                            conn,
                            session.id,
                            "task_deferred_budget",
                            {
                                "task_id": t.id,
                                "agent": t.agent,
                                "action": t.action,
                                "target": t.target_id,
                                "err": str(e)[:300],
                                "review_status": "pending_review",
                            },
                        )
                        return
                    except Exception as e:
                        await task_repo.fail(conn, t.id, error=str(e),
                                              max_attempts=self.cfg.lease.max_attempts)
                        log.exception("task_failed", err=str(e), task_id=t.id, action=t.action)
                        await self._emit(conn, session.id, "task_failed",
                                         {"task_id": t.id, "agent": t.agent, "action": t.action,
                                          "target": t.target_id, "err": str(e)[:300]})
                        return

                    await self._emit(
                        conn,
                        session.id,
                        "agent_progress",
                        {
                            "task_id": t.id,
                            "agent": t.agent,
                            "action": t.action,
                            "target": t.target_id,
                            "phase": "finalizing",
                            "message": "核心处理已完成，正在整理结构化成果并更新闭环。",
                        },
                    )
                    await self._apply_follow_ups(conn, session, t, result)
                    await task_repo.complete(conn, t.id)
                    await self._emit(conn, session.id, "task_completed",
                                     {"task_id": t.id, "agent": t.agent, "action": t.action,
                                      "target": t.target_id, "kind": result.kind,
                                      "follow_hypothesis_ids": result.hypothesis_ids[:5],
                                      "message": "当前任务已完成，结果已经写入会话。"})
            except asyncio.CancelledError:
                raise
            except Exception as e:
                # The task preamble and follow-up scheduling used to sit
                # outside the worker's failure boundary. A filesystem or
                # queue error there could crash the whole main loop without a
                # task-level record, leaving leased work stranded.
                error = f"worker_boundary: {type(e).__name__}: {e}"
                with contextlib.suppress(Exception):
                    await task_repo.fail(
                        conn,
                        t.id,
                        error=error,
                        max_attempts=self.cfg.lease.max_attempts,
                    )
                log.exception("task_worker_boundary_failed", task_id=t.id, err=str(e))
                with contextlib.suppress(Exception):
                    await self._emit(
                        conn,
                        session.id,
                        "task_worker_boundary_failed",
                        {
                            "task_id": t.id,
                            "agent": t.agent,
                            "action": t.action,
                            "target": t.target_id,
                            "err": str(e)[:300],
                            "traceback": traceback.format_exc()[-4000:],
                        },
                    )

        try:
            while True:
                # Check external pause/abort by re-reading session status.
                refreshed = await sess_repo.fetch(conn, session.id)
                external_stop = refreshed is not None and refreshed.status in ("aborted",)
                if refreshed is not None and refreshed.status == "paused":
                    # Wait until unpaused (or aborted).
                    await asyncio.sleep(1.0)
                    continue

                task_counts = await task_repo.count_by_status(conn, session.id)
                if task_counts.get("dead", 0) > 0:
                    log.error(
                        "session_blocked_by_dead_task",
                        dead_tasks=task_counts.get("dead", 0),
                        session_id=session.id,
                    )
                    if inflight:
                        await asyncio.wait(inflight)
                    return StopReason.TASK_FAILURE

                # Termination check (refreshes budget_used_* from the row)
                if refreshed is not None:
                    stop = should_stop(self.cfg, refreshed, tracker, external_stop=external_stop)
                    if stop is not None:
                        # Wait for inflight to drain before returning.
                        if inflight:
                            await asyncio.wait(inflight)
                        return stop

                # Refill worker slots.
                slots_open = self.cfg.run.concurrency - len(inflight)
                claimed: list[Task] = []
                for _ in range(slots_open):
                    t = await task_repo.claim_one(
                        conn, session.id, worker_id=f"w{worker_seq}",
                        lease_seconds=self.cfg.lease.default_seconds,
                    )
                    if t is None:
                        break
                    worker_seq += 1
                    claimed.append(t)
                for t in claimed:
                    inflight.add(asyncio.create_task(_run_task(t)))

                # Update stability snapshot when the calibration count crosses the threshold.
                snap = await snapshot_top_k_pairwise_calibration(
                    conn,
                    session.id,
                    self.cfg.termination.effective_pairwise_calibration_stability_k,
                )
                if (
                    snap.pairwise_calibration_count
                    >= (
                        last_snapshot_pairwise_calibration_count
                        + self.cfg.termination.effective_pairwise_calibration_snapshot_every
                    )
                ):
                    tracker.push(snap)
                    last_snapshot_pairwise_calibration_count = snap.pairwise_calibration_count
                    log.info(
                        "pairwise_calibration_snapshot",
                        pairwise_calibration_count=snap.pairwise_calibration_count,
                        top_ids=list(snap.top_ids),
                        top_calibration_scores=list(snap.top_calibration_scores),
                    )

                # If nothing to do at all and the queue is empty, run decide_next_steps
                # at most every ~10s, else exit (only if we have no hypotheses yet either).
                if not inflight and not claimed:
                    pending = await task_repo.count_by_status(conn, session.id)
                    if pending.get("pending", 0) == 0:
                        admission_scheduled = await self._schedule_route_admission_followups(
                            conn,
                            session,
                        )
                        if admission_scheduled:
                            continue
                        if refreshed is not None:
                            breeding_stop = await should_stop_breeding(self.cfg, conn, refreshed)
                            if breeding_stop is not None:
                                return breeding_stop
                        now = time.monotonic()
                        if now - last_decide_at >= 10.0:
                            last_decide_at = now
                            scheduled = await self._decide_next_steps(conn, session)
                            if scheduled == 0:
                                # truly idle and no progress possible 鈥?exit gracefully
                                return StopReason.IDLE
                            continue
                        # Wait briefly so we don't spin
                        await asyncio.sleep(1.0)
                        continue

                if not inflight:
                    # Nothing claimed AND nothing running 鈥?but tasks may be pending
                    # in other workers' future claims; brief sleep and retry.
                    await asyncio.sleep(0.1)
                    continue

                done, pending = await asyncio.wait(
                    inflight, return_when=asyncio.FIRST_COMPLETED
                )
                for finished in done:
                    # Retrieve worker exceptions so they cannot become an
                    # unobserved asyncio warning or silently bypass the queue
                    # failure accounting.
                    finished.result()
                inflight = set(pending)
        finally:
            if inflight:
                # Best effort: let any inflight task finish before returning.
                await asyncio.wait(inflight)

    # ----------------------------- follow-up rules ----------------------------- #

    async def _apply_follow_ups(
        self,
        conn: aiosqlite.Connection,
        session: Session,
        task: Task,
        result,
    ) -> None:
        if result.kind == "evidence_curated":
            if not result.extra.get("enqueue_design", True):
                target_hid = result.extra.get("target_hypothesis_id") or task.target_id
                if target_hid and result.extra.get("mode") == "dfrs":
                    await task_repo.enqueue(conn, Task(
                        id=ids.task_id(), session_id=session.id,
                        created_at=datetime.now(UTC),
                        agent="validation_planner", action="PlanValidation",
                        target_id=target_hid,
                        payload={
                            "source": "dfrs_evidence_completed",
                            "evidence_package_path": result.extra.get("evidence_package_path"),
                            "breeding_evidence_graph_path": result.extra.get(
                                "breeding_evidence_graph_path"
                            ),
                            "validation_plan_path": result.extra.get("validation_plan_path"),
                        },
                        priority=88, status="pending",
                        idempotency_key=f"{target_hid}::validation_planner::dfrs::{task.id}",
                    ))
                return
            evidence_package_path = result.extra.get("evidence_package_path")
            n_initial = int(result.extra.get("n_initial") or task.payload.get("n_initial") or 3)
            for i in range(n_initial):
                await task_repo.enqueue(conn, Task(
                    id=ids.task_id(), session_id=session.id,
                    created_at=datetime.now(UTC),
                    agent="breeding_designer", action="DesignHypothesis",
                    payload={
                        "strategy": "literature",
                        "n": 1,
                        "evidence_package_path": evidence_package_path,
                    },
                    priority=100, status="pending",
                    idempotency_key=f"{session.id}::breeding_designer::initial::{i}",
                ))
        elif result.kind == "hypothesis_created":
            for hid in result.hypothesis_ids:
                await task_repo.enqueue(conn, Task(
                    id=ids.task_id(), session_id=session.id,
                    created_at=datetime.now(UTC),
                    agent="risk_reviewer", action="AssessHypothesisEvidence",
                    target_id=hid, payload={"kind": "full"},
                    priority=100, status="pending",
                    idempotency_key=f"{hid}::risk_reviewer::evidence_review::full",
                ))
        elif result.kind == "evidence_review_completed":
            for hid in result.hypothesis_ids:
                await task_repo.enqueue(conn, Task(
                    id=ids.task_id(), session_id=session.id,
                    created_at=datetime.now(UTC),
                    agent="validation_planner", action="PlanValidation",
                    target_id=hid,
                    payload={
                        "source": "evidence_review_completed",
                        "evidence_package_path": result.extra.get("evidence_package_path"),
                        "breeding_evidence_graph_path": result.extra.get(
                            "breeding_evidence_graph_path"
                        ),
                    },
                    priority=88, status="pending",
                    idempotency_key=f"{hid}::validation_planner::review",
                ))
        elif result.kind == "validation_planned":
            for hid in result.hypothesis_ids:
                if result.extra.get("source") == "dfrs_evidence_completed":
                    await task_repo.enqueue(conn, Task(
                        id=ids.task_id(), session_id=session.id,
                        created_at=datetime.now(UTC),
                        agent="risk_reviewer", action="ReviewRisk",
                        target_id=hid,
                        payload={
                            "evidence_package_path": result.extra.get(
                                "evidence_package_path"
                            ),
                            "breeding_evidence_graph_path": result.extra.get(
                                "breeding_evidence_graph_path"
                            ),
                            "validation_plan_path": result.extra.get("validation_plan_path"),
                        },
                        priority=85, status="pending",
                        idempotency_key=f"{hid}::risk_reviewer::post_validation::{task.id}",
                    ))
                    continue
                await task_repo.enqueue(conn, Task(
                    id=ids.task_id(), session_id=session.id,
                    created_at=datetime.now(UTC),
                    agent="evidence_curator", action="CurateEvidencePackage",
                    target_id=hid,
                    payload={
                        "mode": "dfrs",
                        "focus": "validation-follow-up",
                        "validation_plan_path": result.extra.get("validation_plan_path"),
                        "enqueue_design": False,
                    },
                    priority=90, status="pending",
                    idempotency_key=f"{hid}::evidence_curator::dfrs::validation",
                ))
        elif result.kind == "risk_reviewed":
            for hid in result.hypothesis_ids:
                await task_repo.enqueue(conn, Task(
                    id=ids.task_id(), session_id=session.id,
                    created_at=datetime.now(UTC),
                    agent="iteration_orchestrator", action="DecideIteration",
                    target_id=hid,
                    payload={
                        "evidence_package_path": result.extra.get("evidence_package_path"),
                        "breeding_evidence_graph_path": result.extra.get(
                            "breeding_evidence_graph_path"
                        ),
                        "validation_plan_path": result.extra.get("validation_plan_path"),
                        "risk_review_path": result.extra.get("risk_review_path"),
                    },
                    priority=85, status="pending",
                    idempotency_key=f"{hid}::iteration::decision::risk::{task.id}",
                ))
        elif result.kind == "iteration_decision":
            action = result.extra.get("action")
            for hid in result.hypothesis_ids:
                if action == "keep":
                    await task_repo.enqueue(conn, Task(
                        id=ids.task_id(), session_id=session.id,
                        created_at=datetime.now(UTC),
                        agent="iteration_orchestrator", action="QueuePairwiseCalibration",
                        target_id=hid, payload={}, priority=80, status="pending",
                        idempotency_key=f"{hid}::iteration_orchestrator::pairwise_add",
                    ))
                elif action in {"revise", "expand"}:
                    gate = await _hypothesis_design_gate(
                        conn,
                        session,
                        run_max=self.cfg.run.max_ideas,
                    )
                    if gate["can_enqueue"]:
                        await task_repo.enqueue(conn, Task(
                            id=ids.task_id(), session_id=session.id,
                            created_at=datetime.now(UTC),
                        agent="breeding_designer", action="DesignHypothesis",
                            target_id=hid,
                            payload={
                                "strategy": "literature",
                                "n": 1,
                                "evidence_package_path": result.extra.get("evidence_package_path"),
                                "iteration_decision_path": result.extra.get("decision_path"),
                                "iteration_action": action,
                                "route_revision_intent": result.extra.get(
                                    "route_revision_intent"
                                ),
                                "evidence_gap_to_resolve": result.extra.get(
                                    "evidence_gap_to_resolve"
                                ),
                                "new_hypothesis_direction": result.extra.get(
                                    "new_hypothesis_direction"
                                ),
                                "parent_hypothesis_id": result.extra.get(
                                    "parent_hypothesis_id"
                                ),
                                "do_not_repeat": result.extra.get("do_not_repeat"),
                                "validation_plan_path": result.extra.get("validation_plan_path"),
                                "risk_review_path": result.extra.get("risk_review_path"),
                            },
                            priority=100, status="pending",
                            idempotency_key=f"{hid}::breeding_designer::iteration::{action}",
                        ))
                    else:
                        await self._emit(
                            conn,
                            session.id,
                            "hypothesis_design_skipped",
                            {
                                "reason": "max_hypothesis_count_reached",
                                "current_count": gate["current_count"],
                                "limit": gate["limit"],
                                "action": action,
                                "hypothesis_id": hid,
                                "decision_path": result.extra.get("decision_path"),
                                "new_hypothesis_direction": result.extra.get(
                                    "new_hypothesis_direction"
                                ),
                            },
                        )
        elif result.kind == "pairwise_calibration_queued":
            for hid in result.hypothesis_ids:
                await task_repo.enqueue(conn, Task(
                    id=ids.task_id(), session_id=session.id,
                    created_at=datetime.now(UTC),
                    agent="iteration_orchestrator", action="RunPairwiseCalibration",
                    target_id=None,
                    payload={"focus": hid}, priority=120, status="pending",
                    idempotency_key=f"{hid}::iteration_orchestrator::pairwise_focus_batch",
                ))

    # ----------------------------- decide_next_steps ----------------------------- #

    async def _schedule_route_admission_followups(
        self,
        conn: aiosqlite.Connection,
        session: Session,
    ) -> int:
        """Turn unresolved route-admission states back into idempotent queue work."""

        decisions = latest_iteration_decisions_for_session(self.cfg, session.id)
        hypotheses = await hyp_repo.list_for_session(conn, session.id)
        min_pairwise = self.cfg.termination.effective_min_pairwise_calibrations_per_hypothesis
        scheduled = 0

        for hypothesis in hypotheses:
            decision = decisions.get(hypothesis.id)
            admission = route_admission_summary(
                hypothesis,
                decision,
                min_pairwise_calibrations=min_pairwise,
            )
            if admission["eligible"] or admission["status"] == "blocked":
                continue

            task: Task | None = None
            idempotency_key = ""
            if admission["status"] == "evidence_review_pending":
                idempotency_key = f"{hypothesis.id}::risk_reviewer::evidence_review::full"
                task = Task(
                    id=ids.task_id(),
                    session_id=session.id,
                    created_at=datetime.now(UTC),
                    agent="risk_reviewer",
                    action="AssessHypothesisEvidence",
                    target_id=hypothesis.id,
                    payload={"kind": "full", "source": "route_admission"},
                    priority=82,
                    status="pending",
                    idempotency_key=idempotency_key,
                )
            elif admission["status"] == "pairwise_pending":
                idempotency_key = f"{hypothesis.id}::iteration_orchestrator::pairwise_add"
                task = Task(
                    id=ids.task_id(),
                    session_id=session.id,
                    created_at=datetime.now(UTC),
                    agent="iteration_orchestrator",
                    action="QueuePairwiseCalibration",
                    target_id=hypothesis.id,
                    payload={"source": "route_admission"},
                    priority=78,
                    status="pending",
                    idempotency_key=idempotency_key,
                )
            elif admission["status"] == "evidence_gap" and decision is not None:
                action = str(decision.get("action") or "")
                if action not in {"revise", "expand"}:
                    continue
                existing_design_key = (
                    f"{hypothesis.id}::breeding_designer::iteration::{action}"
                )
                if await task_repo.exists_by_idempotency_key(conn, existing_design_key):
                    continue
                if any(
                    child.id != hypothesis.id and hypothesis.id in child.parent_ids
                    for child in hypotheses
                ):
                    continue
                decision_path = str(decision.get("decision_path") or "latest")
                idempotency_key = (
                    f"{hypothesis.id}::evidence_curator::admission::{decision_path}"
                )
                task = Task(
                    id=ids.task_id(),
                    session_id=session.id,
                    created_at=datetime.now(UTC),
                    agent="evidence_curator",
                    action="CurateEvidencePackage",
                    target_id=hypothesis.id,
                    payload={
                        "mode": "dfrs",
                        "focus": "route-admission-evidence-gap",
                        "source": "route_admission",
                        "enqueue_design": False,
                        "iteration_decision_path": decision.get("decision_path"),
                        "evidence_gap_to_resolve": decision.get("evidence_gap_to_resolve") or [],
                    },
                    priority=84,
                    status="pending",
                    idempotency_key=idempotency_key,
                )

            if task is not None and await task_repo.enqueue(conn, task):
                scheduled += 1

        return scheduled

    async def _decide_next_steps(
        self, conn: aiosqlite.Connection, session: Session
    ) -> int:
        """When the queue empties: refill it with refinement work. Returns # enqueued."""
        from ..storage.repos import pairwise_calibration as pairwise_repo

        enqueued = 0

        # Anchor idle-refinement idempotency keys on the current calibration count.
        # This prevents duplicate refinement tasks when the queue briefly drains.
        anchor_calibrations = await pairwise_repo.count_pairwise_calibrations(conn, session.id)

        # Always: one pairwise calibration batch to keep refining route order.
        calibration_pool = await hyp_repo.list_for_session(
            conn, session.id, state=CALIBRATION_POOL_STATE
        )
        if len(calibration_pool) >= 2:
            await task_repo.enqueue(conn, Task(
                id=ids.task_id(), session_id=session.id,
                created_at=datetime.now(UTC),
                agent="iteration_orchestrator", action="RunPairwiseCalibration",
                target_id=None, payload={},
                priority=150, status="pending",
                idempotency_key=(
                    f"{session.id}::iteration_orchestrator::pairwise_idle::{anchor_calibrations}"
                ),
            ))
            enqueued += 1

        # If the prioritized pool has matured, schedule route revision/expansion.
        # The maturity gate and top_k are config-driven so deep runs can lower
        # the gate to grow the pool faster.
        mature = sum(1 for h in calibration_pool if h.pairwise_calibrations_played >= 3)
        if mature >= self.cfg.route_revision.min_mature:
            await task_repo.enqueue(conn, Task(
                id=ids.task_id(), session_id=session.id,
                created_at=datetime.now(UTC),
                agent="breeding_designer", action="ReviseOrExpandRoute",
                target_id=None,
                payload={
                    "top_k": self.cfg.route_revision.top_k,
                    "strategies": ["combine", "simplify", "out_of_box"],
                },
                priority=140, status="pending",
                idempotency_key=(
                    f"{session.id}::breeding_designer::route_revision_idle::{anchor_calibrations}"
                ),
            ))
            enqueued += 1

        # Periodic synthesis feedback, approximated by pairwise calibration count.
        calibration_count = await pairwise_repo.count_pairwise_calibrations(conn, session.id)
        async with conn.execute(
            """SELECT COUNT(*) AS n FROM system_feedback
                  WHERE session_id=? AND kind='system_feedback' AND source='iteration_orchestrator'""",
            (session.id,),
        ) as cur:
            row = await cur.fetchone()
        feedback_count = row["n"] if row else 0
        if calibration_count >= (feedback_count + 1) * 50:
            await task_repo.enqueue(conn, Task(
                id=ids.task_id(), session_id=session.id,
                created_at=datetime.now(UTC),
                agent="iteration_orchestrator", action="SynthesizeIterationFeedback",
                target_id=None, payload={},
                priority=180, status="pending",
                idempotency_key=f"{session.id}::iteration_orchestrator::feedback::{feedback_count + 1}",
            ))
            enqueued += 1

        return enqueued

    # ----------------------------- finalize ----------------------------- #

    async def _finalize(
        self,
        conn: aiosqlite.Connection,
        deps: AgentDeps,
        session: Session,
        stop_reason: StopReason | None,
        *,
        acceptance_cfg: Config | None = None,
    ) -> None:
        n_cancel = await task_repo.cancel_pending_for_session(conn, session.id)
        if n_cancel:
            log.info("pending_cancelled", n=n_cancel)

        # Final synthesis is a required Iteration Orchestrator stage. The
        # plain overview remains a failure fallback, not a second workflow.
        agent = IterationOrchestratorSynthesisStage(deps)
        final_task = Task(
            id=ids.task_id(), session_id=session.id,
            created_at=datetime.now(UTC),
            agent="iteration_orchestrator", action="GenerateFinalBreedingOverview",
            target_id=None,
            payload={"stop_reason": stop_reason.value if stop_reason else None},
            priority=1,
            status="pending",
            idempotency_key=f"{session.id}::iteration_orchestrator::final",
        )
        await task_repo.enqueue(conn, final_task)
        await task_repo.mark_in_progress(conn, final_task.id)
        try:
            result = await agent.execute(final_task)
            overview_path = result.extra.get("overview_path")
            if overview_path:
                await sess_repo.set_final_overview(conn, session.id, overview_path)
            await task_repo.complete(conn, final_task.id)
        except Exception as e:
            log.exception("final_overview_failed", err=str(e))
            await task_repo.fail(conn, final_task.id, error=str(e),
                                  max_attempts=self.cfg.lease.max_attempts)
            overview_path = await self._write_simple_overview(conn, session, stop_reason)
            await sess_repo.set_final_overview(conn, session.id, overview_path)

        # `set_final_overview` flips status to 'done' atomically. If the
        # overview path was never set (e.g. final synthesis crashed and the simple
        # overview also failed) the status is still 'running'; force-set it
        # here so the session doesn't appear to be running forever after exit.
        # For EXTERNAL stops we don't overwrite the user-set 'paused' /
        # 'aborted' status.
        if stop_reason == StopReason.TASK_FAILURE:
            await sess_repo.set_status(conn, session.id, "failed")
        elif stop_reason != StopReason.EXTERNAL:
            await sess_repo.set_status(conn, session.id, "done")

        # Acceptance is deterministic and model-free. Persist it after the
        # final overview and terminal status are durable, so the UI and CI can
        # distinguish a finished session from a scientifically usable one.
        try:
            from ..orchestrator.session_acceptance import (
                run_session_acceptance,
                write_session_acceptance,
            )

            acceptance = await run_session_acceptance(
                acceptance_cfg or self.cfg,
                session.id,
            )
            write_session_acceptance(self.cfg, acceptance)
            await self._emit(
                conn,
                session.id,
                "session_acceptance_completed",
                {"status": acceptance.status, "failed_checks": acceptance.as_dict()["failed_checks"]},
            )
        except Exception as e:
            # Acceptance must never hide the final overview or leave a worker
            # stuck after the scientific run itself has finished.
            log.exception("session_acceptance_failed", err=str(e), session_id=session.id)

        await self._emit(conn, session.id, "session_done",
                         {"stop_reason": stop_reason.value if stop_reason else None})

    async def _write_simple_overview(
        self,
        conn: aiosqlite.Connection,
        session: Session,
        stop_reason: StopReason | None,
    ) -> str:
        hyps = await hyp_repo.list_for_session(conn, session.id)
        decisions = latest_iteration_decisions_for_session(self.cfg, session.id)
        parts: list[str] = [
            f"# Research overview 鈥?session {session.id}",
            f"\n**Goal.** {session.research_goal}\n",
            f"**Hypotheses produced.** {len(hyps)}",
            "",
        ]
        parts[0] = f"# Breeding scientist overview - session {session.id}"
        parts.append(
            termination_report_markdown(
                session=session,
                hypotheses=hyps,
                decisions=decisions,
                stop_reason=stop_reason,
                language="en",
            ).strip()
        )
        parts.append("")
        for i, h in enumerate(hyps, 1):
            parts.append(f"## {i}. {h.title or h.id}")
            parts.append(
                f"`{h.id}` 鈥?strategy `{h.strategy}` 鈥?state `{h.state}` "
                f"鈥?pairwise calibration `{h.calibration_score:.0f}`"
                if h.calibration_score is not None else
                f"`{h.id}` 鈥?strategy `{h.strategy}` 鈥?state `{h.state}`"
            )
            parts.append(h.summary or "(no summary)")
            decision = decisions.get(h.id) or {}
            decision_score = decision.get("total_score")
            score_text = (
                f" - composite score `{decision_score:.1f}`"
                if isinstance(decision_score, int | float)
                else ""
            )
            parts[-2] = (
                f"`{h.id}` - strategy `{h.strategy}` - lifecycle `{h.state}`"
                f"{score_text}"
                + (
                    f" - pairwise calibration `{h.calibration_score:.0f}`"
                    if h.calibration_score is not None
                    else ""
                )
            )
            reviews = await rev_repo.list_for_hypothesis(conn, h.id)
            if reviews:
                parts.append("\n**Breeding review notes:**")
                for r in reviews:
                    parts.append(
                        f"- *{r.kind}* 鈥?verdict `{r.verdict or '?'}` "
                        f"(n={r.scores.novelty}, c={r.scores.correctness}, "
                        f"t={r.scores.testability})"
                    )
            parts.append("")
        body = "\n".join(parts)
        return await write_text(self.cfg, session.id, "final", "overview", ".md", body)

    # ----------------------------- helpers ----------------------------- #

    def _build_agents(self, deps: AgentDeps) -> dict[str, object]:
        evidence_curator = EvidenceCuratorAgent(deps)
        iteration_decider = IterationOrchestratorAgent(deps)
        validation_planner = ValidationPlannerAgent(deps)
        risk_reviewer = RiskReviewerAgent(deps)
        breeding_designer_agent = BreedingDesignerAgent(deps)
        evidence_review_agent = EvidenceReviewAgent(deps)
        pairwise_stage = IterationOrchestratorRankingStage(deps)

        breeding_designer_routes: dict[str, object] = {
            "DesignHypothesis": breeding_designer_agent,
            "DirectHypothesisDesign": breeding_designer_agent,
        }
        iteration_routes: dict[str, object] = {
            "DecideIteration": iteration_decider,
            "QueuePairwiseCalibration": pairwise_stage,
            "RunPairwiseCalibration": pairwise_stage,
        }
        risk_reviewer_routes: dict[str, object] = {
            "ReviewRisk": risk_reviewer,
            "AssessHypothesisEvidence": evidence_review_agent,
        }
        out: dict[str, object] = {
            "evidence_curator": evidence_curator,
            "breeding_designer": _ActionRouter(breeding_designer_routes),
            "iteration_orchestrator": _ActionRouter(iteration_routes),
            "validation_planner": validation_planner,
            "risk_reviewer": _ActionRouter(risk_reviewer_routes),
        }
        from .route_revision import RouteRevisionAgent

        route_revision_agent = RouteRevisionAgent(deps)
        breeding_designer_routes["ReviseOrExpandRoute"] = route_revision_agent
        iteration_orchestrator_synthesis = IterationOrchestratorSynthesisStage(deps)
        iteration_routes["SynthesizeIterationFeedback"] = iteration_orchestrator_synthesis
        iteration_routes["GenerateFinalBreedingOverview"] = iteration_orchestrator_synthesis
        return out

    async def _emit(
        self,
        conn: aiosqlite.Connection,
        session_id: str,
        event: str,
        payload: dict[str, Any] | None = None,
    ) -> None:
        payload = decorate_agent_payload(payload)
        await events_repo.emit(
            conn, session_id=session_id, task_id=None, agent="supervisor",
            event=event, payload=payload,
        )
        await GLOBAL_BUS.publish(session_id, event, payload)


# ----------------------------- helpers ----------------------------- #


def _human_preference(session_id: str, text: str):
    from ..models import SystemFeedback

    return SystemFeedback(
        id=ids.feedback_id(), session_id=session_id,
        created_at=datetime.now(UTC),
        source="human", kind="preference",
        target_id=None, text=text, active=True,
    )


def _resolve_initial_hypothesis_count(
    plan: ResearchPlan,
    *,
    requested: int,
    run_max: int,
) -> int:
    """Resolve the first BFRS design count from parsed goal boundaries."""

    count = _positive_int_or_none(plan.initial_hypothesis_count) or requested
    upper_bound = _hypothesis_count_limit(plan, run_max=run_max)
    return max(1, min(int(count), upper_bound))


def _apply_explicit_hypothesis_bounds(
    plan: ResearchPlan,
    *,
    requested_initial: int | None = None,
    requested_max: int | None = None,
) -> ResearchPlan:
    """Apply explicit UI/CLI hypothesis bounds over model-parsed bounds.

    The Goal Interpreter may infer a conservative cap from natural language.
    Explicit UI/CLI values are stronger user constraints. The initial count is
    raised to the requested value when supplied, while the total cap is
    clamped so the plan remains internally consistent.
    """

    initial = _positive_int_or_none(requested_initial)
    limit = _positive_int_or_none(requested_max)
    if initial is None and limit is None:
        return plan

    parsed_initial = _positive_int_or_none(plan.initial_hypothesis_count)
    parsed_limit = _positive_int_or_none(plan.max_hypothesis_count)
    effective_initial = initial or parsed_initial
    effective_limit = limit or parsed_limit
    if initial is not None and (effective_limit is None or effective_limit < initial):
        effective_limit = initial
    if effective_initial is not None and effective_limit is not None:
        effective_initial = min(effective_initial, effective_limit)
    return plan.model_copy(
        update={
            "initial_hypothesis_count": effective_initial,
            "max_hypothesis_count": effective_limit,
        }
    )


async def _can_enqueue_more_hypotheses(
    conn: aiosqlite.Connection,
    session: Session,
    *,
    run_max: int,
) -> bool:
    gate = await _hypothesis_design_gate(conn, session, run_max=run_max)
    return bool(gate["can_enqueue"])


async def _hypothesis_design_gate(
    conn: aiosqlite.Connection,
    session: Session,
    *,
    run_max: int,
) -> dict[str, int | bool]:
    limit = _hypothesis_count_limit(session.research_plan, run_max=run_max)
    current = len(await hyp_repo.list_for_session(conn, session.id))
    # Design tasks reserve hypothesis slots before their LLM calls finish. Count
    # those reservations so concurrent iteration decisions cannot overshoot the cap.
    async with conn.execute(
        """SELECT COUNT(*) AS n
             FROM tasks
            WHERE session_id=?
              AND agent='breeding_designer'
              AND action='DesignHypothesis'
              AND status IN ('pending', 'leased', 'in_progress')""",
        (session.id,),
    ) as cur:
        row = await cur.fetchone()
    reserved = int(row["n"] if row else 0)
    effective_current = current + reserved
    return {
        "can_enqueue": effective_current < limit,
        "current_count": effective_current,
        "limit": limit,
    }


def _hypothesis_count_limit(plan: ResearchPlan, *, run_max: int) -> int:
    max_from_plan = _positive_int_or_none(plan.max_hypothesis_count)
    run_bound = _positive_int_or_none(run_max) or 1
    return max(1, min(value for value in (max_from_plan, run_bound) if value is not None))


def _positive_int_or_none(value: Any) -> int | None:
    try:
        parsed = int(value)
    except (TypeError, ValueError):
        return None
    return parsed if parsed > 0 else None
