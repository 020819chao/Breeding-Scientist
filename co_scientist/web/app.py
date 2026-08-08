"""FastAPI web UI for the co-scientist.

One process per host: launching `co-scientist serve` runs both the API + UI
and the worker pool 鈥?the queue is DB-backed so CLI `co-scientist run` in a
separate terminal feeds tasks to whatever Supervisor is currently active.

The UI is server-side Jinja2 + htmx for partial updates + SSE for live events.
No JS build step. Pico.css for default styling.
"""

from __future__ import annotations

import asyncio
import contextlib
import csv
from io import BytesIO, StringIO
import json
import logging as stdlib_logging
import re
import shutil
import zipfile
from collections.abc import AsyncIterator
from datetime import UTC, datetime
from pathlib import Path
from typing import Annotated, Any
from urllib.parse import quote as _url_quote

import aiosqlite
from fastapi import BackgroundTasks, FastAPI, File, Form, HTTPException, Request, UploadFile
from fastapi.encoders import jsonable_encoder
from fastapi.responses import FileResponse, HTMLResponse, JSONResponse, RedirectResponse, Response
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates
from sse_starlette.sse import EventSourceResponse

from .. import ids
from ..agents.display import (
    ACTION_LABELS_ZH,
    EVENT_LABELS,
    SIX_AGENT_ORDER,
    agent_step_name,
    core_agent_name,
    decorate_agent_payload,
    hypothesis_lifecycle_label,
    hypothesis_strategy_label,
    localize_decision_text,
    localize_gap_text,
    localize_iteration_decision,
    review_kind_label,
    review_verdict_label,
)
from ..config import Config, load_config
from ..knowledge.folder_monitor import KnowledgeFolderMonitor
from ..knowledge.breeding_libraries import (
    FIELD_TRIAL_COLUMNS,
    MARKER_QTL_COLUMNS,
    PHENOTYPE_PROTOCOL_COLUMNS,
)
from ..knowledge.germplasm import EXPECTED_COLUMNS as GERMPLASM_COLUMNS
from ..knowledge.intake import import_knowledge_batch
from ..knowledge.versions import (
    compare_version_files,
    complete_pending_batch,
    find_archived_version,
    find_pending_batch,
    load_batch_history,
    rollback_knowledge_version,
    save_pending_batch,
)
from ..knowledge.web_intake import (
    active_root_from_config,
    catalog_summary,
    extract_batch_zip,
    save_uploaded_zip,
)
from ..logging import get_logger
from ..models import AgentOutputReview, SystemFeedback, Task
from ..orchestrator.events import GLOBAL_BUS
from ..prioritization.composite import (
    composite_breeding_rank_score as _shared_composite_breeding_rank_score,
)
from ..prioritization.composite import (
    iteration_audit_summary as _shared_iteration_audit_summary,
)
from ..prioritization.composite import (
    latest_iteration_decisions_for_session as _shared_latest_iteration_decisions_for_session,
)
from ..prioritization.composite import (
    rank_hypotheses_for_prioritized_routes as _shared_rank_hypotheses_for_prioritized_routes,
)
from ..prioritization.composite import (
    route_admission_summary as _shared_route_admission_summary,
)
from ..storage import db as db_mod
from ..storage.artifacts import read_json
from ..storage.repos import events as events_repo
from ..storage.repos import agent_output_reviews as output_reviews_repo
from ..storage.repos import feedback as fb_repo
from ..storage.repos import hypotheses as hyp_repo
from ..storage.repos import reviews as rev_repo
from ..storage.repos import sessions as sess_repo
from ..storage.repos import tasks as task_repo
from ..storage.repos import transcripts as tx_repo
from .sanitize import render_markdown

log = get_logger("web")
HERE = Path(__file__).parent
TEMPLATES = Jinja2Templates(directory=HERE / "templates")
FRONTEND_DIST = HERE.parents[1] / "frontend" / "dist"


def hypothesis_lifecycle_class(state: Any) -> str:
    return _css_token(hypothesis_lifecycle_label(state))


def _review_view_models(reviews: list[Any]) -> list[dict[str, Any]]:
    out: list[dict[str, Any]] = []
    for review in reviews:
        scores = getattr(review, "scores", None)
        score_items = []
        for label, value in (
            ("evidence fit", getattr(scores, "correctness", None)),
            ("testability", getattr(scores, "testability", None)),
            ("feasibility", getattr(scores, "feasibility", None)),
            ("novelty", getattr(scores, "novelty", None)),
        ):
            if value is not None:
                score_items.append({"label": label, "value": float(value)})
        verdict = str(getattr(review, "verdict", "") or "unknown")
        kind = str(getattr(review, "kind", "") or "review")
        out.append(
            {
                "id": str(getattr(review, "id", "")),
                "kind_label": review_kind_label(kind),
                "verdict": verdict,
                "verdict_label": review_verdict_label(verdict),
                "score_items": score_items,
                "body_html": render_markdown(str(getattr(review, "body", "") or "")),
            }
        )
    return out


def _localized_iteration_decisions(
    decisions: list[dict[str, Any]],
    *,
    language: str,
) -> list[dict[str, Any]]:
    if language != "zh":
        return decisions
    return [_localized_iteration_decision(decision) for decision in decisions]


def _localized_iteration_decision(decision: dict[str, Any]) -> dict[str, Any]:
    return localize_iteration_decision(decision)


def _localize_decision_text(text: str) -> str:
    return localize_decision_text(text)


def _localize_gap_text(text: str) -> str:
    return localize_gap_text(text)


TEMPLATES.env.globals["hypothesis_lifecycle_label"] = hypothesis_lifecycle_label
TEMPLATES.env.globals["hypothesis_lifecycle_class"] = hypothesis_lifecycle_class
TEMPLATES.env.globals["hypothesis_strategy_label"] = hypothesis_strategy_label
TEMPLATES.env.globals["localize_gap_text"] = localize_gap_text


def create_app(cfg: Config | None = None) -> FastAPI:
    cfg = cfg or load_config()
    monitor = KnowledgeFolderMonitor(cfg)

    @contextlib.asynccontextmanager
    async def lifespan(_app: FastAPI) -> AsyncIterator[None]:
        monitor_task: asyncio.Task[None] | None = None
        await db_mod.init_db(cfg)
        if cfg.knowledge.incoming_watch_enabled:
            monitor_task = asyncio.create_task(monitor.run_forever())
        try:
            yield
        finally:
            monitor.stop()
            if monitor_task is not None:
                await monitor_task

    app = FastAPI(title="AI Breeding Scientist", lifespan=lifespan)
    app.state.cfg = cfg
    app.state.knowledge_monitor = monitor
    app.state.background_runs: dict[str, asyncio.Task] = {}

    # Static
    app.mount("/static", StaticFiles(directory=HERE / "static"), name="static")
    if FRONTEND_DIST.is_dir():
        app.mount("/__frontend__", StaticFiles(directory=FRONTEND_DIST), name="frontend")

    # ----------------------------- pages ----------------------------- #

    @app.get("/", response_class=HTMLResponse)
    async def index(request: Request) -> HTMLResponse:
        frontend_index = FRONTEND_DIST / "index.html"
        if frontend_index.is_file():
            return FileResponse(frontend_index)
        rows = await _list_sessions(cfg)
        evidence_view = (
            _build_evidence_interpretation(parsed_payload)
            if "/evidence/package_" in artifact_path.replace("\\", "/")
            else None
        )
        if evidence_view is not None and (FRONTEND_DIST / "index.html").is_file() and "text/html" in request.headers.get("accept", ""):
            return FileResponse(FRONTEND_DIST / "index.html")
        return TEMPLATES.TemplateResponse(
            request, "index.html", {"sessions": rows}
        )

    @app.get("/sessions", response_class=HTMLResponse)
    async def sessions_workspace(request: Request) -> HTMLResponse:
        frontend_index = FRONTEND_DIST / "index.html"
        if frontend_index.is_file():
            return FileResponse(frontend_index)
        rows = await _list_sessions(cfg)
        return TEMPLATES.TemplateResponse(
            request, "index.html", {"sessions": rows}
        )

    @app.get("/knowledge", response_class=HTMLResponse)
    async def knowledge_import_form(request: Request) -> HTMLResponse:
        if (FRONTEND_DIST / "index.html").exists():
            return FileResponse(FRONTEND_DIST / "index.html")
        return TEMPLATES.TemplateResponse(
            request,
            "knowledge_import.html",
            {
                "catalog": catalog_summary(cfg),
                "history": load_batch_history(cfg),
                "monitor": monitor.status(),
                "direct_activation_allowed": cfg.knowledge.allow_direct_activation,
                "result": None,
            },
        )

    @app.get("/api/knowledge/intake")
    async def knowledge_intake_api() -> JSONResponse:
        return JSONResponse(
            jsonable_encoder(
                {
                    "catalog": catalog_summary(cfg),
                    "history": load_batch_history(cfg),
                    "monitor": monitor.status(),
                    "direct_activation_allowed": cfg.knowledge.allow_direct_activation,
                }
            )
        )

    @app.get("/knowledge/template")
    async def download_knowledge_batch_template() -> Response:
        return _knowledge_batch_zip_response(demo=False)

    @app.get("/knowledge/demo")
    async def download_knowledge_demo_batch() -> Response:
        """Download a filled foxtail-millet demo batch for a safe dry run."""
        return _knowledge_batch_zip_response(demo=True)

    @app.get("/api/knowledge/monitor")
    async def knowledge_monitor_status() -> JSONResponse:
        return JSONResponse(monitor.status())

    @app.get("/knowledge/monitor", response_class=HTMLResponse)
    async def knowledge_monitor_dashboard(request: Request) -> HTMLResponse:
        dashboard = monitor.dashboard()
        return TEMPLATES.TemplateResponse(
            request,
            "knowledge_monitor.html",
            {
                **dashboard,
                "message": request.query_params.get("message"),
                "error": request.query_params.get("error"),
            },
        )

    @app.get("/api/knowledge/monitor/dashboard")
    async def knowledge_monitor_dashboard_api() -> JSONResponse:
        return JSONResponse(monitor.dashboard())

    @app.post("/knowledge/monitor/retry/{filename:path}")
    async def retry_quarantined_knowledge(request: Request, filename: str) -> RedirectResponse:
        try:
            monitor.retry_quarantined(filename)
        except (OSError, ValueError) as exc:
            return RedirectResponse(
                f"/knowledge/monitor?error={_url_quote(str(exc))}", status_code=303
            )
        return RedirectResponse("/knowledge/monitor?message=已重新送回预检队列", status_code=303)

    @app.get("/knowledge/batches/{batch_id}", response_class=HTMLResponse)
    async def knowledge_batch_detail(request: Request, batch_id: str) -> HTMLResponse:
        if (FRONTEND_DIST / "index.html").exists():
            return FileResponse(FRONTEND_DIST / "index.html")
        history = load_batch_history(cfg)
        record = next((row for row in history if row.get("batch_id") == batch_id), None)
        if record is None:
            raise HTTPException(status_code=404, detail="knowledge batch not found")
        previous = _previous_batch_record(history, record)
        return TEMPLATES.TemplateResponse(
            request,
            "knowledge_batch_detail.html",
            {
                "catalog": catalog_summary(cfg),
                "record": record,
                "monitor": monitor.status(),
                "previous": previous,
                "stats_diff": _batch_stats_diff(record.get("stats"), previous.get("stats") if previous else None),
                "file_diff": _batch_file_diff(record, previous),
                "approval_result": None,
                "rollback_result": None,
            },
        )

    @app.get("/api/knowledge/batches/{batch_id}/detail")
    async def knowledge_batch_detail_api(batch_id: str) -> JSONResponse:
        history = load_batch_history(cfg)
        record = next((row for row in history if row.get("batch_id") == batch_id), None)
        if record is None:
            raise HTTPException(status_code=404, detail="knowledge batch not found")
        previous = _previous_batch_record(history, record)
        return JSONResponse(
            jsonable_encoder(
                {
                    "catalog": catalog_summary(cfg),
                    "record": record,
                    "monitor": monitor.status(),
                    "previous": previous,
                    "stats_diff": _batch_stats_diff(
                        record.get("stats"), previous.get("stats") if previous else None
                    ),
                    "file_diff": _batch_file_diff(record, previous),
                }
            )
        )

    @app.post("/knowledge/batches/{batch_id}/approve", response_class=HTMLResponse)
    async def approve_knowledge_batch(
        request: Request,
        batch_id: str,
        reviewer: Annotated[str, Form()] = "",
        note: Annotated[str, Form()] = "",
    ) -> HTMLResponse:
        history = load_batch_history(cfg)
        record = next((row for row in history if row.get("batch_id") == batch_id), None)
        if record is None:
            raise HTTPException(status_code=404, detail="knowledge batch not found")
        result: dict[str, Any]
        try:
            reviewer = reviewer.strip()
            if not reviewer:
                raise ValueError("reviewer is required")
            if not record.get("is_pending"):
                raise ValueError("selected batch is not waiting for approval")
            pending_dir = find_pending_batch(cfg, batch_id)
            if pending_dir is None:
                raise ValueError("pending batch package is missing")
            await asyncio.to_thread(
                import_knowledge_batch,
                pending_dir,
                active_root=active_root_from_config(cfg),
                catalog_path=Path(cfg.active_knowledge_catalog_path),
                approval={
                    "reviewer": reviewer,
                    "note": note.strip(),
                    "reviewed_at": datetime.now(UTC).isoformat(),
                },
                allow_existing_pending=True,
            )
            await asyncio.to_thread(complete_pending_batch, active_root_from_config(cfg), batch_id)
            result = {"ok": True, "batch_id": batch_id, "reviewer": reviewer}
        except (OSError, ValueError) as exc:
            result = {"ok": False, "error": str(exc)}
        history = load_batch_history(cfg)
        record = next((row for row in history if row.get("batch_id") == batch_id), record)
        if "application/json" in request.headers.get("accept", ""):
            previous = _previous_batch_record(history, record)
            return JSONResponse(
                jsonable_encoder(
                    {
                        "approval_result": result,
                        "catalog": catalog_summary(cfg),
                        "record": record,
                        "monitor": monitor.status(),
                        "previous": previous,
                        "stats_diff": _batch_stats_diff(
                            record.get("stats"), previous.get("stats") if previous else None
                        ),
                        "file_diff": _batch_file_diff(record, previous),
                    }
                )
            )
        previous = _previous_batch_record(history, record)
        return TEMPLATES.TemplateResponse(
            request,
            "knowledge_batch_detail.html",
            {
                "catalog": catalog_summary(cfg),
                "record": record,
                "monitor": monitor.status(),
                "previous": previous,
                "stats_diff": _batch_stats_diff(record.get("stats"), previous.get("stats") if previous else None),
                "file_diff": _batch_file_diff(record, previous),
                "approval_result": result,
                "rollback_result": None,
            },
        )

    @app.post("/knowledge/batches/{batch_id}/rollback", response_class=HTMLResponse)
    async def rollback_knowledge_batch(
        request: Request,
        batch_id: str,
        confirm: Annotated[bool, Form()] = False,
    ) -> HTMLResponse:
        history = load_batch_history(cfg)
        record = next((row for row in history if row.get("batch_id") == batch_id), None)
        if record is None:
            raise HTTPException(status_code=404, detail="knowledge batch not found")
        result: dict[str, Any]
        try:
            if not confirm:
                raise ValueError("请先确认回滚操作")
            version_dir = find_archived_version(cfg, batch_id)
            if version_dir is None:
                raise ValueError("selected knowledge batch has no complete archive")
            result = await asyncio.to_thread(
                rollback_knowledge_version,
                active_root_from_config(cfg),
                Path(cfg.active_knowledge_catalog_path),
                version_dir,
            )
            result["ok"] = True
        except (OSError, ValueError) as exc:
            result = {"ok": False, "error": str(exc)}
        history = load_batch_history(cfg)
        record = next((row for row in history if row.get("batch_id") == batch_id), record)
        if "application/json" in request.headers.get("accept", ""):
            previous = _previous_batch_record(history, record)
            return JSONResponse(
                jsonable_encoder(
                    {
                        "rollback_result": result,
                        "catalog": catalog_summary(cfg),
                        "record": record,
                        "monitor": monitor.status(),
                        "previous": previous,
                        "stats_diff": _batch_stats_diff(
                            record.get("stats"), previous.get("stats") if previous else None
                        ),
                        "file_diff": _batch_file_diff(record, previous),
                    }
                )
            )
        previous = _previous_batch_record(history, record)
        return TEMPLATES.TemplateResponse(
            request,
            "knowledge_batch_detail.html",
            {
                "catalog": catalog_summary(cfg),
                "record": record,
                "monitor": monitor.status(),
                "previous": previous,
                "stats_diff": _batch_stats_diff(record.get("stats"), previous.get("stats") if previous else None),
                "file_diff": _batch_file_diff(record, previous),
                "approval_result": None,
                "rollback_result": result,
            },
        )

    @app.post("/knowledge/upload", response_class=HTMLResponse)
    async def upload_knowledge_batch(
        request: Request,
        batch_file: Annotated[UploadFile, File(...)],
        dry_run: Annotated[bool, Form()] = False,
    ) -> HTMLResponse:
        """Receive one portable ZIP and run the existing validated importer."""

        from uuid import uuid4

        job_id = f"imp_{uuid4().hex[:16]}"
        root = active_root_from_config(cfg).parent / "web_uploads" / job_id
        zip_path = root / "upload.zip"
        extract_root = root / "extracted"
        result: dict[str, Any] = {
            "ok": False,
            "job_id": job_id,
            "filename": batch_file.filename or "未命名文件",
            "dry_run": dry_run,
        }
        try:
            if not (batch_file.filename or "").lower().endswith(".zip"):
                raise ValueError("请上传 .zip 格式的知识批次包")
            await asyncio.to_thread(save_uploaded_zip, batch_file, zip_path)
            batch_dir = await asyncio.to_thread(extract_batch_zip, zip_path, extract_root)
            effective_dry_run = dry_run or not cfg.knowledge.allow_direct_activation
            result["dry_run"] = effective_dry_run
            imported = await asyncio.to_thread(
                import_knowledge_batch,
                batch_dir,
                active_root=active_root_from_config(cfg),
                catalog_path=Path(cfg.active_knowledge_catalog_path),
                dry_run=effective_dry_run,
            )
            result.update(
                {
                    "ok": True,
                    "batch_id": imported.batch_id,
                    "activated": imported.activated,
                    "stats": imported.stats,
                }
            )
            if effective_dry_run:
                manifest = json.loads((batch_dir / "manifest.json").read_text(encoding="utf-8"))
                pending_dir = await asyncio.to_thread(
                    save_pending_batch,
                    active_root_from_config(cfg),
                    batch_dir,
                    batch_id=imported.batch_id,
                    crop_scope=list(manifest.get("crop_scope") or []),
                    stats=imported.stats,
                    source_filename=batch_file.filename or "未命名文件",
                )
                result.update(
                    {
                        "lifecycle_status": "preflight_passed",
                        "approval_status": "pending_review",
                        "pending_path": str(pending_dir),
                    }
                )
            else:
                result.update(
                    {
                        "lifecycle_status": "active",
                        "approval_status": "not_required",
                    }
                )
        except (OSError, ValueError) as exc:
            result["error"] = str(exc)
        finally:
            await batch_file.close()
            if root.exists():
                shutil.rmtree(root, ignore_errors=True)
        if "application/json" in request.headers.get("accept", ""):
            return JSONResponse(
                jsonable_encoder(
                    {
                        "result": result,
                        "catalog": catalog_summary(cfg),
                        "history": load_batch_history(cfg),
                        "monitor": monitor.status(),
                        "direct_activation_allowed": cfg.knowledge.allow_direct_activation,
                    }
                )
            )
        return TEMPLATES.TemplateResponse(
            request,
            "knowledge_import.html",
            {
                "catalog": catalog_summary(cfg),
                "history": load_batch_history(cfg),
                "monitor": monitor.status(),
                "direct_activation_allowed": cfg.knowledge.allow_direct_activation,
                "result": result,
            },
        )

    @app.get("/sessions/new", response_class=HTMLResponse)
    async def new_session_form(request: Request) -> HTMLResponse:
        frontend_index = FRONTEND_DIST / "index.html"
        if frontend_index.exists():
            return FileResponse(frontend_index)
        return TEMPLATES.TemplateResponse(
            request, "new_session.html", {"default_budget": cfg.run.budget_usd}
        )

    @app.post("/sessions/new")
    async def create_session(
        request: Request,
        background_tasks: BackgroundTasks,
        goal: str = Form(...),
        preferences: str = Form(""),
        budget_usd: float = Form(cfg.run.budget_usd),
        n_initial: int = Form(3),
        max_hypotheses: int | None = Form(None),
        wall_clock_seconds: int = Form(cfg.run.wall_clock_seconds),
    ) -> RedirectResponse:
        from ..agents.supervisor import Supervisor

        # Hand the Supervisor a fresh Config copy so per-session knobs don't leak.
        sup_cfg = cfg.model_copy(deep=True)
        sup_cfg.run.budget_usd = budget_usd
        sup_cfg.run.wall_clock_seconds = wall_clock_seconds
        sup = Supervisor(sup_cfg)

        async def _run() -> None:
            await sup.run_session(
                goal=goal, preferences_text=preferences or None,
                n_initial=n_initial,
                max_hypothesis_count=max_hypotheses,
                wall_clock_seconds=wall_clock_seconds,
            )

        task = asyncio.create_task(_run())
        task_key = f"new_session::{id(task)}"
        app.state.background_runs[task_key] = task

        def _forget_background_run(done: asyncio.Task) -> None:
            app.state.background_runs.pop(task_key, None)
            try:
                done.result()
            except asyncio.CancelledError:
                log.warning("background_run_cancelled", task_key=task_key)
            except Exception as exc:
                log.exception("background_run_failed", task_key=task_key, err=str(exc))

        task.add_done_callback(_forget_background_run)
        return RedirectResponse(url="/", status_code=303)

    @app.get("/sessions/{session_id}", response_class=HTMLResponse)
    async def session_detail(request: Request, session_id: str) -> HTMLResponse:
        frontend_index = FRONTEND_DIST / "index.html"
        # Keep the server-rendered page available to lightweight API/test clients
        # while normal browser navigation uses the Vue workspace.
        if frontend_index.exists() and "text/html" in request.headers.get("accept", ""):
            return FileResponse(frontend_index)
        conn = await db_mod.connect(cfg)
        try:
            session = await sess_repo.fetch(conn, session_id)
            if session is None:
                raise HTTPException(status_code=404, detail="session not found")
            hyps = await hyp_repo.list_for_session(conn, session_id)
            recent_pairwise_calibrations = await _recent_pairwise_calibrations(
                conn,
                session_id,
                limit=20,
            )
            pairwise_summary = await _pairwise_calibration_summary(conn, session_id)
            usage = await tx_repo.usage_summary(conn, session_id)
            germplasm_resources = _load_germplasm_resource_rows(cfg, session.final_overview)
            evidence_graph = _load_evidence_graph_view(cfg, session_id)
            latest_iteration_decisions = _latest_iteration_decisions_for_session(cfg, session_id)
            route_revision_graph = _load_route_revision_graph_view(
                hyps,
                latest_iteration_decisions,
            )
            iteration_audit = _iteration_audit_summary(latest_iteration_decisions)
            ranked_hypotheses, prioritized_route_scores = _rank_hypotheses_for_prioritized_routes(
                hyps,
                latest_iteration_decisions,
            )
            min_pairwise_calibrations = (
                cfg.termination.effective_min_pairwise_calibrations_per_hypothesis
            )
            route_admissions = {
                hypothesis.id: _localized_route_admission(
                    _shared_route_admission_summary(
                        hypothesis,
                        latest_iteration_decisions.get(hypothesis.id),
                        min_pairwise_calibrations=min_pairwise_calibrations,
                    )
                )
                for hypothesis in hyps
            }
            ranked_hypotheses = [
                hypothesis
                for hypothesis in ranked_hypotheses
                if route_admissions[hypothesis.id]["eligible"]
            ]
            pending_hypotheses = [
                hypothesis
                for hypothesis in hyps
                if not route_admissions[hypothesis.id]["eligible"]
            ]
            display_iteration_decisions = {
                hypothesis_id: _localized_iteration_decision(decision)
                for hypothesis_id, decision in latest_iteration_decisions.items()
            }
            recent_events = await events_repo.recent(conn, session_id, limit=100)
            six_agent_summary = await _six_agent_task_summary(conn, session)
            six_agent_outputs = await _six_agent_output_summary(
                cfg,
                conn,
                session,
                hypotheses=hyps,
                decisions=latest_iteration_decisions,
                pairwise_summary=pairwise_summary,
            )
            _decorate_agent_output_reviews(
                six_agent_outputs,
                await output_reviews_repo.latest_for_session(conn, session_id),
            )
            output_by_agent = {item["name"]: item for item in six_agent_outputs}
            for agent in six_agent_summary:
                agent.update(
                    {
                        key: value
                        for key, value in output_by_agent.get(agent["name"], {}).items()
                        if key != "name"
                    }
                )
            acceptance = _load_session_acceptance(cfg, session_id)
            knowledge_snapshot = _session_knowledge_snapshot(session)
            termination_summary = _termination_summary(
                session=session,
                hypotheses=hyps,
                decisions=latest_iteration_decisions,
                iteration_audit=iteration_audit,
                recent_events=recent_events,
            )
            return TEMPLATES.TemplateResponse(
                request,
                "session_detail.html",
                {
                    "session": session,
                    "hypotheses": hyps,
                    "ranked_hypotheses": ranked_hypotheses,
                    "pending_hypotheses": pending_hypotheses,
                    "recent_pairwise_calibrations": recent_pairwise_calibrations,
                    "pairwise_summary": pairwise_summary,
                    "usage": usage,
                    "germplasm_resources": germplasm_resources,
                    "evidence_graph": evidence_graph,
                    "route_revision_graph": route_revision_graph,
                    "latest_iteration_decisions": latest_iteration_decisions,
                    "display_iteration_decisions": display_iteration_decisions,
                    "iteration_audit": iteration_audit,
                    "prioritized_route_scores": prioritized_route_scores,
                    "route_admissions": route_admissions,
                    "min_pairwise_calibrations": min_pairwise_calibrations,
                    "termination_summary": termination_summary,
                    "six_agent_summary": six_agent_summary,
                    "acceptance": acceptance,
                    "knowledge_snapshot": knowledge_snapshot,
                    "event_labels": EVENT_LABELS,
                },
            )
        finally:
            await conn.close()

    @app.get("/api/sessions/{session_id}/detail")
    async def api_session_detail(session_id: str) -> JSONResponse:
        """Return the complete detail-page payload for the Vue client.

        Keep this data contract alongside the existing Jinja page while the
        detail view is migrated. The existing HTML route remains untouched as
        a fallback until the Vue view has passed functional verification.
        """
        conn = await db_mod.connect(cfg)
        try:
            session = await sess_repo.fetch(conn, session_id)
            if session is None:
                raise HTTPException(status_code=404, detail="session not found")
            hyps = await hyp_repo.list_for_session(conn, session_id)
            recent_pairwise_calibrations = await _recent_pairwise_calibrations(
                conn,
                session_id,
                limit=20,
            )
            pairwise_summary = await _pairwise_calibration_summary(conn, session_id)
            usage = await tx_repo.usage_summary(conn, session_id)
            germplasm_resources = _load_germplasm_resource_rows(cfg, session.final_overview)
            evidence_graph = _load_evidence_graph_view(cfg, session_id)
            latest_iteration_decisions = _latest_iteration_decisions_for_session(cfg, session_id)
            route_revision_graph = _load_route_revision_graph_view(
                hyps,
                latest_iteration_decisions,
            )
            iteration_audit = _iteration_audit_summary(latest_iteration_decisions)
            ranked_hypotheses, prioritized_route_scores = _rank_hypotheses_for_prioritized_routes(
                hyps,
                latest_iteration_decisions,
            )
            min_pairwise_calibrations = (
                cfg.termination.effective_min_pairwise_calibrations_per_hypothesis
            )
            route_admissions = {
                hypothesis.id: _localized_route_admission(
                    _shared_route_admission_summary(
                        hypothesis,
                        latest_iteration_decisions.get(hypothesis.id),
                        min_pairwise_calibrations=min_pairwise_calibrations,
                    )
                )
                for hypothesis in hyps
            }
            ranked_hypotheses = [
                hypothesis
                for hypothesis in ranked_hypotheses
                if route_admissions[hypothesis.id]["eligible"]
            ]
            pending_hypotheses = [
                hypothesis
                for hypothesis in hyps
                if not route_admissions[hypothesis.id]["eligible"]
            ]
            display_iteration_decisions = {
                hypothesis_id: _localized_iteration_decision(decision)
                for hypothesis_id, decision in latest_iteration_decisions.items()
            }
            recent_events = await events_repo.recent(conn, session_id, limit=100)
            six_agent_summary = await _six_agent_task_summary(conn, session)
            six_agent_outputs = await _six_agent_output_summary(
                cfg,
                conn,
                session,
                hypotheses=hyps,
                decisions=latest_iteration_decisions,
                pairwise_summary=pairwise_summary,
            )
            _decorate_agent_output_reviews(
                six_agent_outputs,
                await output_reviews_repo.latest_for_session(conn, session_id),
            )
            output_by_agent = {item["name"]: item for item in six_agent_outputs}
            for agent in six_agent_summary:
                agent.update(
                    {
                        key: value
                        for key, value in output_by_agent.get(agent["name"], {}).items()
                        if key != "name"
                    }
                )
            acceptance = _load_session_acceptance(cfg, session_id)
            knowledge_snapshot = _session_knowledge_snapshot(session)
            termination_summary = _termination_summary(
                session=session,
                hypotheses=hyps,
                decisions=latest_iteration_decisions,
                iteration_audit=iteration_audit,
                recent_events=recent_events,
            )
            payload = {
                "session": session,
                "hypotheses": hyps,
                "ranked_hypotheses": ranked_hypotheses,
                "pending_hypotheses": pending_hypotheses,
                "recent_pairwise_calibrations": recent_pairwise_calibrations,
                "pairwise_summary": pairwise_summary,
                "usage": usage,
                "germplasm_resources": germplasm_resources,
                "evidence_graph": evidence_graph,
                "route_revision_graph": route_revision_graph,
                "latest_iteration_decisions": latest_iteration_decisions,
                "display_iteration_decisions": display_iteration_decisions,
                "iteration_audit": iteration_audit,
                "prioritized_route_scores": prioritized_route_scores,
                "route_admissions": route_admissions,
                "min_pairwise_calibrations": min_pairwise_calibrations,
                "termination_summary": termination_summary,
                "six_agent_summary": six_agent_summary,
                "acceptance": acceptance,
                "knowledge_snapshot": knowledge_snapshot,
                "event_labels": EVENT_LABELS,
            }
            return JSONResponse(jsonable_encoder(payload))
        finally:
            await conn.close()

    @app.get("/api/sessions/{session_id}/evidence-graph")
    async def api_evidence_graph(session_id: str) -> JSONResponse:
        conn = await db_mod.connect(cfg)
        try:
            session = await sess_repo.fetch(conn, session_id)
            if session is None:
                raise HTTPException(status_code=404, detail="session not found")
            return JSONResponse(jsonable_encoder({"session": session, "graph": _load_evidence_graph_view(cfg, session_id)}))
        finally:
            await conn.close()

    @app.get("/api/sessions/{session_id}/hypotheses/{hid}/evidence-subgraph")
    async def api_hypothesis_evidence_subgraph(session_id: str, hid: str) -> JSONResponse:
        conn = await db_mod.connect(cfg)
        try:
            session = await sess_repo.fetch(conn, session_id)
            hypothesis = await hyp_repo.fetch(conn, hid)
            if session is None or hypothesis is None:
                raise HTTPException(status_code=404, detail="not found")
            graph_view = _load_hypothesis_evidence_subgraph_view(cfg, session_id, hid)
            hypotheses = await hyp_repo.list_for_session(conn, session_id)
            decisions = _latest_iteration_decisions_for_session(cfg, session_id)
            graph_view["closed_loop"] = _hypothesis_closed_loop_context(
                hypotheses,
                decisions,
                hid,
                evidence_subgraph=graph_view,
            )
            return JSONResponse(
                jsonable_encoder(
                    {
                        "session": session,
                        "hypothesis": hypothesis,
                        "graph": graph_view,
                    }
                )
            )
        finally:
            await conn.close()

    @app.get("/api/sessions/{session_id}/overview")
    async def api_session_overview(session_id: str, lang: str = "zh") -> JSONResponse:
        """Return the rendered final report while keeping the native page intact."""
        conn = await db_mod.connect(cfg)
        try:
            session = await sess_repo.fetch(conn, session_id)
            if session is None or not session.final_overview:
                raise HTTPException(status_code=404, detail="no final overview yet for this session")

            base = cfg.data_dir.resolve()
            requested_language = "en" if lang.lower() == "en" else "zh"
            overview_rel = session.final_overview
            english_rel = str(Path(session.final_overview).with_name("overview_en.md"))
            chinese_rel = str(Path(session.final_overview).with_name("overview_zh.md"))
            has_english = (cfg.data_dir / english_rel).is_file()
            has_chinese = (cfg.data_dir / chinese_rel).is_file()
            actual_language = requested_language
            if requested_language == "en" and has_english:
                overview_rel = english_rel
            elif requested_language == "en" and has_chinese:
                actual_language = "zh"
                overview_rel = chinese_rel
            elif requested_language == "zh" and has_chinese:
                overview_rel = chinese_rel

            try:
                path = (cfg.data_dir / overview_rel).resolve()
                path.relative_to(base)
            except (ValueError, OSError) as e:
                log.error("overview_path_escape", session=session_id, err=str(e))
                raise HTTPException(status_code=404, detail="overview unavailable") from e
            if not path.is_file():
                raise HTTPException(status_code=404, detail="overview missing on disk")

            overview_md = path.read_text(encoding="utf-8")
            if requested_language == "zh" and not has_chinese:
                overview_md = _localize_legacy_chinese_overview(overview_md)
            linked_overview_md = _link_overview_references(overview_md, session.id)
            acceptance = _load_session_acceptance(cfg, session_id)
            knowledge_snapshot = _session_knowledge_snapshot(session)
            return JSONResponse(
                jsonable_encoder(
                    {
                        "session": session,
                        "overview_html": render_markdown(linked_overview_md),
                        "overview_md": overview_md,
                        "language": actual_language,
                        "requested_language": requested_language,
                        "has_english_overview": has_english,
                        "has_chinese_overview": has_chinese,
                        "acceptance": acceptance,
                        "knowledge_snapshot": knowledge_snapshot,
                    }
                )
            )
        finally:
            await conn.close()

    @app.post("/sessions/{session_id}/agent-outputs/review")
    async def review_agent_output(
        session_id: str,
        agent: str = Form(...),
        output_key: str = Form(...),
        output_path: str = Form(""),
        target_id: str = Form(""),
        status: str = Form(...),
        reviewer: str = Form(...),
        note: str = Form(""),
    ) -> RedirectResponse:
        """Persist expert review and enqueue targeted repair work when needed."""

        redirect = f"/sessions/{session_id}/agent-outputs"
        allowed_statuses = {"approved", "needs_revision", "rejected"}
        if status not in allowed_statuses:
            return RedirectResponse(
                f"{redirect}?error={_url_quote('审核状态无效')}",
                status_code=303,
            )
        if not reviewer.strip():
            return RedirectResponse(
                f"{redirect}?error={_url_quote('请填写审核人')}",
                status_code=303,
            )

        conn = await db_mod.connect(cfg)
        try:
            session = await sess_repo.fetch(conn, session_id)
            if session is None:
                raise HTTPException(status_code=404, detail="session not found")
            normalized_output_key = output_key.strip().replace("\\", "/")
            normalized_output_path = output_path.strip().replace("\\", "/")
            review = AgentOutputReview(
                id=ids.agent_output_review_id(),
                session_id=session_id,
                created_at=datetime.now(UTC),
                agent=agent,
                output_key=normalized_output_key,
                output_path=normalized_output_path or None,
                target_id=target_id.strip() or None,
                status=status,
                reviewer=reviewer.strip(),
                note=note.strip(),
            )
            await output_reviews_repo.insert(conn, review)

            if status != "approved" or note.strip():
                feedback_kind = "rejection" if status == "rejected" else "directive"
                feedback_text = note.strip() or {
                    "needs_revision": "专家要求修改该成果后再进入后续流程。",
                    "rejected": "专家不通过该成果，不得直接作为后续路线依据。",
                }.get(status, "专家已通过该成果。")
                await fb_repo.insert(
                    conn,
                    SystemFeedback(
                        id=ids.feedback_id(),
                        session_id=session_id,
                        created_at=datetime.now(UTC),
                        source="human",
                        kind=feedback_kind,
                        target_id=review.target_id,
                        text=feedback_text,
                        artifact_path=review.output_path,
                        active=True,
                    ),
                )

            if status in {"needs_revision", "rejected"} and review.target_id:
                await _enqueue_mentor_followup(cfg, conn, session, review)
            await GLOBAL_BUS.publish(
                session_id,
                "agent_output_reviewed",
                {
                    "review_id": review.id,
                    "agent": review.agent,
                    "output_key": review.output_key,
                    "status": review.status,
                    "target_id": review.target_id,
                },
            )
            return RedirectResponse(f"{redirect}?saved=1", status_code=303)
        finally:
            await conn.close()

    @app.get("/api/sessions/{session_id}/agent-outputs")
    async def api_session_agent_outputs(session_id: str) -> JSONResponse:
        conn = await db_mod.connect(cfg)
        try:
            session = await sess_repo.fetch(conn, session_id)
            if session is None:
                raise HTTPException(status_code=404, detail="session not found")
            hypotheses = await hyp_repo.list_for_session(conn, session_id)
            decisions = _latest_iteration_decisions_for_session(cfg, session_id)
            pairwise_summary = await _pairwise_calibration_summary(conn, session_id)
            outputs = await _six_agent_output_summary(
                cfg,
                conn,
                session,
                hypotheses=hypotheses,
                decisions=decisions,
                pairwise_summary=pairwise_summary,
            )
            _decorate_agent_output_reviews(
                outputs,
                await output_reviews_repo.latest_for_session(conn, session_id),
            )
            return JSONResponse(
                jsonable_encoder(
                    {
                        "session": session,
                        "outputs": outputs,
                        "lineage": _agent_output_lineage(outputs),
                    }
                )
            )
        finally:
            await conn.close()

    @app.get("/sessions/{session_id}/agent-outputs", response_class=HTMLResponse)
    async def session_agent_outputs(request: Request, session_id: str) -> HTMLResponse:
        frontend_index = FRONTEND_DIST / "index.html"
        if frontend_index.is_file() and "text/html" in request.headers.get("accept", ""):
            return FileResponse(frontend_index)
        conn = await db_mod.connect(cfg)
        try:
            session = await sess_repo.fetch(conn, session_id)
            if session is None:
                raise HTTPException(status_code=404, detail="session not found")
            hypotheses = await hyp_repo.list_for_session(conn, session_id)
            decisions = _latest_iteration_decisions_for_session(cfg, session_id)
            pairwise_summary = await _pairwise_calibration_summary(conn, session_id)
            outputs = await _six_agent_output_summary(
                cfg,
                conn,
                session,
                hypotheses=hypotheses,
                decisions=decisions,
                pairwise_summary=pairwise_summary,
            )
            _decorate_agent_output_reviews(
                outputs,
                await output_reviews_repo.latest_for_session(conn, session_id),
            )
            all_outputs = outputs
            selected_agent = request.query_params.get("agent", "").strip()
            if selected_agent and any(
                output.get("name") == selected_agent for output in all_outputs
            ):
                outputs = [
                    output for output in all_outputs if output.get("name") == selected_agent
                ]
            return TEMPLATES.TemplateResponse(
                request,
                "agent_outputs.html",
                {
                    "session": session,
                    "six_agent_outputs": outputs,
                    "lineage": _agent_output_lineage(all_outputs),
                    "selected_agent": selected_agent,
                },
            )
        finally:
            await conn.close()

    @app.get("/sessions/{session_id}/artifacts/{artifact_path:path}", response_class=HTMLResponse)
    async def session_artifact_detail(request: Request, session_id: str, artifact_path: str) -> HTMLResponse:
        """Render one session-owned JSON or Markdown result artifact."""

        # Evidence interpretation is a Vue page.  Keep the legacy server-rendered
        # artifact view available for non-browser callers, but let normal browser
        # navigation reach the SPA route so the evidence package can be presented
        # with its dedicated interpretation UI.
        frontend_index = FRONTEND_DIST / "index.html"
        if frontend_index.is_file() and "text/html" in request.headers.get("accept", ""):
            return FileResponse(frontend_index)

        session = await _fetch_session_for_web(cfg, session_id)
        if session is None:
            raise HTTPException(status_code=404, detail="session not found")
        base = (cfg.data_dir / "artifacts" / session_id).resolve()
        try:
            path = (cfg.data_dir / artifact_path).resolve()
            path.relative_to(base)
        except (OSError, ValueError):
            raise HTTPException(status_code=404, detail="artifact not found") from None
        if not path.is_file():
            raise HTTPException(status_code=404, detail="artifact not found")
        try:
            raw = path.read_text(encoding="utf-8")
        except (OSError, UnicodeDecodeError):
            raise HTTPException(status_code=415, detail="artifact format is not supported") from None
        parsed_payload: Any = None
        if path.suffix.lower() == ".json":
            try:
                parsed_payload = json.loads(raw)
                content = json.dumps(parsed_payload, ensure_ascii=False, indent=2)
                content_kind = "json"
            except json.JSONDecodeError:
                content = raw
                content_kind = "text"
        else:
            content = render_markdown(raw) if path.suffix.lower() in {".md", ".markdown"} else raw
            content_kind = "markdown" if path.suffix.lower() in {".md", ".markdown"} else "text"
        normalized_artifact_path = artifact_path.replace("\\", "/")
        evidence_view = (
            _build_evidence_interpretation(parsed_payload)
            if "/evidence/package_" in normalized_artifact_path
            else None
        )
        risk_view = (
            parsed_payload.get("record")
            if "/reviews/" in normalized_artifact_path and isinstance(parsed_payload, dict)
            else None
        )
        return TEMPLATES.TemplateResponse(
            request,
            "artifact_detail.html",
            {
                "session": session,
                "artifact_path": artifact_path,
                "artifact_name": path.name,
                "content": content,
                "content_kind": content_kind,
                "evidence_view": evidence_view,
                "risk_view": risk_view,
                "validation_view": (
                    _build_validation_interpretation(parsed_payload)
                    if "/validation/plan_" in artifact_path.replace("\\", "/")
                    else None
                ),
            },
        )

    @app.get("/api/sessions/{session_id}/artifacts/{artifact_path:path}")
    async def session_artifact_detail_api(session_id: str, artifact_path: str) -> JSONResponse:
        """Return the durable evidence artifact view model for the Vue page."""

        session = await _fetch_session_for_web(cfg, session_id)
        if session is None:
            raise HTTPException(status_code=404, detail="session not found")
        base = (cfg.data_dir / "artifacts" / session_id).resolve()
        try:
            path = (cfg.data_dir / artifact_path).resolve()
            path.relative_to(base)
        except (OSError, ValueError):
            raise HTTPException(status_code=404, detail="artifact not found") from None
        if not path.is_file():
            raise HTTPException(status_code=404, detail="artifact not found")
        try:
            raw = path.read_text(encoding="utf-8")
        except (OSError, UnicodeDecodeError):
            raise HTTPException(status_code=415, detail="artifact format is not supported") from None

        parsed_payload: Any = None
        if path.suffix.lower() == ".json":
            try:
                parsed_payload = json.loads(raw)
                content = json.dumps(parsed_payload, ensure_ascii=False, indent=2)
                content_kind = "json"
            except json.JSONDecodeError:
                content = raw
                content_kind = "text"
        else:
            content = render_markdown(raw) if path.suffix.lower() in {".md", ".markdown"} else raw
            content_kind = "markdown" if path.suffix.lower() in {".md", ".markdown"} else "text"
        evidence_view = (
            _build_evidence_interpretation(parsed_payload)
            if "/evidence/package_" in artifact_path.replace("\\", "/")
            else None
        )
        return JSONResponse(
            jsonable_encoder(
                {
                    "session_id": session_id,
                    "artifact_path": artifact_path,
                    "artifact_name": path.name,
                    "content": content,
                    "content_kind": content_kind,
                    "evidence_view": evidence_view,
                }
            )
        )

    @app.get("/api/sessions/{session_id}/route-revision-graph")
    async def route_revision_graph_api(
        request: Request,
        session_id: str,
    ) -> JSONResponse:
        """Return route evolution data for the Vue route workspace."""

        conn = await db_mod.connect(cfg)
        try:
            session = await sess_repo.fetch(conn, session_id)
            if session is None:
                raise HTTPException(status_code=404, detail="session not found")
            hyps = await hyp_repo.list_for_session(conn, session_id)
            decisions = _latest_iteration_decisions_for_session(cfg, session_id)
            focus_id = request.query_params.get("focus_id") or None
            graph_view = _load_route_revision_graph_view(hyps, decisions, focus_id=focus_id)
            return JSONResponse(jsonable_encoder({"session_id": session_id, "graph": graph_view}))
        finally:
            await conn.close()

    @app.get("/sessions/{session_id}/route-revision-graph", response_class=HTMLResponse)
    async def route_revision_graph_page(
        request: Request,
        session_id: str,
    ) -> HTMLResponse:
        if (FRONTEND_DIST / "index.html").is_file() and "text/html" in request.headers.get("accept", ""):
            return FileResponse(FRONTEND_DIST / "index.html")
        conn = await db_mod.connect(cfg)
        try:
            session = await sess_repo.fetch(conn, session_id)
            if session is None:
                raise HTTPException(status_code=404, detail="session not found")
            hyps = await hyp_repo.list_for_session(conn, session_id)
            decisions = _latest_iteration_decisions_for_session(cfg, session_id)
            graph_view = _load_route_revision_graph_view(hyps, decisions)
            return TEMPLATES.TemplateResponse(
                request,
                "route_revision_graph.html",
                {
                    "session": session,
                    "h": None,
                    "graph": graph_view,
                },
            )
        finally:
            await conn.close()

    @app.get("/sessions/{session_id}/evidence-graph", response_class=HTMLResponse)
    async def evidence_graph_page(request: Request, session_id: str) -> HTMLResponse:
        if (FRONTEND_DIST / "index.html").is_file():
            return FileResponse(FRONTEND_DIST / "index.html")
        conn = await db_mod.connect(cfg)
        try:
            session = await sess_repo.fetch(conn, session_id)
            if session is None:
                raise HTTPException(status_code=404, detail="session not found")
            graph_view = _load_evidence_graph_view(cfg, session_id)
            return TEMPLATES.TemplateResponse(
                request,
                "evidence_graph.html",
                {
                    "session": session,
                    "graph": graph_view,
                },
            )
        finally:
            await conn.close()

    @app.get("/sessions/{session_id}/hypotheses/{hid}/route-revision-graph", response_class=HTMLResponse)
    async def route_revision_graph_focus_page(
        request: Request,
        session_id: str,
        hid: str,
    ) -> HTMLResponse:
        if (FRONTEND_DIST / "index.html").is_file() and "text/html" in request.headers.get("accept", ""):
            return FileResponse(FRONTEND_DIST / "index.html")
        conn = await db_mod.connect(cfg)
        try:
            session = await sess_repo.fetch(conn, session_id)
            h = await hyp_repo.fetch(conn, hid)
            if session is None or h is None:
                raise HTTPException(status_code=404, detail="not found")
            hyps = await hyp_repo.list_for_session(conn, session_id)
            decisions = _latest_iteration_decisions_for_session(cfg, session_id)
            graph_view = _load_route_revision_graph_view(
                hyps,
                decisions,
                focus_id=hid,
            )
            return TEMPLATES.TemplateResponse(
                request,
                "route_revision_graph.html",
                {
                    "session": session,
                    "h": h,
                    "graph": graph_view,
                },
            )
        finally:
            await conn.close()

    @app.get("/sessions/{session_id}/hypotheses/{hid}/evidence-subgraph", response_class=HTMLResponse)
    async def hypothesis_evidence_subgraph_page(
        request: Request,
        session_id: str,
        hid: str,
    ) -> HTMLResponse:
        if (FRONTEND_DIST / "index.html").is_file():
            return FileResponse(FRONTEND_DIST / "index.html")
        conn = await db_mod.connect(cfg)
        try:
            session = await sess_repo.fetch(conn, session_id)
            h = await hyp_repo.fetch(conn, hid)
            if session is None or h is None:
                raise HTTPException(status_code=404, detail="not found")
            graph_view = _load_hypothesis_evidence_subgraph_view(cfg, session_id, hid)
            hyps = await hyp_repo.list_for_session(conn, session_id)
            decisions = _latest_iteration_decisions_for_session(cfg, session_id)
            graph_view["closed_loop"] = _hypothesis_closed_loop_context(
                hyps,
                decisions,
                hid,
                evidence_subgraph=graph_view,
            )
            return TEMPLATES.TemplateResponse(
                request,
                "evidence_graph.html",
                {
                    "session": session,
                    "h": h,
                    "graph": graph_view,
                },
            )
        finally:
            await conn.close()

    @app.get("/sessions/{session_id}/hypotheses/{hid}", response_class=HTMLResponse)
    async def hypothesis_detail(
        request: Request,
        session_id: str,
        hid: str,
        lang: str = "zh",
    ) -> HTMLResponse:
        if (FRONTEND_DIST / "index.html").exists() and "text/html" in request.headers.get("accept", ""):
            return FileResponse(FRONTEND_DIST / "index.html")
        conn = await db_mod.connect(cfg)
        try:
            h = await hyp_repo.fetch(conn, hid)
            session = await sess_repo.fetch(conn, session_id)
            if h is None or session is None:
                raise HTTPException(status_code=404, detail="not found")
            reviews = await rev_repo.list_for_hypothesis(conn, hid)
            language = "en" if lang.lower() == "en" else "zh"
            iteration_decisions = _localized_iteration_decisions(
                _load_iteration_decisions(cfg, session_id, hid),
                language=language,
            )
            evidence_subgraph = _load_hypothesis_evidence_subgraph_view(cfg, session_id, hid)
            all_hyps = await hyp_repo.list_for_session(conn, session_id)
            latest_decisions = _latest_iteration_decisions_for_session(cfg, session_id)
            route_revision_graph = _load_route_revision_graph_view(
                all_hyps,
                latest_decisions,
                focus_id=hid,
            )
            closed_loop = _hypothesis_closed_loop_context(
                all_hyps,
                latest_decisions,
                hid,
                evidence_subgraph=evidence_subgraph,
            )
            route_view = await _load_breeding_route_view(
                cfg,
                h,
                latest_decisions.get(hid) or {},
                language=language,
            )
            full_text = _hypothesis_text_for_language(h.full_text or "", lang)
            display_h = h.model_copy(
                update={"state": hypothesis_lifecycle_label(h.state)}
            )
            return TEMPLATES.TemplateResponse(
                request,
                "hypothesis_detail.html",
                {
                    "session": session,
                    "h": display_h,
                    "pairwise_calibration_score": _calibration_score_to_ui_score(
                        h.calibration_score
                    ),
                    "display_title": _markdown_title(full_text) or h.title or h.id,
                    "reviews": reviews,
                    "review_views": _review_view_models(reviews),
                    "iteration_decisions": iteration_decisions,
                    "evidence_subgraph": evidence_subgraph,
                    "route_revision_graph": route_revision_graph,
                    "closed_loop": closed_loop,
                    "route_view": route_view,
                    "language": language,
                    "has_english_hypothesis": _extract_marker_block(h.full_text or "", "HYPOTHESIS_EN") is not None,
                    "has_chinese_hypothesis": _extract_marker_block(h.full_text or "", "HYPOTHESIS_ZH") is not None,
                    "full_text_html": render_markdown(full_text),
                },
            )
        finally:
            await conn.close()

    @app.get("/sessions/{session_id}/overview", response_class=HTMLResponse)
    async def session_overview(
        request: Request,
        session_id: str,
        lang: str = "zh",
    ) -> HTMLResponse:
        if (FRONTEND_DIST / "index.html").is_file():
            return FileResponse(FRONTEND_DIST / "index.html")
        conn = await db_mod.connect(cfg)
        try:
            session = await sess_repo.fetch(conn, session_id)
            if session is None or not session.final_overview:
                raise HTTPException(
                    status_code=404, detail="no final overview yet for this session"
                )
            # `final_overview` is written by the supervisor under
            # `data_dir/artifacts/...` but is stored as a string in the DB.
            # Resolve and confirm the path is still inside `data_dir` so a
            # tampered row can't read arbitrary files.
            base = cfg.data_dir.resolve()
            overview_rel = session.final_overview
            requested_lang = "en" if lang.lower() == "en" else "zh"
            english_rel = str(Path(session.final_overview).with_name("overview_en.md"))
            chinese_rel = str(Path(session.final_overview).with_name("overview_zh.md"))
            has_english = (cfg.data_dir / english_rel).is_file()
            has_chinese = (cfg.data_dir / chinese_rel).is_file()
            actual_lang = requested_lang
            if lang.lower() == "en":
                if has_english:
                    overview_rel = english_rel
                else:
                    actual_lang = "zh" if has_chinese else "fallback"
            elif lang.lower() == "zh":
                if has_chinese:
                    overview_rel = chinese_rel
                else:
                    actual_lang = "fallback"
            try:
                path = (cfg.data_dir / overview_rel).resolve()
                path.relative_to(base)
            except (ValueError, OSError) as e:
                log.error("overview_path_escape", session=session_id, err=str(e))
                raise HTTPException(status_code=404, detail="overview unavailable") from e
            if not path.is_file():
                raise HTTPException(status_code=404, detail="overview missing on disk")
            overview_md = path.read_text(encoding="utf-8")
            if requested_lang == "zh" and not has_chinese:
                overview_md = _localize_legacy_chinese_overview(overview_md)
            linked_overview_md = _link_overview_references(overview_md, session.id)
            acceptance = _load_session_acceptance(cfg, session_id)
            knowledge_snapshot = _session_knowledge_snapshot(session)
            return TEMPLATES.TemplateResponse(
                request,
                "overview.html",
                {
                    "session": session,
                    "overview_html": render_markdown(linked_overview_md),
                    "overview_md": overview_md,
                    "language": actual_lang,
                    "requested_language": requested_lang,
                    "has_english_overview": has_english,
                    "has_chinese_overview": has_chinese,
                    "acceptance": acceptance,
                    "knowledge_snapshot": knowledge_snapshot,
                },
            )
        finally:
            await conn.close()

    # ----------------------------- API + SSE ----------------------------- #

    @app.get("/api/sessions")
    async def api_sessions() -> JSONResponse:
        return JSONResponse(await _list_sessions(cfg))

    @app.get("/api/session-form-config")
    async def api_session_form_config() -> JSONResponse:
        return JSONResponse(
            {
                "default_budget": cfg.run.budget_usd,
                "wall_clock_seconds": cfg.run.wall_clock_seconds,
            }
        )

    @app.delete("/api/sessions/{session_id}")
    async def api_delete_session(session_id: str) -> JSONResponse:
        conn = await db_mod.connect(cfg)
        try:
            session = await sess_repo.fetch(conn, session_id)
            if session is None:
                raise HTTPException(status_code=404, detail="session not found")
            if session.status in {"running", "paused"}:
                return JSONResponse(
                    {
                        "ok": False,
                        "error": "运行中或暂停中的 Session 不能直接删除\uFF0C请先终止。",
                    },
                    status_code=409,
                )
            deleted = await sess_repo.delete_cascade(conn, session_id)
            if deleted:
                _remove_session_files(cfg, session_id)
            return JSONResponse({"ok": deleted, "session_id": session_id})
        finally:
            await conn.close()

    @app.get("/api/sessions/{session_id}/hypotheses/{hid}/detail")
    async def hypothesis_detail_api(
        session_id: str,
        hid: str,
        lang: str = "zh",
    ) -> dict[str, Any]:
        """Return the complete hypothesis route view for the Vue detail page."""
        conn = await db_mod.connect(cfg)
        try:
            h = await hyp_repo.fetch(conn, hid)
            session = await sess_repo.fetch(conn, session_id)
            if h is None or session is None or str(h.session_id) != str(session_id):
                raise HTTPException(status_code=404, detail="not found")
            reviews = await rev_repo.list_for_hypothesis(conn, hid)
            language = "en" if lang.lower() == "en" else "zh"
            iteration_decisions = _localized_iteration_decisions(
                _load_iteration_decisions(cfg, session_id, hid),
                language=language,
            )
            evidence_subgraph = _load_hypothesis_evidence_subgraph_view(cfg, session_id, hid)
            all_hyps = await hyp_repo.list_for_session(conn, session_id)
            latest_decisions = _latest_iteration_decisions_for_session(cfg, session_id)
            route_revision_graph = _load_route_revision_graph_view(
                all_hyps,
                latest_decisions,
                focus_id=hid,
            )
            closed_loop = _hypothesis_closed_loop_context(
                all_hyps,
                latest_decisions,
                hid,
                evidence_subgraph=evidence_subgraph,
            )
            route_view = await _load_breeding_route_view(
                cfg,
                h,
                latest_decisions.get(hid) or {},
                language=language,
            )
            full_text = _hypothesis_text_for_language(h.full_text or "", language)
            display_h = h.model_copy(update={"state": hypothesis_lifecycle_label(h.state)})
            payload = {
                "session": session,
                "hypothesis": display_h,
                "pairwise_calibration_score": _calibration_score_to_ui_score(h.calibration_score),
                "display_title": _markdown_title(full_text) or h.title or h.id,
                "reviews": reviews,
                "review_views": _review_view_models(reviews),
                "iteration_decisions": iteration_decisions,
                "evidence_subgraph": evidence_subgraph,
                "route_revision_graph": route_revision_graph,
                "closed_loop": closed_loop,
                "route_view": route_view,
                "language": language,
                "has_english_hypothesis": _extract_marker_block(h.full_text or "", "HYPOTHESIS_EN") is not None,
                "has_chinese_hypothesis": _extract_marker_block(h.full_text or "", "HYPOTHESIS_ZH") is not None,
                "full_text": full_text,
                "full_text_html": render_markdown(full_text),
            }
            return jsonable_encoder(payload)
        finally:
            await conn.close()

    @app.get("/api/sessions/{session_id}/metrics")
    async def api_metrics(session_id: str) -> JSONResponse:
        from ..obs.metrics import session_metrics_cached, to_dict

        conn = await db_mod.connect(cfg)
        try:
            m = await session_metrics_cached(conn, session_id)
            return JSONResponse(to_dict(m))
        finally:
            await conn.close()

    @app.get("/api/sessions/{session_id}")
    async def api_session(session_id: str) -> JSONResponse:
        conn = await db_mod.connect(cfg)
        try:
            s = await sess_repo.fetch(conn, session_id)
            if s is None:
                raise HTTPException(status_code=404)
            return JSONResponse(s.model_dump(mode="json"))
        finally:
            await conn.close()

    @app.get("/api/sessions/{session_id}/events")
    async def api_events(session_id: str) -> EventSourceResponse:
        async def _stream() -> AsyncIterator[dict[str, Any]]:
            # Replay last 25 events from DB so refreshes don't go blank.
            conn = await db_mod.connect(cfg)
            try:
                history = await events_repo.recent(conn, session_id, limit=25)
            finally:
                await conn.close()
            for ev in reversed(history):
                payload = decorate_agent_payload(ev["payload"])
                yield {
                    "event": ev["event"],
                    "data": json.dumps(
                        {"payload": payload, "ts": ev["ts"]},
                        ensure_ascii=False,
                    ),
                }
            async with contextlib.aclosing(GLOBAL_BUS.subscribe(session_id)) as gen:
                async for ev in gen:
                    ev.payload = decorate_agent_payload(ev.payload) or {}
                    yield {
                        "event": ev.name,
                        "data": ev.to_json(),
                    }

        return EventSourceResponse(_stream())

    @app.post("/api/sessions/{session_id}/pause")
    async def api_pause(session_id: str) -> JSONResponse:
        conn = await db_mod.connect(cfg)
        try:
            await sess_repo.set_status(conn, session_id, "paused")
            await GLOBAL_BUS.publish(session_id, "session_paused", {})
            return JSONResponse({"ok": True})
        finally:
            await conn.close()

    @app.post("/api/sessions/{session_id}/resume")
    async def api_resume(session_id: str) -> JSONResponse:
        conn = await db_mod.connect(cfg)
        try:
            await sess_repo.set_status(conn, session_id, "running")
            await GLOBAL_BUS.publish(session_id, "session_resumed", {})
            return JSONResponse({"ok": True})
        finally:
            await conn.close()

    @app.post("/api/sessions/{session_id}/abort")
    async def api_abort(session_id: str) -> JSONResponse:
        conn = await db_mod.connect(cfg)
        try:
            await sess_repo.set_status(conn, session_id, "aborted")
            await GLOBAL_BUS.publish(session_id, "session_aborted", {})
            return JSONResponse({"ok": True})
        finally:
            await conn.close()

    @app.post("/api/sessions/{session_id}/feedback")
    async def api_feedback(
        session_id: str,
        text: str = Form(...),
        kind: str = Form("directive"),
        target_id: str = Form(""),
    ) -> JSONResponse:
        conn = await db_mod.connect(cfg)
        try:
            fb = SystemFeedback(
                id=ids.feedback_id(), session_id=session_id,
                created_at=datetime.now(UTC),
                source="human", kind=kind,
                target_id=target_id or None, text=text, active=True,
            )
            await fb_repo.insert(conn, fb)
            if kind == "pin" and target_id:
                await hyp_repo.set_state(conn, target_id, "pinned")
            elif kind == "rejection" and target_id:
                await hyp_repo.set_state(conn, target_id, "rejected")
            await GLOBAL_BUS.publish(session_id, "human_feedback", {
                "kind": kind, "target_id": target_id or None, "text": text[:200],
            })
            return JSONResponse({"ok": True, "feedback_id": fb.id})
        finally:
            await conn.close()

    @app.get("/healthz")
    async def health() -> JSONResponse:
        return JSONResponse({"ok": True})

    # quiet uvicorn access spam during streaming
    stdlib_logging.getLogger("uvicorn.access").setLevel(stdlib_logging.WARNING)
    return app


# ----------------------------- helpers ----------------------------- #


def _knowledge_batch_zip_response(*, demo: bool) -> Response:
    """Build either a blank schema template or a filled demo batch ZIP."""

    root = "foxtail_millet_drought_demo_2026" if demo else "knowledge_batch_template"
    if demo:
        manifest = {
            "batch_id": "foxtail_millet_drought_demo_2026",
            "schema_version": "1.0",
            "crop_scope": ["foxtail_millet"],
            "submitted_by": "AI Breeding Scientist demo",
            "submitted_at": "2026-08-07",
            "notes": "演示数据，仅用于理解知识库接入流程，不作为真实育种结论。",
            "sources": {
                "germplasm_csv": "sources/germplasm_resources.csv",
                "crop_kg_packs": [
                    {"crop_key": "foxtail_millet", "path": "sources/kg/foxtail_millet.json"}
                ],
                "rag_sources_dir": "sources/rag",
                "rag_index_json": "outputs/evidence_index.json",
                "marker_qtl_csv": "sources/marker_qtl_library.csv",
                "phenotype_protocol_csv": "sources/phenotype_protocol_library.csv",
                "field_trial_csv": "sources/field_trial_records.csv",
            },
        }
    else:
        manifest = {
            "batch_id": "replace-with-batch-id",
            "schema_version": "1.0",
            "crop_scope": ["replace-with-crop-key"],
            "submitted_by": "",
            "submitted_at": "YYYY-MM-DD",
            "notes": "Fill the real records, then upload this ZIP for automated validation.",
            "sources": {
                "germplasm_csv": "sources/germplasm_resources.csv",
                "crop_kg_packs": [
                    {"crop_key": "replace-with-crop-key", "path": "sources/kg/crop_kg.json"}
                ],
                "rag_sources_dir": "sources/rag",
                "rag_index_json": "outputs/evidence_index.json",
                "marker_qtl_csv": "sources/marker_qtl_library.csv",
                "phenotype_protocol_csv": "sources/phenotype_protocol_library.csv",
                "field_trial_csv": "sources/field_trial_records.csv",
            },
        }

    stream = BytesIO()
    with zipfile.ZipFile(stream, "w", zipfile.ZIP_DEFLATED) as archive:
        archive.writestr(
            f"{root}/manifest.json",
            json.dumps(manifest, ensure_ascii=False, indent=2),
        )
        templates_dir = HERE.parents[1] / "docs" / "templates"
        if demo:
            csv_files = {
                "germplasm_resources.csv": templates_dir / "germplasm_resources_public_seed.csv",
                "marker_qtl_library.csv": templates_dir / "marker_qtl_library_seed.csv",
                "phenotype_protocol_library.csv": templates_dir / "phenotype_protocol_library_seed.csv",
                "field_trial_records.csv": templates_dir / "field_trial_records_seed.csv",
            }
            kg_path = templates_dir / "foxtail_millet_kg_seed.json"
            rag_files = (
                "foxtail_millet_drought_testing_note.md",
                "dense_lodging_90day_validation_note.md",
                "263a_germplasm_material_note.md",
                "seita5g404900_caps_validation_preflight_2026-07.md",
            )
            for filename, source in csv_files.items():
                archive.write(source, f"{root}/sources/{filename}")
            archive.write(kg_path, f"{root}/sources/kg/foxtail_millet.json")
            rag_dir = HERE.parents[1] / "docs" / "rag_sources"
            for filename in rag_files:
                archive.write(rag_dir / filename, f"{root}/sources/rag/{filename}")
        else:
            csv_templates = {
                "germplasm_resources.csv": GERMPLASM_COLUMNS,
                "marker_qtl_library.csv": MARKER_QTL_COLUMNS,
                "phenotype_protocol_library.csv": PHENOTYPE_PROTOCOL_COLUMNS,
                "field_trial_records.csv": FIELD_TRIAL_COLUMNS,
            }
            for filename, columns in csv_templates.items():
                text = StringIO()
                csv.writer(text, lineterminator="\n").writerow(columns)
                archive.writestr(f"{root}/sources/{filename}", text.getvalue())
            archive.writestr(
                f"{root}/sources/kg/crop_kg.json",
                json.dumps(
                    {
                        "metadata": {
                            "crop_key": "replace-with-crop-key",
                            "crop_scope": "replace-with-crop-key",
                        },
                        "nodes": [],
                        "edges": [],
                    },
                    ensure_ascii=False,
                    indent=2,
                ),
            )
            archive.writestr(
                f"{root}/sources/rag/README.md",
                "# RAG 资料\n\n请将整理后的 .md 或 .txt 证据卡放入本目录。\n",
            )
    filename = "foxtail_millet_drought_demo_2026.zip" if demo else "knowledge_batch_template.zip"
    return Response(
        content=stream.getvalue(),
        media_type="application/zip",
        headers={"Content-Disposition": f'attachment; filename="{filename}"'},
    )


async def _list_sessions(cfg: Config) -> list[dict[str, Any]]:
    conn = await db_mod.connect(cfg)
    try:
        async with conn.execute(
            """SELECT id, status, research_goal, created_at, updated_at,
                      budget_usd, budget_used_usd,
                      (SELECT COUNT(*) FROM hypotheses WHERE session_id = s.id) AS n_hyps
                 FROM sessions s
                 ORDER BY updated_at DESC LIMIT 50""",
        ) as cur:
            rows = await cur.fetchall()
    finally:
        await conn.close()
    return [dict(r) for r in rows]


def _previous_batch_record(
    history: list[dict[str, Any]],
    record: dict[str, Any],
) -> dict[str, Any] | None:
    current_time = str(record.get("imported_at") or "")
    candidates = [
        row for row in history
        if row is not record and str(row.get("imported_at") or "") < current_time
    ]
    return max(candidates, key=lambda row: str(row.get("imported_at") or ""), default=None)


def _batch_stats_diff(
    current: Any,
    previous: Any,
) -> list[dict[str, Any]]:
    current = current if isinstance(current, dict) else {}
    previous = previous if isinstance(previous, dict) else {}
    keys = sorted({*current, *previous})
    rows: list[dict[str, Any]] = []
    for key in keys:
        current_value = current.get(key)
        previous_value = previous.get(key)
        if isinstance(current_value, dict) or isinstance(previous_value, dict):
            nested_current = current_value if isinstance(current_value, dict) else {}
            nested_previous = previous_value if isinstance(previous_value, dict) else {}
            for nested_key in sorted({*nested_current, *nested_previous}):
                value = nested_current.get(nested_key)
                old_value = nested_previous.get(nested_key)
                if isinstance(value, int | float) or isinstance(old_value, int | float):
                    rows.append(
                        {
                            "key": f"{key}.{nested_key}",
                            "current": value if isinstance(value, int | float) else "-",
                            "previous": old_value if isinstance(old_value, int | float) else "-",
                            "delta": (value or 0) - (old_value or 0),
                        }
                    )
            continue
        if isinstance(current_value, int | float) or isinstance(previous_value, int | float):
            current_number = current_value if isinstance(current_value, int | float) else 0
            previous_number = previous_value if isinstance(previous_value, int | float) else 0
            rows.append(
                {
                    "key": key,
                    "current": current_value if current_value is not None else "-",
                    "previous": previous_value if previous_value is not None else "-",
                    "delta": current_number - previous_number,
                }
            )
    return rows


def _batch_file_diff(
    record: dict[str, Any],
    previous: dict[str, Any] | None,
) -> dict[str, Any] | None:
    current_archive = record.get("archive_path")
    previous_archive = previous.get("archive_path") if previous else None
    if not current_archive or not previous_archive:
        return None
    return compare_version_files(Path(current_archive), Path(previous_archive))


async def _six_agent_task_summary(conn: Any, session: Any) -> list[dict[str, Any]]:
    rows_by_agent: dict[str, dict[str, Any]] = {
        name: {
            "name": name,
            "total": 0,
            "pending": 0,
            "active": 0,
            "done": 0,
            "failed": 0,
            "cancelled": 0,
            "steps": [],
        }
        for name in SIX_AGENT_ORDER
    }
    seen_steps: dict[str, set[str]] = {name: set() for name in SIX_AGENT_ORDER}

    # Goal parsing happens before the durable task queue is filled.
    goal_row = rows_by_agent["Goal Interpreter"]
    goal_row["total"] = 1
    goal_row["done"] = 1 if getattr(session, "research_plan", None) else 0
    seen_steps["Goal Interpreter"].add("Goal parsing")

    async with conn.execute(
        """SELECT agent, action, status, COUNT(*) AS n
             FROM tasks
            WHERE session_id=?
            GROUP BY agent, action, status""",
        (session.id,),
    ) as cur:
        rows = await cur.fetchall()

    for row in rows:
        internal_agent = row["agent"]
        action = row["action"]
        core = core_agent_name(internal_agent) or internal_agent
        summary = rows_by_agent.setdefault(
            core,
            {
                "name": core,
                "total": 0,
                "pending": 0,
                "active": 0,
                "done": 0,
                "failed": 0,
                "cancelled": 0,
                "steps": [],
            },
        )
        n = int(row["n"])
        status = row["status"]
        summary["total"] += n
        if status == "pending":
            summary["pending"] += n
        elif status in {"leased", "in_progress"}:
            summary["active"] += n
        elif status == "done":
            summary["done"] += n
        elif status in {"failed", "dead"}:
            summary["failed"] += n
        elif status == "cancelled":
            summary["cancelled"] += n
        step = agent_step_name(internal_agent, action)
        if step:
            seen_steps.setdefault(core, set()).add(step)

    out = []
    for name in SIX_AGENT_ORDER:
        item = rows_by_agent[name]
        item["steps"] = sorted(seen_steps.get(name, set()))
        out.append(item)
    return out


def _termination_summary(
    *,
    session: Any,
    hypotheses: list[Any],
    decisions: dict[str, dict[str, Any]],
    iteration_audit: dict[str, Any],
    recent_events: list[dict[str, Any]],
) -> dict[str, Any]:
    stop_reason = _latest_stop_reason(recent_events)
    max_hypothesis_count = _positive_int_or_none(
        getattr(session.research_plan, "max_hypothesis_count", None)
    )
    hypothesis_count = len(hypotheses)
    total_decisions = int(iteration_audit.get("total_decisions") or len(decisions))
    keep_ready = _keep_ready_count(decisions)
    action_counts = iteration_audit.get("action_counts") or {}
    pause_reject = int(action_counts.get("pause") or 0) + int(action_counts.get("reject") or 0)

    if not stop_reason and getattr(session, "status", "") != "done":
        return {
            "available": False,
            "stop_reason": None,
            "state": "running",
            "title": "Run in progress",
            "explanation": "The run is still active.",
            "points": [],
        }

    reason_info = _stop_reason_info(stop_reason)
    points = [
        f"Hypotheses generated: {hypothesis_count}"
        + (f" / {max_hypothesis_count}" if max_hypothesis_count is not None else ""),
        f"Iteration decisions: {total_decisions}",
        f"Keep-ready routes: {keep_ready}",
    ]
    if pause_reject:
        points.append(f"Paused/rejected routes: {pause_reject}")
    if stop_reason == "breeding_max_hypotheses_reached":
        points.append("Revise/expand design is capped by max_hypothesis_count.")

    return {
        "available": bool(stop_reason or getattr(session, "status", "") == "done"),
        "stop_reason": stop_reason,
        "state": reason_info["state"],
        "title": reason_info["title"],
        "explanation": reason_info["explanation"],
        "points": points,
    }


def _latest_stop_reason(recent_events: list[dict[str, Any]]) -> str | None:
    for event in recent_events:
        if event.get("event") not in {"session_done", "session_completed"}:
            continue
        payload = event.get("payload")
        if not isinstance(payload, dict):
            continue
        stop_reason = payload.get("stop_reason")
        if isinstance(stop_reason, str) and stop_reason:
            return _normalize_stop_reason(stop_reason)
    return None


def _normalize_stop_reason(stop_reason: str) -> str:
    return stop_reason


def _stop_reason_info(stop_reason: str | None) -> dict[str, str]:
    info = {
        "breeding_success_ready": {
            "state": "success",
            "title": "Breeding success ready",
            "explanation": "The system found enough high-scoring keep-ready breeding routes for final review.",
        },
        "breeding_evidence_blocked": {
            "state": "blocked",
            "title": "Evidence blocked",
            "explanation": "Most reviewed routes were paused or rejected because evidence gaps or conflicts remain unresolved.",
        },
        "breeding_no_composite_gain": {
            "state": "blocked",
            "title": "No composite gain",
            "explanation": "Recent iterations did not produce a sufficiently strong composite-ranked route.",
        },
        "breeding_max_hypotheses_reached": {
            "state": "capped",
            "title": "Maximum hypothesis pool reached",
            "explanation": "The user-defined hypothesis cap has been reached before enough keep-ready routes were available.",
        },
        "pairwise_calibration_stable": {
            "state": "success",
            "title": "Pairwise calibration stable",
            "explanation": "The prioritized breeding routes stayed stable within the configured pairwise calibration window.",
        },
        "budget": {
            "state": "blocked",
            "title": "Budget exhausted",
            "explanation": "The run stopped after reaching the configured budget.",
        },
        "wall_clock": {
            "state": "blocked",
            "title": "Time limit reached",
            "explanation": "The run stopped after reaching the configured wall-clock limit.",
        },
        "idle": {
            "state": "idle",
            "title": "Queue drained",
            "explanation": "No runnable tasks remained in the queue.",
        },
        "external": {
            "state": "idle",
            "title": "Stopped externally",
            "explanation": "The run was paused or aborted by the user.",
        },
    }
    return info.get(
        stop_reason or "",
        {
            "state": "idle",
            "title": "Run completed",
            "explanation": "The run completed without a detailed stop reason.",
        },
    )


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


async def _recent_pairwise_calibrations(
    conn,
    session_id: str,
    *,
    limit: int,
) -> list[dict[str, Any]]:
    async with conn.execute(
        """SELECT id, hyp_a, hyp_b, mode, winner,
                  calibration_a_after AS calibration_a_raw,
                  calibration_b_after AS calibration_b_raw,
                  created_at
              FROM pairwise_calibration_matches
             WHERE session_id=?
             ORDER BY created_at DESC LIMIT ?""",
        (session_id, limit),
    ) as cur:
        rows = await cur.fetchall()
    out = []
    for row in rows:
        item = dict(row)
        item["has_calibration_scores"] = isinstance(
            item.get("calibration_a_raw"), int | float
        ) and isinstance(item.get("calibration_b_raw"), int | float)
        item["calibration_a_after"] = _calibration_score_to_ui_score(
            item.get("calibration_a_raw")
        )
        item["calibration_b_after"] = _calibration_score_to_ui_score(
            item.get("calibration_b_raw")
        )
        out.append(item)
    return out


async def _six_agent_output_summary(
    cfg: Config,
    conn: Any,
    session: Any,
    *,
    hypotheses: list[Any],
    decisions: dict[str, dict[str, Any]],
    pairwise_summary: dict[str, Any],
) -> list[dict[str, Any]]:
    """Build mentor-facing output summaries from durable scientific artifacts."""

    session_id = str(session.id)
    labels = {
        "Goal Interpreter": "目标解析",
        "Evidence Curator": "证据整理",
        "Breeding Designer": "育种设计",
        "Validation Planner": "验证规划",
        "Risk Reviewer": "风险评审",
        "Iteration Orchestrator": "迭代编排",
    }

    def item(
        title: str,
        summary: str,
        *,
        path: str | None = None,
        link: str | None = None,
        link_label: str = "查看结果",
        details: list[dict[str, str]] | None = None,
        target_id: str | None = None,
    ) -> dict[str, Any]:
        return {
            "title": title,
            "summary": summary,
            "path": path,
            "url": link or (f"/sessions/{session_id}/artifacts/{path}" if path else None),
            "link_label": link_label,
            "details": details or [],
            "target_id": target_id,
        }

    objective = str(getattr(session.research_plan, "objective", "") or session.research_goal)
    plan = session.research_plan
    goal_output = item(
        "结构化育种目标",
        f"作物/目标: {objective}; 初始假设 {plan.initial_hypothesis_count} 条, "
        f"最大假设 {plan.max_hypothesis_count or '未设置'} 条。",
        details=[
            {"label": "目标", "value": objective},
            {"label": "初始假设数", "value": str(plan.initial_hypothesis_count)},
            {"label": "最大假设数", "value": str(plan.max_hypothesis_count or "未设置")},
            {"label": "目标偏好", "value": "; ".join(plan.preferences) or "未设置"},
        ],
    )

    evidence_files = _session_artifact_files(cfg, session_id, "evidence", "package_*.json")
    evidence_outputs = []
    for relative_path in evidence_files[:5]:
        evidence_payload = _read_artifact_json(cfg, relative_path)
        evidence_outputs.append(
            item(
                "证据包",
                "本地种质、知识图谱、RAG 和育种资料已整理为结构化证据包。",
                path=relative_path,
                target_id=(evidence_payload or {}).get("target_hypothesis_id")
                if isinstance(evidence_payload, dict)
                else None,
                link_label="查看证据解读",
                details=_structured_artifact_details(
                    evidence_payload,
                    (
                        ("搜索模式", "mode"),
                        ("知识快照", "knowledge_snapshot_id"),
                        ("知识批次", "knowledge_batch_id"),
                        ("材料命中数", "local_germplasm"),
                        ("知识图谱命中数", "local_crop_kg"),
                        ("RAG 命中数", "local_rag"),
                    ),
                ),
            )
        )
    graph_path = f"artifacts/{session_id}/evidence/breeding_evidence_graph.json"
    if (cfg.data_dir / graph_path).is_file():
        evidence_outputs.insert(
            0,
            item(
                "Breeding Evidence Graph",
                "证据节点、关系和证据缺口的汇总图。",
                path=graph_path,
                link=f"/sessions/{session_id}/evidence-graph",
                link_label="查看图谱",
            ),
        )

    ordered_hypotheses = sorted(
        hypotheses,
        key=lambda hypothesis: getattr(hypothesis, "created_at", None),
        reverse=True,
    )
    design_outputs = []
    for hypothesis in ordered_hypotheses[:5]:
        design_outputs.append(
            item(
                hypothesis.title or hypothesis.id,
                (hypothesis.summary or "育种假设已生成。")[:240],
                path=hypothesis.artifact_path,
                link=f"/sessions/{session_id}/hypotheses/{hypothesis.id}",
                link_label="查看假设",
                target_id=hypothesis.id,
                details=[
                    {"label": "策略", "value": hypothesis.strategy},
                    {"label": "生命周期", "value": hypothesis.state},
                    {"label": "配对校准次数", "value": str(hypothesis.pairwise_calibrations_played)},
                    {
                        "label": "配对分",
                        "value": str(hypothesis.calibration_score or "未形成"),
                    },
                    {
                        "label": "父路线",
                        "value": ", ".join(hypothesis.parent_ids) or "初始路线",
                    },
                ],
            )
        )

    validation_files = _session_artifact_files(cfg, session_id, "validation", "plan_*.json")
    validation_outputs = []
    for relative_path in validation_files[:5]:
        validation_payload = _read_artifact_json(cfg, relative_path)
        validation_hypothesis_id = (
            str(validation_payload.get("hypothesis_id") or "")
            if isinstance(validation_payload, dict)
            else ""
        )
        validation_outputs.append(
            item(
                "验证计划",
                "包含表型、标记/基因型、田间试验和成功判定标准。",
                path=relative_path,
                details=_structured_artifact_details(
                    validation_payload,
                    (
                        ("假设", "hypothesis_title"),
                        ("验证就绪度", "validation_readiness_score"),
                        ("就绪等级", "readiness_level"),
                        ("材料计划", "materials_plan"),
                        ("育种目标", "breeding_goal"),
                    ),
                ),
                target_id=validation_hypothesis_id or None,
            )
        )

    reviews = await rev_repo.list_for_session(conn, session_id)
    risk_files = _session_artifact_files(cfg, session_id, "risk", "review_*.json")
    risk_outputs = [
        item(
            f"{review_verdict_label(review.verdict)} · {review.hypothesis_id}",
            f"评审类型: {review_kind_label(review.kind)}; "
            f"可测试性 {_format_optional_ratio(review.scores.testability)}, "
            f"可行性 {_format_optional_ratio(review.scores.feasibility)}。",
            path=str(review.artifact_path or "").replace("\\", "/"),
            link_label="查看评审",
            target_id=review.hypothesis_id,
            details=[
                {"label": "结论", "value": review_verdict_label(review.verdict)},
                {"label": "新颖性", "value": _format_optional_ratio(review.scores.novelty)},
                {"label": "正确性", "value": _format_optional_ratio(review.scores.correctness)},
                {"label": "可测试性", "value": _format_optional_ratio(review.scores.testability)},
                {"label": "可行性", "value": _format_optional_ratio(review.scores.feasibility)},
            ],
        )
        for review in reviews[:5]
    ]
    if not risk_outputs:
        risk_outputs = [
            item("风险评审", "尚未形成风险评审结果。", path=path)
            for path in risk_files[:5]
        ]

    hypothesis_titles = {hypothesis.id: hypothesis.title or hypothesis.id for hypothesis in hypotheses}
    iteration_outputs = [
        item(
            f"{ACTION_LABELS_ZH.get(str(decision.get('action') or 'pending'), '待处理')} · "
            f"{hypothesis_titles.get(hypothesis_id, hypothesis_id)}",
            str(decision.get("reason_summary") or "迭代决策已形成。"),
            path=str(decision.get("decision_path") or "") or None,
            link=f"/sessions/{session_id}/hypotheses/{hypothesis_id}",
            link_label="查看路线",
            target_id=hypothesis_id,
            details=[
                {"label": "动作", "value": str(decision.get("action") or "pending")},
                {"label": "评审闸门", "value": str(decision.get("review_gate") or "未设置")},
                {"label": "迭代分", "value": str(decision.get("total_score") or "未形成")},
                {
                    "label": "下一步",
                    "value": str(decision.get("new_hypothesis_direction") or "未设置"),
                },
            ],
        )
        for hypothesis_id, decision in sorted(
            decisions.items(),
            key=lambda pair: str(pair[1].get("created_at") or ""),
            reverse=True,
        )[:5]
    ]
    if session.final_overview:
        iteration_outputs.insert(
            0,
            item(
                "最终育种综述",
                "汇总正式路线、证据边界、验证计划、风险和终止判断。",
                path=session.final_overview,
                link=f"/sessions/{session_id}/overview",
                link_label="查看综述",
            ),
        )

    output_map = {
        "Goal Interpreter": (
            "负责把自然语言需求转成结构化育种目标。",
            [goal_output],
            "已完成目标结构化。",
        ),
        "Evidence Curator": (
            "负责把本地知识库、知识图谱、RAG 和资料整理为可追溯证据。",
            evidence_outputs,
            f"已整理 {len(evidence_files)} 个证据包。",
        ),
        "Breeding Designer": (
            "负责生成可比较、可验证、可迭代的育种假设。",
            design_outputs,
            f"已生成 {len(hypotheses)} 条假设。",
        ),
        "Validation Planner": (
            "负责把路线转成材料、表型、标记和田间试验方案。",
            validation_outputs,
            f"已形成 {len(validation_files)} 个验证计划。",
        ),
        "Risk Reviewer": (
            "负责检查证据缺口、反证、风险和路线可推进性。",
            risk_outputs,
            f"已形成 {len(reviews) or len(risk_files)} 个风险评审结果。",
        ),
        "Iteration Orchestrator": (
            "负责配对校准、路线排序、任务回补、迭代和终止判断。",
            iteration_outputs,
            f"已形成 {len(decisions)} 个迭代决策, 配对校准 {pairwise_summary.get('total', 0)} 次。",
        ),
    }
    for agent_name, (_purpose, outputs, _summary) in output_map.items():
        for index, output in enumerate(outputs):
            output["agent"] = agent_name
            output["output_key"] = output.get("path") or (
                f"{agent_name}::{index}::{output.get('title', 'output')}"
            )
    return [
        {
            "name": name,
            "label": labels[name],
            "purpose": purpose,
            "output_count": (
                len(outputs)
                if name != "Breeding Designer"
                else len(hypotheses)
            ),
            "summary": summary,
            "outputs": outputs,
        }
        for name in SIX_AGENT_ORDER
        for purpose, outputs, summary in [output_map[name]]
    ]


def _session_artifact_files(
    cfg: Config,
    session_id: str,
    subdirectory: str,
    pattern: str,
) -> list[str]:
    base = (cfg.data_dir / "artifacts" / session_id).resolve()
    directory = (base / subdirectory).resolve()
    try:
        directory.relative_to(base)
    except ValueError:
        return []
    if not directory.is_dir():
        return []
    files = [path for path in directory.glob(pattern) if path.is_file()]
    files.sort(key=lambda path: path.stat().st_mtime, reverse=True)
    return [path.relative_to(cfg.data_dir).as_posix() for path in files]


async def _fetch_session_for_web(cfg: Config, session_id: str) -> Any | None:
    conn = await db_mod.connect(cfg)
    try:
        return await sess_repo.fetch(conn, session_id)
    finally:
        await conn.close()


def _remove_session_files(cfg: Config, session_id: str) -> None:
    """Remove only session-owned artifacts, vectors, and logs."""

    for root in (
        cfg.data_dir / "artifacts",
        cfg.data_dir / "vectors",
        cfg.data_dir / "logs",
    ):
        base = root.resolve()
        candidate = (root / session_id).resolve()
        try:
            candidate.relative_to(base)
        except ValueError:
            continue
        if candidate.is_dir():
            shutil.rmtree(candidate)


def _format_optional_ratio(value: Any) -> str:
    return f"{float(value):.2f}" if isinstance(value, int | float) else "-"


def _structured_artifact_details(
    payload: Any,
    fields: tuple[tuple[str, str], ...],
) -> list[dict[str, str]]:
    if not isinstance(payload, dict):
        return []
    details: list[dict[str, str]] = []
    for label, key in fields:
        value = payload.get(key)
        if value is None:
            continue
        if isinstance(value, dict):
            if isinstance(value.get("results"), list):
                shown = f"{len(value['results'])} 条命中"
            else:
                shown = ", ".join(str(name) for name in value)[:180]
        elif isinstance(value, list):
            shown = ", ".join(str(entry) for entry in value[:4])
            if len(value) > 4:
                shown += f" 等 {len(value)} 项"
        else:
            shown = str(value)
        details.append({"label": label, "value": shown})
    return details


def _build_validation_interpretation(payload: Any) -> dict[str, Any] | None:
    """Turn a validation-plan JSON artifact into a reader-friendly plan view."""

    if not isinstance(payload, dict):
        return None

    def text(value: Any, fallback: str = "未记录") -> str:
        if value is None or value == "":
            return fallback
        return _route_value_text(value)

    def items(value: Any) -> list[str]:
        if not isinstance(value, list):
            return []
        return [text(item) for item in value if item not in (None, "")]

    readiness = str(payload.get("readiness_level") or "").lower()
    readiness_labels = {
        "ready": "已具备验证条件",
        "conditional": "有条件推进",
        "needs_evidence": "需要补充证据",
        "blocked": "暂不具备推进条件",
    }
    score = payload.get("validation_readiness_score")
    score_text = f"{float(score):.1f}" if isinstance(score, int | float) else "-"

    breeding_goal = payload.get("breeding_goal") or {}
    materials = payload.get("materials_plan") or {}
    genotyping = payload.get("genotyping_plan") or {}
    phenotyping = payload.get("phenotyping_plan") or {}
    field_trial = payload.get("field_trial_design") or {}
    cost = payload.get("cost_cycle_estimate") or {}

    risk_controls = []
    for entry in payload.get("risk_controls") or []:
        if isinstance(entry, dict):
            risk_controls.append(
                {
                    "risk": text(entry.get("risk")),
                    "control": text(entry.get("control")),
                }
            )

    gaps = []
    for entry in payload.get("critical_evidence_gaps") or []:
        if isinstance(entry, dict):
            severity = str(entry.get("severity") or "").lower()
            gaps.append(
                {
                    "type": text(entry.get("type"), "一般证据缺口").replace("_", " "),
                    "severity": "高优先级" if severity == "high" else "需关注",
                    "message": text(entry.get("message") or entry.get("target")),
                }
            )

    return {
        "title": text(payload.get("hypothesis_title"), "当前育种路线验证方案"),
        "research_goal": text(payload.get("research_goal")),
        "readiness_label": readiness_labels.get(readiness, "待专家确认"),
        "readiness_level": readiness,
        "score": score_text,
        "crop": text(breeding_goal.get("crop")),
        "target_trait": text(breeding_goal.get("target_trait")),
        "target_environment": text(breeding_goal.get("target_environment")),
        "materials": {
            "required": items(materials.get("required_materials")),
            "controls": items(materials.get("controls")),
            "availability": text(materials.get("availability_check")),
            "population": text(materials.get("minimum_population")),
        },
        "genotyping": {
            "objective": text(genotyping.get("objective")),
            "targets": items(genotyping.get("targets")),
            "assay": text(genotyping.get("assay")),
            "samples": items(genotyping.get("samples")),
            "go_no_go": text(genotyping.get("go_no_go")),
        },
        "phenotyping": {
            "objective": text(phenotyping.get("objective")),
            "protocol": text(phenotyping.get("protocol")),
            "timepoints": items(phenotyping.get("timepoints")),
            "quality_control": items(phenotyping.get("quality_control")),
        },
        "field_trial": {
            "population": text(field_trial.get("population")),
            "environment": text(field_trial.get("environment")),
            "design": text(field_trial.get("design")),
            "replication": text(field_trial.get("replication")),
            "thresholds": text(field_trial.get("decision_thresholds")),
        },
        "cost": {
            "first_evidence": text(cost.get("first_decisive_evidence")),
            "tier": text(cost.get("cost_tier")),
            "bottlenecks": items(cost.get("bottlenecks")),
        },
        "risk_controls": risk_controls,
        "gaps": gaps,
    }


def _build_evidence_interpretation(payload: Any) -> dict[str, Any] | None:
    """Turn an evidence-package JSON payload into a reader-friendly view."""

    if not isinstance(payload, dict):
        return None

    source_specs = (
        ("local_germplasm", "种质资源"),
        ("local_crop_kg", "知识图谱"),
        ("local_rag", "RAG 资料"),
        ("local_marker_qtl", "标记与 QTL"),
        ("local_phenotype_protocols", "表型协议"),
        ("local_field_trials", "田间试验"),
        ("external_literature", "外部文献"),
    )

    def results_for(key: str) -> list[dict[str, Any]]:
        value = payload.get(key)
        if isinstance(value, dict) and isinstance(value.get("results"), list):
            return [item for item in value["results"] if isinstance(item, dict)]
        if isinstance(value, list):
            return [item for item in value if isinstance(item, dict)]
        return []

    def clip(value: Any, limit: int = 260) -> str:
        text = _route_value_text(value)
        return text if len(text) <= limit else f"{text[:limit].rstrip()}…"

    def source_url(value: Any) -> str:
        text = _route_value_text(value)
        for token in text.replace(";", " ").split():
            if token.startswith(("http://", "https://")):
                return token.rstrip(",")
        return ""

    confidence_labels = {
        "high": "较强",
        "medium": "中等",
        "low": "较弱",
        "local_germplasm_high": "本地高置信线索",
        "local_germplasm_clue": "本地种质线索",
        "local_kg_clue": "知识图谱线索",
        "local_rag": "RAG 资料线索",
        "local_field_trial_clue": "田间试验线索",
    }

    source_groups = []
    key_findings = []
    for key, label in source_specs:
        results = results_for(key)
        if not results:
            continue
        source_groups.append({"label": label, "count": len(results)})
        for result in results[:2]:
            title = (
                result.get("name")
                or result.get("title")
                or result.get("trait")
                or result.get("protocol_id")
                or result.get("trial_id")
                or result.get("accession_id")
                or "未命名证据"
            )
            summary = (
                result.get("summary")
                or result.get("evidence_summary")
                or result.get("text")
                or result.get("phenotype_summary")
                or result.get("measurement_method")
                or result.get("notes")
                or "该条记录已进入证据包。"
            )
            key_findings.append(
                {
                    "source_label": label,
                    "title": clip(title, 120),
                    "summary": clip(summary),
                    "confidence": confidence_labels.get(
                        str(result.get("evidence_level") or result.get("data_confidence") or ""),
                        "待进一步确认",
                    ),
                    "source_url": source_url(result.get("source_refs")),
                }
            )

    gaps = payload.get("evidence_gaps") or []
    gap_labels = {
        "material_availability": "材料可得性",
        "marker_assay_preflight": "标记/基因型验证",
        "pending_local_field_validation": "本地田间验证",
        "general_evidence_gap": "一般证据缺口",
        "evidence_conflict": "证据冲突",
    }
    gap_rows = []
    gap_types: set[str] = set()
    if isinstance(gaps, list):
        for gap in gaps:
            if not isinstance(gap, dict):
                continue
            gap_type = str(gap.get("type") or "general_evidence_gap")
            gap_types.add(gap_type)
            gap_rows.append(
                {
                    "label": gap_labels.get(gap_type, gap_type.replace("_", " ")),
                    "severity": "高" if str(gap.get("severity", "")).lower() == "high" else "需关注",
                    "message": clip(gap.get("message") or gap.get("target") or "需要进一步确认"),
                }
            )

    next_steps = []
    if "material_availability" in gap_types:
        next_steps.append("确认候选亲本的身份、来源和本地可获得性。")
    if "marker_assay_preflight" in gap_types:
        next_steps.append("检测亲本多态性，确认标记或基因型方案可以用于选择。")
    if "pending_local_field_validation" in gap_types:
        next_steps.append("在记录环境条件下开展重复、多环境表型和产量验证。")
    if not next_steps:
        next_steps.append("由专家审核证据后，再进入育种假设和路线设计。")
    elif "由专家审核证据后，再进入育种假设和路线设计。" not in next_steps:
        next_steps.append("由专家审核证据后，再进入育种假设和路线设计。")

    total_records = sum(group["count"] for group in source_groups)
    source_count = len(source_groups)
    if gaps:
        support_label = "有条件支持"
        conclusion = (
            f"已从 {source_count} 类来源整理出 {total_records} 条证据。"
            "这些证据可以支持候选方向，但不能替代本地基因型、表型和田间验证。"
        )
    elif source_count >= 3:
        support_label = "多源支持"
        conclusion = f"已从 {source_count} 类来源整理出 {total_records} 条证据，可进入专家审核。"
    else:
        support_label = "初步支持"
        conclusion = "目前已形成初步证据链，仍建议补充更多独立来源。"

    return {
        "status": "待专家审核",
        "support_label": support_label,
        "conclusion": conclusion,
        "research_goal": clip(payload.get("research_goal") or "当前育种研究目标", 360),
        "source_groups": source_groups,
        "key_findings": key_findings[:8],
        "gaps": gap_rows[:10],
        "next_steps": next_steps,
        "raw_json": json.dumps(payload, ensure_ascii=False, indent=2),
        "snapshot_id": str(payload.get("knowledge_snapshot_id") or "未记录"),
        "batch_id": str(payload.get("knowledge_batch_id") or "未记录"),
        "search_mode": str(payload.get("mode") or payload.get("search_strategy") or "未记录"),
    }


def _agent_output_lineage(outputs: list[dict[str, Any]]) -> list[dict[str, Any]]:
    lineage = []
    for index, output in enumerate(outputs):
        latest = output.get("outputs") or []
        lineage.append(
            {
                "number": index + 1,
                "name": output.get("name", ""),
                "label": output.get("label", ""),
                "purpose": output.get("purpose", ""),
                "summary": output.get("summary", ""),
                "output_count": output.get("output_count", 0),
                "latest_title": latest[0].get("title") if latest else "尚无成果",
                "anchor": f"agent-output-{index + 1}",
            }
        )
    return lineage


def _decorate_agent_output_reviews(
    agents: list[dict[str, Any]],
    reviews: dict[str, AgentOutputReview],
) -> None:
    """Attach the latest mentor verdict to each output card in-place."""

    labels = {
        "pending": "待审核",
        "approved": "已通过",
        "needs_revision": "需修改",
        "rejected": "不通过",
    }
    for agent in agents:
        for output in agent.get("outputs", []):
            review = reviews.get(str(output.get("output_key") or ""))
            output["review"] = (
                {
                    "status": review.status,
                    "status_label": labels[review.status],
                    "reviewer": review.reviewer,
                    "note": review.note,
                    "created_at": review.created_at.isoformat(),
                }
                if review is not None
                else {
                    "status": "pending",
                    "status_label": labels["pending"],
                    "reviewer": "",
                    "note": "",
                    "created_at": "",
                }
            )


async def _enqueue_mentor_followup(
    cfg: Config,
    conn: Any,
    session: Any,
    review: AgentOutputReview,
) -> None:
    """Translate an expert rejection into one idempotent six-agent task."""

    task_spec: dict[str, Any] | None = None
    if review.agent == "Evidence Curator":
        task_spec = {
            "agent": "evidence_curator",
            "action": "CurateEvidencePackage",
            "payload": {
                "mode": "dfrs",
                "focus": "mentor_review",
                "source": "mentor_review",
                "enqueue_design": False,
                "mentor_review_id": review.id,
            },
            "priority": 80,
        }
    elif review.agent == "Breeding Designer":
        task_spec = {
            "agent": "breeding_designer",
            "action": "DesignHypothesis",
            "payload": {
                "strategy": "literature",
                "n": 1,
                "source": "mentor_review",
                "mentor_review_id": review.id,
                "parent_hypothesis_id": review.target_id,
                "iteration_action": "revise",
            },
            "priority": 90,
        }
    elif review.agent == "Validation Planner":
        task_spec = {
            "agent": "validation_planner",
            "action": "PlanValidation",
            "payload": {"source": "mentor_review", "mentor_review_id": review.id},
            "priority": 85,
        }
    elif review.agent == "Risk Reviewer":
        task_spec = {
            "agent": "risk_reviewer",
            "action": "AssessHypothesisEvidence",
            "payload": {
                "kind": "full",
                "source": "mentor_review",
                "mentor_review_id": review.id,
            },
            "priority": 82,
        }
    elif review.agent == "Iteration Orchestrator":
        task_spec = {
            "agent": "iteration_orchestrator",
            "action": "DecideIteration",
            "payload": {"source": "mentor_review", "mentor_review_id": review.id},
            "priority": 80,
        }
    if task_spec is None:
        return

    task = Task(
        id=ids.task_id(),
        session_id=session.id,
        created_at=datetime.now(UTC),
        agent=task_spec["agent"],
        action=task_spec["action"],
        target_id=review.target_id,
        payload=task_spec["payload"],
        priority=task_spec["priority"],
        status="pending",
        idempotency_key=(
            f"{session.id}::mentor_review::{review.output_key}::{review.status}"
        ),
    )
    await task_repo.enqueue(conn, task)


async def _pairwise_calibration_summary(
    conn: aiosqlite.Connection,
    session_id: str,
) -> dict[str, int]:
    """Return compact ranking-progress counts for the Session leaderboard."""

    async with conn.execute(
        """SELECT COUNT(*) AS total,
                      SUM(CASE WHEN mode='pairwise' THEN 1 ELSE 0 END) AS pairwise,
                      SUM(CASE WHEN mode='debate' THEN 1 ELSE 0 END) AS debate
             FROM pairwise_calibration_matches
             WHERE session_id=? AND mode != 'invalid'""",
        (session_id,),
    ) as cur:
        row = await cur.fetchone()
    async with conn.execute(
        """SELECT COUNT(*) AS n
             FROM hypotheses
             WHERE session_id=? AND calibration_score IS NOT NULL""",
        (session_id,),
    ) as cur:
        scored = await cur.fetchone()
    return {
        "total": int(row["total"] or 0) if row else 0,
        "pairwise": int(row["pairwise"] or 0) if row else 0,
        "debate": int(row["debate"] or 0) if row else 0,
        "scored_hypotheses": int(scored["n"] or 0) if scored else 0,
    }


_SOURCE_URL_RE = re.compile(r"\[Source:\s*(https?://[^\]\s]+)\]")
_BARE_URL_RE = re.compile("(?<!\\]\\()(?<!href=\")(?P<url>https?://[^\\s\\]\\)>,\\u3002\\uff1b\\uff0c]+)")
_HYP_BRACKET_RE = re.compile(r"\[(?:H-\s*)?(?P<hid>hyp_[A-Za-z0-9_:-]+)\]")
_HYP_CODE_RE = re.compile(r"`(?P<hid>hyp_[A-Za-z0-9_:-]+)`")


def _link_overview_references(markdown: str, session_id: str) -> str:
    """Make overview source URLs and hypothesis IDs clickable before rendering.

    The original artifact remains unchanged; this only improves the web view.
    Markdown output is still passed through the existing sanitizer.
    """

    def source_repl(match: re.Match[str]) -> str:
        url = match.group(1)
        return f"[Source: {url}]({url})"

    def hyp_link(hid: str) -> str:
        return f"/sessions/{session_id}/hypotheses/{hid}"

    def hyp_bracket_repl(match: re.Match[str]) -> str:
        hid = match.group("hid")
        return f"[H-{hid}]({hyp_link(hid)})"

    def hyp_code_repl(match: re.Match[str]) -> str:
        hid = match.group("hid")
        return f"[`{hid}`]({hyp_link(hid)})"

    linked = _SOURCE_URL_RE.sub(source_repl, markdown)
    linked = _HYP_BRACKET_RE.sub(hyp_bracket_repl, linked)
    linked = _HYP_CODE_RE.sub(hyp_code_repl, linked)
    linked = _link_bare_urls_outside_markdown_links(linked)
    return linked


def _localize_legacy_chinese_overview(markdown: str) -> str:
    """Translate known English audit fragments in pre-bilingual reports.

    Older sessions stored one fallback overview that could contain English
    source-map and audit text. Keep those historical reports readable in the
    Chinese UI without rewriting the original artifact on disk.
    """

    replacements = {
        "# System termination rationale": "# 系统终止原因",
        "# Source map and evidence gaps": "# 来源图谱与证据缺口",
        "- Main sources found in the report and evidence context:": "- 报告和证据上下文中的主要来源：",
        "- Main sources visible in the report and evidence context:": "- 报告和证据上下文中可见的主要来源：",
        ": supports materials, markers/QTL, RAG evidence, validation plans, or risk judgments.": "：支持材料、标记/QTL、RAG 证据、验证方案或风险判断。",
        ": supports material, marker/QTL, RAG evidence, validation, or risk judgments.": "：支持材料、标记/QTL、RAG 证据、验证方案或风险判断。",
        "- Evidence gap: no extractable sources found; add local RAG or literature mappings.": "- 证据缺口：未找到可提取的来源，请补充本地 RAG 或文献映射。",
        "- Evidence gap: no extractable source URL was found; add local RAG or literature source mapping.": "- 证据缺口：未找到可提取的来源 URL，请补充本地 RAG 或文献来源映射。",
        "- Evidence gap: next iteration should close material availability, parent polymorphism, single-environment evidence, GxE stability, and go/no-go thresholds.": "- 证据缺口：下一轮需要补齐材料可得性、亲本多态性、单环境证据、G×E 稳定性以及推进/停止阈值。",
        "- Evidence gap: next cycle must close material availability, parent polymorphism, single-environment evidence, GxE stability, and go/no-go thresholds.": "- 证据缺口：下一轮需要补齐材料可得性、亲本多态性、单环境证据、G×E 稳定性以及推进/停止阈值。",
        "# Final report audit": "# 最终报告审计",
        "Passed deterministic checks: required sections are present, important claim lines include source URLs or hypothesis references, and core breeding decision elements are represented.": "确定性检查已通过：必需章节齐全，重要结论包含来源 URL 或假设引用，核心育种决策要素已覆盖。",
        "Needs attention before treating this as a polished advisor-facing report.": "在将本报告作为完整专家报告使用前，仍需处理以下问题。",
        "## Missing sections": "## 缺少的章节",
        "## Missing breeding decision elements": "## 缺少的育种决策要素",
        "## Important lines that may need inline support": "## 需要补充行内证据的重点内容",
    }
    localized = markdown
    for source, target in replacements.items():
        localized = localized.replace(source, target)
    return localized


def _link_bare_urls_outside_markdown_links(markdown: str) -> str:
    lines: list[str] = []
    in_code_block = False
    for line in markdown.splitlines():
        if line.lstrip().startswith("```"):
            in_code_block = not in_code_block
            lines.append(line)
            continue
        if in_code_block:
            lines.append(line)
            continue
        lines.append(_link_bare_urls_in_line(line))
    return "\n".join(lines)


def _link_bare_urls_in_line(line: str) -> str:
    out: list[str] = []
    pos = 0
    for match in re.finditer(r"\[[^\]]+\]\([^)]+\)", line):
        out.append(_BARE_URL_RE.sub(lambda m: f"[{m.group('url')}]({m.group('url')})", line[pos:match.start()]))
        out.append(match.group(0))
        pos = match.end()
    out.append(_BARE_URL_RE.sub(lambda m: f"[{m.group('url')}]({m.group('url')})", line[pos:]))
    return "".join(out)


async def _load_breeding_route_view(
    cfg: Config,
    hypothesis: Any,
    decision: dict[str, Any],
    *,
    language: str,
) -> dict[str, Any]:
    """Build the concise, execution-first view shown on a route detail page."""

    record: dict[str, Any] = {}
    artifact_path = str(getattr(hypothesis, "artifact_path", "") or "")
    if artifact_path:
        try:
            payload = await read_json(cfg, artifact_path)
            candidate = payload.get("record") if isinstance(payload, dict) else None
            if isinstance(candidate, dict):
                record = candidate
            elif isinstance(payload, dict):
                record = payload
        except (OSError, ValueError, KeyError, TypeError):
            record = {}

    suffix = "_en" if language == "en" else "_zh"

    def text_field(name: str, fallback: str = "") -> str:
        value = record.get(f"{name}{suffix}")
        if value in (None, ""):
            value = record.get(name, fallback)
        return _route_value_text(value)

    context_key = "breeding_context_en" if language == "en" else "breeding_context_zh"
    context = record.get(context_key) or record.get("breeding_context") or {}
    if not isinstance(context, dict):
        context = {}

    def context_field(name: str) -> str:
        return _route_value_text(context.get(name, ""))

    def item(label: str, value: str) -> dict[str, str] | None:
        return {"label": label, "value": value} if value else None

    label = (lambda zh, en: en if language == "en" else zh)
    sections: list[dict[str, Any]] = []
    section_specs = [
        (
            label("路线目标", "Route objective"),
            [
                item(label("作物", "Crop"), context_field("crop")),
                item(label("目标性状", "Target trait"), context_field("target_trait")),
                item(label("目标环境", "Target environment"), context_field("target_population_of_environments")),
                item(label("预期育种价值", "Expected breeding value"), context_field("expected_breeding_value")),
            ],
        ),
        (
            label("材料与路线设计", "Materials and route design"),
            [
                item(label("供体亲本", "Donor parent"), context_field("donor_parent")),
                item(label("轮回亲本", "Recurrent parent"), context_field("recurrent_parent")),
                item(label("育种策略", "Breeding strategy"), context_field("breeding_strategy")),
                item(label("选择方案", "Selection scheme"), context_field("selection_scheme")),
            ],
        ),
        (
            label("分子与表型验证", "Molecular and phenotypic validation"),
            [
                item(label("候选基因/QTL/标记", "Candidate genes/QTL/markers"), context_field("candidate_genes_qtl")),
                item(label("基因型方案", "Genotyping plan"), context_field("genotyping_plan")),
                item(label("表型方案", "Phenotyping plan"), context_field("phenotyping_plan")),
                item(label("田间试验设计", "Field trial design"), context_field("validation_trial_design")),
            ],
        ),
        (
            label("推进条件与风险", "Advancement conditions and risks"),
            [
                item(label("推进判据", "Decision thresholds"), context_field("decision_thresholds")),
                item(label("周期估计", "Cycle estimate"), context_field("cycle_time_estimate")),
                item(label("风险与权衡", "Risks and trade-offs"), context_field("risks_tradeoffs")),
                item(label("证据缺口", "Evidence gaps"), context_field("evidence_gaps")),
                item(label("替代路线", "Fallback route"), context_field("fallback_route")),
            ],
        ),
    ]
    for title, items in section_specs:
        visible_items = [entry for entry in items if entry is not None]
        if visible_items:
            sections.append({"title": title, "items": visible_items})

    validation_summary = record.get("validation_plan_summary")
    risk_summary = record.get("risk_review_summary")
    evidence_counts = record.get("evidence_package_counts")
    gaps = record.get("evidence_gap_types") or []
    citations = record.get("citations") or []
    critical_evidence_gaps: list[dict[str, Any]] = []
    must_resolve_items: list[dict[str, Any]] = []
    validation_plan_path = record.get("validation_plan_path")
    if validation_plan_path:
        try:
            validation_plan = await read_json(cfg, validation_plan_path)
        except (OSError, ValueError, KeyError, TypeError):
            validation_plan = {}
        if isinstance(validation_plan, dict):
            critical_evidence_gaps = [
                item for item in validation_plan.get("critical_evidence_gaps") or []
                if isinstance(item, dict)
            ]
    risk_review_path = record.get("risk_review_path")
    if risk_review_path:
        try:
            risk_review = await read_json(cfg, risk_review_path)
        except (OSError, ValueError, KeyError, TypeError):
            risk_review = {}
        if isinstance(risk_review, dict):
            must_resolve_items = [
                item for item in risk_review.get("must_resolve_before_prioritization") or []
                if isinstance(item, dict)
            ]
    return {
        "available": bool(record),
        "title": text_field("title", getattr(hypothesis, "title", "")),
        "statement": text_field("statement", getattr(hypothesis, "summary", "")),
        "mechanism": text_field("mechanism"),
        "sections": sections,
        "evidence_counts": evidence_counts if isinstance(evidence_counts, dict) else {},
        "evidence_gap_types": [str(gap) for gap in gaps if gap],
        "citation_count": len(citations) if isinstance(citations, list) else 0,
        "validation_summary": validation_summary if isinstance(validation_summary, dict) else {},
        "risk_summary": risk_summary if isinstance(risk_summary, dict) else {},
        "critical_evidence_gaps": critical_evidence_gaps,
        "must_resolve_items": must_resolve_items,
        "decision": decision,
        "audit": record.get("breeding_design_card_audit") or {},
    }


def _route_value_text(value: Any) -> str:
    if value in (None, "", [], {}):
        return ""
    if isinstance(value, dict):
        return "；".join(
            f"{key}：{_route_value_text(item)}"
            for key, item in value.items()
            if _route_value_text(item)
        )
    if isinstance(value, (list, tuple, set)):
        return "；".join(_route_value_text(item) for item in value if _route_value_text(item))
    return str(value).strip()


def _hypothesis_text_for_language(text: str, lang: str) -> str:
    if lang.lower() == "en":
        block = _extract_marker_block(text, "HYPOTHESIS_EN")
        if block is not None:
            return block
    else:
        block = _extract_marker_block(text, "HYPOTHESIS_ZH")
        if block is not None:
            return block
    return text


def _markdown_title(text: str) -> str | None:
    for line in text.splitlines():
        stripped = line.strip()
        if stripped.startswith("# "):
            return stripped[2:].strip() or None
    return None


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


def _load_germplasm_resource_rows(
    cfg: Config,
    overview_path: str | None,
) -> list[dict[str, str]]:
    if not overview_path:
        return []
    base = cfg.data_dir.resolve()
    try:
        path = (cfg.data_dir / overview_path).resolve()
        path.relative_to(base)
    except (ValueError, OSError):
        return []
    if not path.is_file():
        return []
    try:
        return _extract_germplasm_table(path.read_text(encoding="utf-8"))
    except OSError:
        return []


def _extract_germplasm_table(markdown: str) -> list[dict[str, str]]:
    lines = markdown.splitlines()
    start = next(
        (
            idx
            for idx, line in enumerate(lines)
            if line.strip() in {"# Germplasm resource evidence table", "## Germplasm resource evidence table"}
        ),
        None,
    )
    if start is None:
        return []

    table_lines: list[str] = []
    for line in lines[start + 1:]:
        stripped = line.strip()
        if not stripped:
            if table_lines:
                break
            continue
        if stripped.startswith("#") or stripped == "---":
            break
        if stripped.startswith("|"):
            table_lines.append(stripped)
            continue
        if table_lines:
            break

    if len(table_lines) < 3:
        return []

    headers = _split_markdown_table_row(table_lines[0])
    expected = ["Material", "Accession ID", "Use / trait clue", "Source", "Risk / evidence gap"]
    if headers != expected:
        return []

    rows: list[dict[str, str]] = []
    for line in table_lines[2:]:
        cells = _split_markdown_table_row(line)
        if len(cells) != len(headers):
            continue
        rows.append(dict(zip(headers, cells, strict=True)))
    return rows


def _load_iteration_decisions(
    cfg: Config,
    session_id: str,
    hypothesis_id: str,
) -> list[dict[str, Any]]:
    base = cfg.data_dir.resolve()
    iteration_dir = cfg.data_dir / "artifacts" / session_id / "iteration"
    try:
        resolved_dir = iteration_dir.resolve()
        resolved_dir.relative_to(base)
    except (ValueError, OSError):
        return []
    if not resolved_dir.is_dir():
        return []

    decisions: list[dict[str, Any]] = []
    for path in sorted(resolved_dir.glob("decision_*.json")):
        try:
            resolved_path = path.resolve()
            resolved_path.relative_to(resolved_dir)
            payload = json.loads(resolved_path.read_text(encoding="utf-8"))
        except (ValueError, OSError, json.JSONDecodeError):
            continue
        if not isinstance(payload, dict):
            continue
        if payload.get("hypothesis_id") != hypothesis_id:
            continue
        item = dict(payload)
        item["decision_path"] = resolved_path.relative_to(cfg.data_dir).as_posix()
        decisions.append(item)

    return sorted(
        decisions,
        key=lambda item: str(item.get("created_at") or ""),
        reverse=True,
    )


def _latest_iteration_decisions_for_session(
    cfg: Config,
    session_id: str,
) -> dict[str, dict[str, Any]]:
    return _shared_latest_iteration_decisions_for_session(cfg, session_id)


def _iteration_decision_summary(payload: dict[str, Any]) -> dict[str, Any]:
    reasons = [str(reason) for reason in payload.get("reasons") or [] if reason]
    package_path = payload.get("evidence_package_path")
    score = payload.get("total_score")
    return {
        "hypothesis_id": str(payload.get("hypothesis_id") or ""),
        "action": str(payload.get("action") or "pending"),
        "total_score": score if isinstance(score, int | float) else None,
        "review_gate": payload.get("review_gate"),
        "next_step_recommendation": payload.get("next_step_recommendation"),
        "created_at": payload.get("created_at"),
        "reason_summary": reasons[0] if reasons else "",
        "evidence_package_path": Path(package_path).as_posix() if isinstance(package_path, str) else "",
        "has_evidence_package": isinstance(package_path, str) and bool(package_path),
    }


def _iteration_audit_summary(decisions: dict[str, dict[str, Any]]) -> dict[str, Any]:
    return _shared_iteration_audit_summary(decisions)


def _action_priority(action: str) -> int:
    return {
        "reject": 0,
        "pause": 1,
        "revise": 2,
        "expand": 3,
        "pending": 4,
        "keep": 5,
    }.get(action, 4)


def _rank_hypotheses_for_prioritized_routes(
    hypotheses: list[Any],
    decisions: dict[str, dict[str, Any]],
) -> tuple[list[Any], dict[str, dict[str, Any]]]:
    return _shared_rank_hypotheses_for_prioritized_routes(hypotheses, decisions)


def _route_admission_summary(
    hypothesis: Any,
    decision: dict[str, Any] | None,
    *,
    min_pairwise_calibrations: int = 3,
) -> dict[str, Any]:
    return _shared_route_admission_summary(
        hypothesis,
        decision,
        min_pairwise_calibrations=min_pairwise_calibrations,
    )


def _localized_route_admission(admission: dict[str, Any]) -> dict[str, Any]:
    item = dict(admission)
    item["reasons"] = [
        _localize_decision_text(str(reason)) for reason in admission.get("reasons") or []
    ]
    item["next_step"] = _localize_decision_text(str(admission.get("next_step") or ""))
    return item


def _composite_breeding_rank_score(
    hypothesis: Any,
    decision: dict[str, Any] | None,
) -> dict[str, Any]:
    return _shared_composite_breeding_rank_score(hypothesis, decision)


def _load_route_revision_graph_view(
    hypotheses: list[Any],
    decisions: dict[str, dict[str, Any]],
    *,
    focus_id: str | None = None,
) -> dict[str, Any]:
    hyp_by_id = {str(hypothesis.id): hypothesis for hypothesis in hypotheses}
    raw_edges = _route_revision_edges(hypotheses, decisions)
    selected_ids = set(hyp_by_id)
    scope = "session"
    title = "Route revision graph"
    if focus_id:
        selected_ids = _route_revision_neighborhood(focus_id, raw_edges)
        selected_ids.add(focus_id)
        scope = "hypothesis"
        title = "Route revision subgraph"

    selected_hypotheses = [
        hypothesis
        for hypothesis in hypotheses
        if str(hypothesis.id) in selected_ids
    ]
    selected_edges = [
        edge
        for edge in raw_edges
        if edge["source"] in selected_ids and edge["target"] in selected_ids
    ]
    nodes = _layout_route_revision_nodes(selected_hypotheses, selected_edges, decisions)
    edge_rows = _route_revision_edge_rows(selected_edges)
    return {
        "available": bool(nodes),
        "title": title,
        "scope": scope,
        "focus_id": focus_id,
        "path": "derived:hypotheses.parent_ids + iteration decisions",
        "node_count": len(selected_hypotheses),
        "edge_count": len(selected_edges),
        "visible_node_count": len(nodes),
        "visible_edge_count": len(edge_rows),
        "root_count": sum(1 for node in nodes if node["depth"] == 0),
        "leaf_count": _route_revision_leaf_count(nodes, edge_rows),
        "truncated": False,
        "svg_width": max(1120, max((int(node["x"]) + 160 for node in nodes), default=1120)),
        "svg_height": max(620, max((int(node["y"]) + 110 for node in nodes), default=620)),
        "nodes": nodes,
        "edges": edge_rows,
        "action_counts": _count_by_key(nodes, "action"),
    }



def _hypothesis_closed_loop_context(
    hypotheses: list[Any],
    decisions: dict[str, dict[str, Any]],
    hypothesis_id: str,
    *,
    evidence_subgraph: dict[str, Any],
) -> dict[str, Any]:
    hyp_by_id = {str(hypothesis.id): hypothesis for hypothesis in hypotheses}
    hypothesis = hyp_by_id.get(hypothesis_id)
    parent_ids = [str(parent_id) for parent_id in getattr(hypothesis, "parent_ids", []) or []]
    parents = [
        _closed_loop_hypothesis_item(parent)
        for parent_id in parent_ids
        if (parent := hyp_by_id.get(parent_id)) is not None
    ]
    children = [
        _closed_loop_hypothesis_item(child)
        for child in hypotheses
        if hypothesis_id in [str(parent_id) for parent_id in getattr(child, "parent_ids", []) or []]
    ]
    decision = decisions.get(hypothesis_id) or {}
    parent_decisions = [
        {
            "hypothesis_id": parent_id,
            "action": (decisions.get(parent_id) or {}).get("action") or "pending",
            "direction": (decisions.get(parent_id) or {}).get("new_hypothesis_direction") or "",
            "decision_path": (decisions.get(parent_id) or {}).get("decision_path") or "",
            "evidence_subgraph_href": f"/sessions/{hypothesis.session_id}/hypotheses/{parent_id}/evidence-subgraph"
            if hypothesis is not None
            else "",
        }
        for parent_id in parent_ids
    ]
    return {
        "available": bool(hypothesis),
        "hypothesis_id": hypothesis_id,
        "parents": parents,
        "children": children,
        "parent_decisions": parent_decisions,
        "decision": decision,
        "action": decision.get("action") or "pending",
        "direction": decision.get("new_hypothesis_direction") or "",
        "decision_path": decision.get("decision_path") or "",
        "evidence_package_path": decision.get("evidence_package_path") or "",
        "validation_plan_path": decision.get("validation_plan_path") or "",
        "risk_review_path": decision.get("risk_review_path") or "",
        "evidence_subgraph_available": bool(evidence_subgraph.get("available")),
        "evidence_subgraph_href": f"/sessions/{hypothesis.session_id}/hypotheses/{hypothesis_id}/evidence-subgraph"
        if hypothesis is not None
        else "",
        "route_revision_subgraph_href": f"/sessions/{hypothesis.session_id}/hypotheses/{hypothesis_id}/route-revision-graph"
        if hypothesis is not None
        else "",
        "source_package_paths": evidence_subgraph.get("source_package_paths") or [],
    }


def _closed_loop_hypothesis_item(hypothesis: Any) -> dict[str, str]:
    return {
        "id": str(hypothesis.id),
        "title": str(hypothesis.title or hypothesis.id),
        "href": f"/sessions/{hypothesis.session_id}/hypotheses/{hypothesis.id}",
        "state": hypothesis_lifecycle_label(hypothesis.state),
    }


def _route_revision_edges(
    hypotheses: list[Any],
    decisions: dict[str, dict[str, Any]],
) -> list[dict[str, Any]]:
    hyp_ids = {str(hypothesis.id) for hypothesis in hypotheses}
    edges: list[dict[str, Any]] = []
    seen: set[tuple[str, str]] = set()
    for child in hypotheses:
        child_id = str(child.id)
        for parent_id in getattr(child, "parent_ids", []) or []:
            parent_id = str(parent_id)
            if parent_id not in hyp_ids or parent_id == child_id:
                continue
            key = (parent_id, child_id)
            if key in seen:
                continue
            seen.add(key)
            parent_decision = decisions.get(parent_id) or {}
            child_decision = decisions.get(child_id) or {}
            action = str(parent_decision.get("action") or child_decision.get("action") or child.strategy)
            direction = str(
                parent_decision.get("new_hypothesis_direction")
                or child_decision.get("new_hypothesis_direction")
                or ""
            )
            edges.append(
                {
                    "source": parent_id,
                    "target": child_id,
                    "action": action,
                    "predicate": action,
                    "direction": direction,
                    "decision_path": str(parent_decision.get("decision_path") or ""),
                    "evidence_package_path": str(parent_decision.get("evidence_package_path") or ""),
                    "validation_plan_path": str(parent_decision.get("validation_plan_path") or ""),
                    "risk_review_path": str(parent_decision.get("risk_review_path") or ""),
                    "evidence_subgraph_href": f"/sessions/{child.session_id}/hypotheses/{parent_id}/evidence-subgraph",
                    "successor_href": f"/sessions/{child.session_id}/hypotheses/{child_id}",
                    "evidence_gap_to_resolve": parent_decision.get("evidence_gap_to_resolve") or [],
                    "do_not_repeat": parent_decision.get("do_not_repeat") or [],
                }
            )
    return edges


def _route_revision_neighborhood(
    focus_id: str,
    edges: list[dict[str, Any]],
) -> set[str]:
    parents: dict[str, set[str]] = {}
    children: dict[str, set[str]] = {}
    for edge in edges:
        source = str(edge["source"])
        target = str(edge["target"])
        parents.setdefault(target, set()).add(source)
        children.setdefault(source, set()).add(target)

    selected: set[str] = set()
    frontier = [focus_id]
    while frontier:
        node_id = frontier.pop()
        for parent_id in parents.get(node_id, set()):
            if parent_id not in selected:
                selected.add(parent_id)
                frontier.append(parent_id)
    frontier = [focus_id]
    while frontier:
        node_id = frontier.pop()
        for child_id in children.get(node_id, set()):
            if child_id not in selected:
                selected.add(child_id)
                frontier.append(child_id)
    return selected



def _layout_route_revision_nodes(
    hypotheses: list[Any],
    edges: list[dict[str, Any]],
    decisions: dict[str, dict[str, Any]],
) -> list[dict[str, Any]]:
    ids = {str(hypothesis.id) for hypothesis in hypotheses}
    parent_map: dict[str, list[str]] = {node_id: [] for node_id in ids}
    for edge in edges:
        source = str(edge["source"])
        target = str(edge["target"])
        if source in ids and target in ids:
            parent_map.setdefault(target, []).append(source)

    depth_cache: dict[str, int] = {}

    def depth(node_id: str, visiting: set[str] | None = None) -> int:
        if node_id in depth_cache:
            return depth_cache[node_id]
        visiting = visiting or set()
        if node_id in visiting:
            return 0
        visiting.add(node_id)
        parents = [parent for parent in parent_map.get(node_id, []) if parent in ids]
        value = 0 if not parents else 1 + max(depth(parent, set(visiting)) for parent in parents)
        depth_cache[node_id] = value
        return value

    buckets: dict[int, list[Any]] = {}
    for hypothesis in hypotheses:
        buckets.setdefault(depth(str(hypothesis.id)), []).append(hypothesis)

    nodes: list[dict[str, Any]] = []
    for depth_value in sorted(buckets):
        bucket = sorted(
            buckets[depth_value],
            key=lambda hypothesis: (
                str((decisions.get(hypothesis.id) or {}).get("action") or "pending"),
                str(hypothesis.title or hypothesis.id),
            ),
        )
        for idx, hypothesis in enumerate(bucket):
            decision = decisions.get(hypothesis.id) or {}
            rank = _composite_breeding_rank_score(hypothesis, decision)
            action = str(decision.get("action") or "pending")
            lifecycle = hypothesis_lifecycle_label(hypothesis.state)
            nodes.append(
                {
                    "id": str(hypothesis.id),
                    "label": _short_label(hypothesis.title or hypothesis.id, max_len=28),
                    "full_label": str(hypothesis.title or hypothesis.id),
                    "state": lifecycle,
                    "internal_state": str(hypothesis.state),
                    "action": action,
                    "action_class": _css_token(action),
                    "score": rank.get("score"),
                    "depth": depth_value,
                    "x": 90 + depth_value * 240,
                    "y": 70 + idx * 105,
                    "href": f"/sessions/{hypothesis.session_id}/hypotheses/{hypothesis.id}",
                }
            )
    return nodes


def _route_revision_edge_rows(edges: list[dict[str, Any]]) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    for edge in edges:
        rows.append(
            {
                "source": str(edge["source"]),
                "target": str(edge["target"]),
                "predicate": str(edge.get("predicate") or edge.get("action") or "evolved"),
                "action": str(edge.get("action") or "evolved"),
                "action_class": _css_token(edge.get("action") or "evolved"),
                "direction": str(edge.get("direction") or ""),
                "decision_path": str(edge.get("decision_path") or ""),
                "evidence_package_path": str(edge.get("evidence_package_path") or ""),
                "validation_plan_path": str(edge.get("validation_plan_path") or ""),
                "risk_review_path": str(edge.get("risk_review_path") or ""),
                "evidence_subgraph_href": str(edge.get("evidence_subgraph_href") or ""),
                "successor_href": str(edge.get("successor_href") or ""),
                "evidence_gap_to_resolve": [
                    str(item)
                    for item in edge.get("evidence_gap_to_resolve") or []
                    if item
                ],
                "do_not_repeat": [
                    str(item)
                    for item in edge.get("do_not_repeat") or []
                    if item
                ],
            }
        )
    return rows


def _route_revision_leaf_count(
    nodes: list[dict[str, Any]],
    edges: list[dict[str, Any]],
) -> int:
    sources = {str(edge["source"]) for edge in edges}
    return sum(1 for node in nodes if str(node["id"]) not in sources)


def _css_token(value: Any) -> str:
    return re.sub(r"[^a-z0-9_-]+", "-", str(value or "unknown").lower()).strip("-") or "unknown"


def _scorecard_by_dimension(rows: list[Any]) -> dict[str, float]:
    out: dict[str, float] = {}
    for row in rows:
        if not isinstance(row, dict):
            continue
        dimension = row.get("dimension")
        score = row.get("score")
        if isinstance(dimension, str) and isinstance(score, int | float):
            out[dimension] = float(score)
    return out


def _bounded_score(value: Any, *, default: float) -> float:
    if not isinstance(value, int | float):
        return default
    return max(0.0, min(100.0, float(value)))


def _calibration_score_to_ui_score(calibration_score: Any) -> float:
    if not isinstance(calibration_score, int | float):
        return 50.0
    return max(0.0, min(100.0, 50.0 + (float(calibration_score) - 1200.0) / 8.0))


TEMPLATES.env.globals["calibration_score_to_ui_score"] = _calibration_score_to_ui_score


def _action_rank_multiplier(action: str) -> float:
    return {
        "keep": 1.0,
        "expand": 0.88,
        "revise": 0.72,
        "pending": 0.68,
        "pause": 0.35,
        "reject": 0.0,
    }.get(action, 0.68)


def _action_rank_penalty(action: str) -> float:
    return {
        "keep": 0.0,
        "expand": 3.0,
        "revise": 8.0,
        "pending": 10.0,
        "pause": 25.0,
        "reject": 100.0,
    }.get(action, 10.0)


def _load_session_acceptance(cfg: Config, session_id: str) -> dict[str, Any]:
    """Load the model-free acceptance result written at session finalization."""

    rel_path = f"artifacts/{session_id}/final/session_acceptance.json"
    payload = _read_artifact_json(cfg, rel_path)
    if not isinstance(payload, dict) or payload.get("status") not in {"pass", "fail"}:
        return {
            "available": False,
            "status": None,
            "checks": [],
            "failed_checks": [],
            "path": rel_path,
        }
    return {
        "available": True,
        "status": payload.get("status"),
        "checks": [check for check in payload.get("checks", []) if isinstance(check, dict)],
        "failed_checks": [str(name) for name in payload.get("failed_checks", [])],
        "path": rel_path,
    }


def _session_knowledge_snapshot(session: Any) -> dict[str, Any]:
    config_snapshot = getattr(session, "config_snapshot", {})
    snapshot = config_snapshot.get("knowledge_snapshot") if isinstance(config_snapshot, dict) else None
    return snapshot if isinstance(snapshot, dict) else {}


def _load_evidence_graph_view(
    cfg: Config,
    session_id: str,
    *,
    max_nodes: int = 80,
    max_edges: int = 140,
) -> dict[str, Any]:
    rel_path = f"artifacts/{session_id}/evidence/breeding_evidence_graph.json"
    payload = _read_artifact_json(cfg, rel_path)
    if not isinstance(payload, dict):
        return _empty_graph_view(rel_path)
    raw_nodes = [node for node in payload.get("nodes", []) if isinstance(node, dict)]
    raw_edges = [edge for edge in payload.get("edges", []) if isinstance(edge, dict)]
    return _graph_view_from_raw(
        raw_nodes,
        raw_edges,
        path=rel_path,
        updated_at=payload.get("updated_at"),
        total_node_count=int(payload.get("node_count") or len(raw_nodes)),
        total_edge_count=int(payload.get("edge_count") or len(raw_edges)),
        max_nodes=max_nodes,
        max_edges=max_edges,
        title="Breeding Evidence Graph",
        scope="session",
    )


def _load_hypothesis_evidence_subgraph_view(
    cfg: Config,
    session_id: str,
    hypothesis_id: str,
    *,
    max_nodes: int = 80,
    max_edges: int = 140,
) -> dict[str, Any]:
    package_paths = _hypothesis_evidence_package_paths(cfg, session_id, hypothesis_id)
    nodes: list[dict[str, Any]] = []
    edges: list[dict[str, Any]] = []
    source_paths: list[str] = []
    package_summaries: list[dict[str, Any]] = []
    updated_at: str | None = None

    for package_path in package_paths:
        package = _read_artifact_json(cfg, package_path)
        if not isinstance(package, dict):
            continue
        package_summaries.append(_evidence_package_summary(package, package_path))
        graph_delta = package.get("breeding_evidence_graph_delta")
        if not isinstance(graph_delta, dict):
            continue
        source_paths.append(package_path)
        if package.get("updated_at"):
            updated_at = str(package["updated_at"])
        nodes.extend(node for node in graph_delta.get("nodes", []) if isinstance(node, dict))
        edges.extend(edge for edge in graph_delta.get("edges", []) if isinstance(edge, dict))

    if not nodes and not edges:
        view = _empty_graph_view(
            f"artifacts/{session_id}/evidence/package_* for {hypothesis_id}"
        )
        view.update(
            {
                "title": "Hypothesis Evidence Subgraph",
                "scope": "hypothesis",
                "hypothesis_id": hypothesis_id,
                "source_package_paths": [],
                "evidence_package_summaries": package_summaries,
            }
        )
        return view

    view = _graph_view_from_raw(
        nodes,
        edges,
        path=source_paths[0],
        updated_at=updated_at,
        total_node_count=len(nodes),
        total_edge_count=len(edges),
        max_nodes=max_nodes,
        max_edges=max_edges,
        title="Hypothesis Evidence Subgraph",
        scope="hypothesis",
    )
    view["hypothesis_id"] = hypothesis_id
    view["source_package_paths"] = source_paths
    view["evidence_package_summaries"] = package_summaries
    return view


def _hypothesis_evidence_package_paths(
    cfg: Config,
    session_id: str,
    hypothesis_id: str,
) -> list[str]:
    paths: list[str] = []
    seen: set[str] = set()

    for decision in _load_iteration_decisions(cfg, session_id, hypothesis_id):
        package_path = decision.get("evidence_package_path")
        if isinstance(package_path, str) and package_path:
            normalized = Path(package_path).as_posix()
            if normalized not in seen:
                paths.append(normalized)
                seen.add(normalized)

    evidence_dir = cfg.data_dir / "artifacts" / session_id / "evidence"
    base = cfg.data_dir.resolve()
    try:
        resolved_dir = evidence_dir.resolve()
        resolved_dir.relative_to(base)
    except (ValueError, OSError):
        return paths
    if not resolved_dir.is_dir():
        return paths

    for path in sorted(resolved_dir.glob("package_*.json")):
        rel_path = path.resolve().relative_to(cfg.data_dir).as_posix()
        if rel_path in seen:
            continue
        package = _read_artifact_json(cfg, rel_path)
        if isinstance(package, dict) and package.get("target_hypothesis_id") == hypothesis_id:
            paths.append(rel_path)
            seen.add(rel_path)
    return paths


def _evidence_package_summary(package: dict[str, Any], path: str) -> dict[str, Any]:
    kg_package = package.get("local_crop_kg") or {}
    return {
        "path": path,
        "mode": package.get("mode"),
        "search_strategy": package.get("search_strategy"),
        "queries": _as_list(package.get("queries"), limit=6),
        "germplasm": _summarize_germplasm((package.get("local_germplasm") or {}).get("results") or []),
        "kg": _summarize_kg((kg_package.get("results")) or []),
        "rag": _summarize_rag((package.get("local_rag") or {}).get("results") or []),
        "marker_qtl": _summarize_marker_qtl((package.get("local_marker_qtl") or {}).get("results") or []),
        "phenotype_protocols": _summarize_phenotype_protocols(
            (package.get("local_phenotype_protocols") or {}).get("results") or []
        ),
        "field_trials": _summarize_field_trials((package.get("local_field_trials") or {}).get("results") or []),
        "gaps": _summarize_gaps(package.get("evidence_gaps") or []),
    }


def _summarize_germplasm(rows: list[Any], *, limit: int = 6) -> list[dict[str, str]]:
    out: list[dict[str, str]] = []
    for row in rows:
        if not isinstance(row, dict):
            continue
        out.append(
            {
                "accession_id": str(row.get("accession_id") or row.get("name") or ""),
                "name": str(row.get("name") or ""),
                "traits": str(row.get("primary_traits") or ""),
                "availability": str(row.get("availability") or "unknown"),
                "confidence": str(row.get("data_confidence") or "unknown"),
                "risk": str(row.get("risk_notes") or ""),
            }
        )
        if len(out) >= limit:
            break
    return out


def _summarize_kg(rows: list[Any], *, limit: int = 8) -> list[dict[str, Any]]:
    out: list[dict[str, Any]] = []
    for row in rows:
        if not isinstance(row, dict):
            continue
        out.append(
            {
                "id": str(row.get("id") or ""),
                "name": str(row.get("name") or ""),
                "type": str(row.get("type") or ""),
                "confidence": str(row.get("data_confidence") or "unknown"),
                "summary": str(row.get("summary") or ""),
                "edges": [
                    {
                        "predicate": str(edge.get("predicate") or ""),
                        "target": str(edge.get("object_name") or edge.get("object") or ""),
                    }
                    for edge in (row.get("edges") or [])[:3]
                    if isinstance(edge, dict)
                ],
            }
        )
        if len(out) >= limit:
            break
    return out


def _summarize_rag(rows: list[Any], *, limit: int = 6) -> list[dict[str, str]]:
    out: list[dict[str, str]] = []
    for row in rows:
        if not isinstance(row, dict):
            continue
        out.append(
            {
                "title": str(row.get("title") or row.get("source_path") or ""),
                "url": str(row.get("url") or ""),
                "excerpt": _short_label(row.get("text") or "", max_len=180),
            }
        )
        if len(out) >= limit:
            break
    return out


def _summarize_marker_qtl(rows: list[Any], *, limit: int = 8) -> list[dict[str, str]]:
    out: list[dict[str, str]] = []
    for row in rows:
        if not isinstance(row, dict):
            continue
        out.append(
            {
                "marker_id": str(row.get("marker_id") or ""),
                "marker_name": str(row.get("marker_name") or ""),
                "trait": str(row.get("trait") or ""),
                "gene_or_qtl": str(row.get("gene_or_qtl") or ""),
                "validation_status": str(row.get("validation_status") or ""),
                "confidence": str(row.get("data_confidence") or "unknown"),
                "risk": str(row.get("risk_notes") or ""),
                "source": str(row.get("source_refs") or ""),
            }
        )
        if len(out) >= limit:
            break
    return out


def _summarize_phenotype_protocols(rows: list[Any], *, limit: int = 8) -> list[dict[str, str]]:
    out: list[dict[str, str]] = []
    for row in rows:
        if not isinstance(row, dict):
            continue
        out.append(
            {
                "protocol_id": str(row.get("protocol_id") or ""),
                "trait": str(row.get("trait") or ""),
                "target_environment": str(row.get("target_environment") or ""),
                "method": _short_label(row.get("measurement_method") or "", max_len=140),
                "thresholds": _short_label(row.get("decision_thresholds") or "", max_len=140),
                "validation_status": str(row.get("validation_status") or ""),
                "confidence": str(row.get("data_confidence") or "unknown"),
                "risk": str(row.get("risk_notes") or ""),
            }
        )
        if len(out) >= limit:
            break
    return out


def _summarize_field_trials(rows: list[Any], *, limit: int = 8) -> list[dict[str, str]]:
    out: list[dict[str, str]] = []
    for row in rows:
        if not isinstance(row, dict):
            continue
        out.append(
            {
                "trial_id": str(row.get("trial_id") or ""),
                "trait": str(row.get("trait") or ""),
                "environment": str(row.get("environment") or ""),
                "materials": str(row.get("materials") or ""),
                "outcome": str(row.get("decision_outcome") or ""),
                "confidence": str(row.get("data_confidence") or "unknown"),
                "phenotype_summary": _short_label(row.get("phenotype_summary") or "", max_len=140),
                "risk": str(row.get("risk_notes") or ""),
            }
        )
        if len(out) >= limit:
            break
    return out


def _summarize_gaps(rows: list[Any], *, limit: int = 10) -> list[dict[str, str]]:
    out: list[dict[str, str]] = []
    for row in rows:
        if not isinstance(row, dict):
            continue
        out.append(
            {
                "severity": str(row.get("severity") or "unknown"),
                "type": str(row.get("type") or "gap"),
                "target": str(row.get("target") or ""),
                "message": str(row.get("message") or ""),
            }
        )
        if len(out) >= limit:
            break
    return out


def _as_list(value: Any, *, limit: int) -> list[str]:
    if not isinstance(value, list):
        return []
    return [str(item) for item in value[:limit]]


def _graph_view_from_raw(
    raw_nodes: list[dict[str, Any]],
    raw_edges: list[dict[str, Any]],
    *,
    path: str,
    updated_at: Any,
    total_node_count: int,
    total_edge_count: int,
    max_nodes: int,
    max_edges: int,
    title: str,
    scope: str,
) -> dict[str, Any]:
    completed_nodes = _complete_graph_endpoint_nodes(raw_nodes, raw_edges)
    visible_nodes = _select_graph_nodes(completed_nodes, raw_edges, limit=max_nodes)
    visible_ids = {str(node.get("id")) for node in visible_nodes if node.get("id")}
    visible_edges = [
        edge
        for edge in raw_edges
        if str(edge.get("source")) in visible_ids and str(edge.get("target")) in visible_ids
    ][:max_edges]

    nodes = _layout_graph_nodes(visible_nodes)
    edge_rows = [_graph_edge_row(edge) for edge in visible_edges]
    cy_elements = _cytoscape_elements(nodes, edge_rows)
    return {
        "available": True,
        "title": title,
        "scope": scope,
        "path": path,
        "updated_at": updated_at,
        "node_count": total_node_count,
        "edge_count": total_edge_count,
        "visible_node_count": len(nodes),
        "visible_edge_count": len(edge_rows),
        "truncated": len(completed_nodes) > len(nodes) or len(raw_edges) > len(edge_rows),
        "svg_height": max(760, max((int(node["y"]) + 90 for node in nodes), default=760)),
        "nodes": nodes,
        "edges": edge_rows,
        "cy_elements": cy_elements,
        "node_types": _count_by_key(nodes, "type"),
    }


def _read_artifact_json(cfg: Config, rel_path: str) -> Any:
    base = cfg.data_dir.resolve()
    try:
        path = (cfg.data_dir / rel_path).resolve()
        path.relative_to(base)
        return json.loads(path.read_text(encoding="utf-8"))
    except (ValueError, OSError, json.JSONDecodeError):
        return None


def _complete_graph_endpoint_nodes(
    nodes: list[dict[str, Any]],
    edges: list[dict[str, Any]],
) -> list[dict[str, Any]]:
    node_map: dict[str, dict[str, Any]] = {}
    for node in nodes:
        if node.get("id"):
            node_map[str(node["id"])] = dict(node)
    for edge in edges:
        for endpoint in ("source", "target"):
            node_id = str(edge.get(endpoint) or "")
            if node_id and node_id not in node_map:
                node_map[node_id] = {
                    "id": node_id,
                    "type": _type_from_node_id(node_id),
                    "label": node_id,
                    "status": "referenced",
                }
    return list(node_map.values())


def _empty_graph_view(path: str) -> dict[str, Any]:
    return {
        "available": False,
        "title": "Breeding Evidence Graph",
        "scope": "session",
        "path": path,
        "updated_at": None,
        "node_count": 0,
        "edge_count": 0,
        "visible_node_count": 0,
        "visible_edge_count": 0,
        "truncated": False,
        "svg_height": 760,
        "nodes": [],
        "edges": [],
        "cy_elements": [],
        "node_types": {},
    }


def _type_from_node_id(node_id: str) -> str:
    prefix = node_id.split(":", 1)[0].lower()
    if prefix == "material":
        return "germplasm"
    if prefix in {"gene", "qtl", "marker", "marker_qtl", "gene_qtl"}:
        return "gene_qtl_marker"
    if prefix in {"trait", "risk", "evidence", "environment", "protocol", "trial", "field_trial"}:
        return prefix
    return "other"


def _layout_graph_nodes(nodes: list[dict[str, Any]]) -> list[dict[str, Any]]:
    buckets: dict[str, list[dict[str, Any]]] = {}
    for node in nodes:
        node_type = _graph_node_type(node)
        buckets.setdefault(node_type, []).append(node)

    ordered_types = [
        "germplasm",
        "trait",
        "gene_qtl_marker",
        "environment_protocol",
        "rag_evidence",
        "risk",
        "other",
    ]
    x_by_type = {
        "germplasm": 90,
        "trait": 240,
        "gene_qtl_marker": 405,
        "environment_protocol": 570,
        "rag_evidence": 735,
        "risk": 900,
        "other": 1035,
    }

    laid_out: list[dict[str, Any]] = []
    for node_type in ordered_types:
        bucket = sorted(
            buckets.get(node_type, []),
            key=lambda item: str(item.get("label") or item.get("id") or ""),
        )
        for idx, node in enumerate(bucket):
            laid_out.append(
                {
                    "id": str(node.get("id") or ""),
                    "label": _short_label(node.get("label") or node.get("name") or node.get("id")),
                    "full_label": str(node.get("label") or node.get("name") or node.get("id") or ""),
                    "type": node_type,
                    "raw_type": str(node.get("type") or ""),
                    "status": str(node.get("status") or "unknown"),
                    "evidence_level": str(node.get("evidence_level") or ""),
                    "x": x_by_type[node_type],
                    "y": 70 + idx * 78,
                }
            )
    return laid_out


def _graph_edge_row(edge: dict[str, Any]) -> dict[str, str]:
    return {
        "source": str(edge.get("source") or ""),
        "target": str(edge.get("target") or ""),
        "predicate": str(edge.get("predicate") or ""),
        "provenance": str(edge.get("provenance") or ""),
        "evidence_level": str(edge.get("evidence_level") or ""),
        "status": str(edge.get("status") or ""),
    }


def _cytoscape_elements(
    nodes: list[dict[str, Any]],
    edges: list[dict[str, str]],
) -> list[dict[str, Any]]:
    node_ids = {str(node["id"]) for node in nodes}
    node_labels = {
        str(node.get("id")): str(node.get("full_label") or node.get("label") or node.get("id") or "")
        for node in nodes
    }
    elements: list[dict[str, Any]] = []
    for node in nodes:
        node_type = str(node.get("type") or "other")
        elements.append(
            {
                "group": "nodes",
                "data": {
                    "id": str(node.get("id") or ""),
                    "label": str(node.get("label") or node.get("id") or ""),
                    "full_label": str(node.get("full_label") or node.get("label") or node.get("id") or ""),
                    "type": node_type,
                    "raw_type": str(node.get("raw_type") or ""),
                    "status": str(node.get("status") or ""),
                    "evidence_level": str(node.get("evidence_level") or ""),
                },
                "classes": node_type,
            }
        )
    for index, edge in enumerate(edges, start=1):
        source = str(edge.get("source") or "")
        target = str(edge.get("target") or "")
        if source not in node_ids or target not in node_ids:
            continue
        elements.append(
            {
                "group": "edges",
                "data": {
                    "id": f"edge-{index}",
                    "source": source,
                    "target": target,
                    "source_label": node_labels.get(source, source),
                    "target_label": node_labels.get(target, target),
                    "label": str(edge.get("predicate") or ""),
                    "predicate": str(edge.get("predicate") or ""),
                    "status": str(edge.get("status") or ""),
                    "provenance": str(edge.get("provenance") or ""),
                    "evidence_level": str(edge.get("evidence_level") or ""),
                },
            }
        )
    return elements


def _select_graph_nodes(
    nodes: list[dict[str, Any]],
    edges: list[dict[str, Any]],
    *,
    limit: int,
) -> list[dict[str, Any]]:
    """Choose a representative evidence subgraph instead of slicing raw order.

    Artifact order is ingestion order, so taking the first N nodes can remove all
    trait or risk nodes from the rendered graph. Keep type coverage first, then
    prefer nodes that participate in more evidence relationships.
    """

    if limit <= 0 or len(nodes) <= limit:
        return list(nodes)

    node_map = {
        str(node.get("id")): node
        for node in nodes
        if node.get("id")
    }
    degree: dict[str, int] = {node_id: 0 for node_id in node_map}
    for edge in edges:
        source = str(edge.get("source") or "")
        target = str(edge.get("target") or "")
        if source in node_map and target in node_map:
            degree[source] += 1
            degree[target] += 1

    type_order = [
        "trait",
        "germplasm",
        "gene_qtl_marker",
        "environment_protocol",
        "risk",
        "rag_evidence",
        "other",
    ]
    type_rank = {node_type: index for index, node_type in enumerate(type_order)}

    def sort_key(node: dict[str, Any]) -> tuple[int, int, str]:
        node_id = str(node.get("id") or "")
        node_type = _graph_node_type(node)
        return (
            -degree.get(node_id, 0),
            type_rank.get(node_type, len(type_rank)),
            str(node.get("label") or node_id).lower(),
        )

    connected = [node for node in nodes if degree.get(str(node.get("id")), 0) > 0]
    isolated = [node for node in nodes if degree.get(str(node.get("id")), 0) == 0]
    selected: list[dict[str, Any]] = []
    selected_ids: set[str] = set()

    # Reserve a representative from each evidence type so the graph remains
    # interpretable even when the visible-node budget is smaller than the pack.
    for node_type in type_order:
        candidates = [node for node in connected if _graph_node_type(node) == node_type]
        if not candidates:
            candidates = [node for node in isolated if _graph_node_type(node) == node_type]
        if candidates and len(selected) < limit:
            candidate = sorted(candidates, key=sort_key)[0]
            node_id = str(candidate.get("id") or "")
            if node_id and node_id not in selected_ids:
                selected.append(candidate)
                selected_ids.add(node_id)

    for candidate in sorted(connected, key=sort_key) + sorted(isolated, key=sort_key):
        if len(selected) >= limit:
            break
        node_id = str(candidate.get("id") or "")
        if node_id and node_id not in selected_ids:
            selected.append(candidate)
            selected_ids.add(node_id)

    return selected


def _graph_node_type(node: dict[str, Any]) -> str:
    raw = str(node.get("type") or "").lower()
    node_id = str(node.get("id") or "").lower()
    if raw in {"germplasm", "material"} or node_id.startswith("material:"):
        return "germplasm"
    if raw == "trait" or node_id.startswith("trait:"):
        return "trait"
    if raw in {"gene", "qtl", "marker", "marker_qtl", "gene_qtl"} or any(
        token in node_id for token in ("gene:", "qtl:", "marker:", "marker_qtl:", "gene_qtl:")
    ):
        return "gene_qtl_marker"
    if raw in {"environment", "protocol", "trial", "phenotype_protocol", "field_trial"}:
        return "environment_protocol"
    if raw in {"rag_evidence", "literature", "evidence"} or node_id.startswith("evidence:"):
        return "rag_evidence"
    if raw == "risk" or node_id.startswith("risk:"):
        return "risk"
    return "other"


def _short_label(value: Any, *, max_len: int = 34) -> str:
    text = " ".join(str(value or "").split())
    if len(text) <= max_len:
        return text
    return text[: max_len - 3].rstrip() + "..."


def _count_by_key(rows: list[dict[str, Any]], key: str) -> dict[str, int]:
    counts: dict[str, int] = {}
    for row in rows:
        value = str(row.get(key) or "unknown")
        counts[value] = counts.get(value, 0) + 1
    return dict(sorted(counts.items()))


def _split_markdown_table_row(line: str) -> list[str]:
    body = line.strip()
    if body.startswith("|"):
        body = body[1:]
    if body.endswith("|"):
        body = body[:-1]
    cells: list[str] = []
    current: list[str] = []
    escaped = False
    for ch in body:
        if escaped:
            current.append(ch)
            escaped = False
            continue
        if ch == "\\":
            escaped = True
            continue
        if ch == "|":
            cells.append("".join(current).strip())
            current = []
            continue
        current.append(ch)
    cells.append("".join(current).strip())
    return cells
