"""Deterministic acceptance gate for completed breeding-scientist sessions.

The gate is deliberately model-free. It checks the durable outputs and routing
metadata that must be true before a session is treated as scientifically usable.
"""

from __future__ import annotations

import json
import re
from dataclasses import dataclass
from pathlib import Path
from typing import Any
from urllib.error import URLError
from urllib.request import urlopen

from ..config import Config
from ..knowledge.crop_taxonomy import canonical_crop
from ..knowledge.snapshot import verify_knowledge_snapshot
from ..storage import db as db_mod

FORBIDDEN_RUNTIME_NAMES = ("generation", "reflection", "ranking", "proximity")
EXPECTED_TASK_AGENTS = {
    "evidence_curator",
    "breeding_designer",
    "validation_planner",
    "risk_reviewer",
    "iteration_orchestrator",
}


@dataclass(frozen=True)
class AcceptanceCheck:
    """One named gate result."""

    name: str
    status: str
    message: str

    @property
    def ok(self) -> bool:
        return self.status != "fail"

    def as_dict(self) -> dict[str, str]:
        return {"name": self.name, "status": self.status, "message": self.message}


@dataclass(frozen=True)
class SessionAcceptanceReport:
    """Serializable result returned by the CLI and suitable for CI."""

    session_id: str
    status: str
    checks: tuple[AcceptanceCheck, ...]

    def as_dict(self) -> dict[str, Any]:
        return {
            "session_id": self.session_id,
            "status": self.status,
            "checks": [check.as_dict() for check in self.checks],
            "failed_checks": [check.name for check in self.checks if check.status == "fail"],
        }


async def run_session_acceptance(
    cfg: Config,
    session_id: str,
    *,
    check_web: bool = False,
    web_base_url: str | None = None,
) -> SessionAcceptanceReport:
    """Run all deterministic acceptance checks for one session."""

    snapshot = await _load_snapshot(cfg, session_id)
    checks = _evaluate_snapshot(cfg, snapshot)
    if check_web:
        checks.append(_check_web_routes(cfg, session_id, web_base_url=web_base_url))
    else:
        checks.append(
            AcceptanceCheck("web_routes", "skip", "skipped; pass --check-web to probe the local UI")
        )
    status = "pass" if all(check.status != "fail" for check in checks) else "fail"
    return SessionAcceptanceReport(session_id=session_id, status=status, checks=tuple(checks))


async def _load_snapshot(cfg: Config, session_id: str) -> dict[str, Any]:
    conn = await db_mod.connect(cfg)
    try:
        async with conn.execute("SELECT * FROM sessions WHERE id=?", (session_id,)) as cur:
            session = await cur.fetchone()
        async with conn.execute(
            "SELECT agent, action, payload, status FROM tasks WHERE session_id=? ORDER BY created_at",
            (session_id,),
        ) as cur:
            tasks = [dict(row) for row in await cur.fetchall()]
        async with conn.execute(
            "SELECT agent, event, payload FROM events WHERE session_id=? ORDER BY ts",
            (session_id,),
        ) as cur:
            events = [dict(row) for row in await cur.fetchall()]
        async with conn.execute(
            "SELECT agent FROM transcripts WHERE session_id=?",
            (session_id,),
        ) as cur:
            transcript_agents = [row["agent"] for row in await cur.fetchall()]
        async with conn.execute(
            "SELECT id FROM hypotheses WHERE session_id=? ORDER BY created_at",
            (session_id,),
        ) as cur:
            hypotheses = [row["id"] for row in await cur.fetchall()]
    finally:
        await conn.close()

    if session is None:
        return {"missing": True, "session_id": session_id}
    return {
        "missing": False,
        "session": dict(session),
        "tasks": tasks,
        "events": events,
        "transcript_agents": transcript_agents,
        "hypotheses": hypotheses,
        "knowledge_snapshot": _json_object(session["config_snapshot"]).get("knowledge_snapshot"),
        "config": cfg,
    }


def _evaluate_snapshot(cfg: Config, snapshot: dict[str, Any]) -> list[AcceptanceCheck]:
    if snapshot.get("missing"):
        return [AcceptanceCheck("session_exists", "fail", "session was not found")]

    session = snapshot["session"]
    tasks = snapshot["tasks"]
    events = snapshot["events"]
    plan = _json_object(session.get("research_plan"))
    crop = _canonical_crop(plan.get("crop") or plan.get("domain_hint") or session.get("research_goal"))
    checks = [
        _check_session_status(session, tasks),
        _check_goal_and_crop(plan, crop),
        _check_knowledge_snapshot(cfg, snapshot.get("knowledge_snapshot")),
        _check_six_agent_runtime(tasks, events, snapshot["transcript_agents"]),
        _check_hypothesis_loop(cfg, plan, events, snapshot["hypotheses"]),
    ]

    artifact_root = cfg.data_dir / "artifacts" / session["id"]
    packages = _load_json_files(artifact_root / "evidence", "package_*.json")
    expected_snapshot_id = (
        snapshot.get("knowledge_snapshot", {}).get("snapshot_id")
        if isinstance(snapshot.get("knowledge_snapshot"), dict)
        else None
    )
    checks.append(_check_evidence_packages(packages, crop, expected_snapshot_id))
    checks.append(_check_graph(artifact_root / "evidence" / "breeding_evidence_graph.json", crop))
    checks.append(_check_final_report(artifact_root, session.get("final_overview")))
    return checks


def _check_session_status(session: dict[str, Any], tasks: list[dict[str, Any]]) -> AcceptanceCheck:
    status = str(session.get("status") or "")
    unfinished = [task for task in tasks if task.get("status") not in {"done", "cancelled"}]
    if status != "done":
        return AcceptanceCheck("session_status", "fail", f"status={status or 'unknown'}; expected done")
    if unfinished:
        states = sorted({str(task.get("status")) for task in unfinished})
        return AcceptanceCheck("session_status", "fail", f"unfinished task states: {', '.join(states)}")
    return AcceptanceCheck("session_status", "pass", f"done; {len(tasks)} queued tasks completed")


def _check_goal_and_crop(plan: dict[str, Any], crop: str | None) -> AcceptanceCheck:
    if not plan.get("objective"):
        return AcceptanceCheck("goal_and_crop", "fail", "research plan has no objective")
    if not crop:
        return AcceptanceCheck("goal_and_crop", "fail", "research plan has no recognized crop")
    return AcceptanceCheck("goal_and_crop", "pass", f"objective present; crop={crop}")


def _check_knowledge_snapshot(cfg: Config, snapshot: Any) -> AcceptanceCheck:
    if not isinstance(snapshot, dict) or not snapshot.get("snapshot_id"):
        return AcceptanceCheck(
            "knowledge_snapshot",
            "skip",
            "legacy session has no knowledge snapshot; new sessions are version-bound",
        )
    ok, message = verify_knowledge_snapshot(cfg, snapshot)
    return AcceptanceCheck("knowledge_snapshot", "pass" if ok else "fail", message)


def _check_six_agent_runtime(
    tasks: list[dict[str, Any]],
    events: list[dict[str, Any]],
    transcript_agents: list[str],
) -> AcceptanceCheck:
    task_agents = {str(task.get("agent") or "").strip().lower() for task in tasks}
    missing = sorted(EXPECTED_TASK_AGENTS - task_agents)
    goal_seen = any(
        str(agent or "").lower() == "goal_interpreter"
        for agent in transcript_agents
    ) or any(
        "goal_interpreter" in json.dumps(event, ensure_ascii=False).lower()
        for event in events
    )
    forbidden_hits: set[str] = set()
    for row in [*tasks, *events]:
        text = json.dumps(row, ensure_ascii=False).lower()
        forbidden_hits.update(
            name
            for name in FORBIDDEN_RUNTIME_NAMES
            if re.search(rf"(?<![a-z]){re.escape(name)}(?![a-z])", text)
        )
    if missing or not goal_seen or forbidden_hits:
        details = []
        if missing:
            details.append(f"missing={','.join(missing)}")
        if not goal_seen:
            details.append("Goal Interpreter not recorded")
        if forbidden_hits:
            details.append(f"legacy names={','.join(sorted(forbidden_hits))}")
        return AcceptanceCheck("six_agent_runtime", "fail", "; ".join(details))
    return AcceptanceCheck(
        "six_agent_runtime",
        "pass",
        "Goal Interpreter plus five executable agents; no legacy runtime names",
    )


def _check_hypothesis_loop(
    cfg: Config,
    plan: dict[str, Any],
    events: list[dict[str, Any]],
    hypothesis_ids: list[str],
) -> AcceptanceCheck:
    initial = plan.get("initial_hypothesis_count")
    if not isinstance(initial, int):
        initial = _session_started_count(events)
    final = len(hypothesis_ids)
    configured_max = plan.get("max_hypothesis_count")
    maximum = configured_max if isinstance(configured_max, int) else cfg.run.max_ideas
    iteration_events = sum(
        1
        for event in events
        if str(event.get("agent") or "").lower() == "iteration_orchestrator"
        or "iteration_orchestrator" in str(event.get("payload") or "").lower()
    )
    if not isinstance(initial, int) or initial < 1:
        return AcceptanceCheck("hypothesis_loop", "fail", "initial hypothesis count is missing or invalid")
    if final < initial or final < 1:
        return AcceptanceCheck("hypothesis_loop", "fail", f"initial={initial}, final={final}; final count regressed")
    if final > maximum:
        return AcceptanceCheck("hypothesis_loop", "fail", f"final={final} exceeds max={maximum}")
    if iteration_events == 0:
        return AcceptanceCheck("hypothesis_loop", "fail", "no Iteration Orchestrator activity recorded")
    expansion = "expanded" if final > initial else "held"
    return AcceptanceCheck(
        "hypothesis_loop",
        "pass",
        f"initial={initial}, final={final}, max={maximum}; loop {expansion}; iteration activity={iteration_events}",
    )


def _check_evidence_packages(
    packages: list[dict[str, Any]],
    crop: str | None,
    expected_snapshot_id: str | None,
) -> AcceptanceCheck:
    if not packages:
        return AcceptanceCheck("evidence_packages", "fail", "no evidence package artifacts found")
    if not crop:
        return AcceptanceCheck("evidence_packages", "fail", "cannot validate package scope without crop")

    scopes: list[str] = []
    document_sources: dict[str, set[str]] = {}
    rag_results = 0
    for package in packages:
        if expected_snapshot_id and package.get("knowledge_snapshot_id") != expected_snapshot_id:
            return AcceptanceCheck(
                "evidence_packages",
                "fail",
                "evidence package is not bound to the Session knowledge snapshot",
            )
        for section_name, scope_key in (
            ("local_germplasm", "crop"),
            ("local_crop_kg", "crop_scope"),
            ("local_rag", "crop_scope"),
            ("local_marker_qtl", "crop"),
            ("local_phenotype_protocols", "crop"),
            ("local_field_trials", "crop"),
        ):
            section = package.get(section_name) or {}
            results = section.get("results") or []
            for result in results:
                scope = _canonical_crop(result.get(scope_key))
                if scope:
                    scopes.append(scope)
                else:
                    return AcceptanceCheck(
                        "evidence_packages",
                        "fail",
                        f"{section_name} contains a result without explicit crop scope",
                    )
        for result in (package.get("local_rag") or {}).get("results") or []:
            rag_results += 1
            document_id = str(result.get("document_id") or result.get("source_path") or "").strip()
            source_path = str(result.get("source_path") or result.get("source") or "").strip()
            if document_id:
                document_sources.setdefault(document_id, set()).add(source_path)

    foreign = sorted({scope for scope in scopes if scope != crop})
    if foreign:
        return AcceptanceCheck("evidence_packages", "fail", f"foreign crop scopes detected: {', '.join(foreign)}")
    duplicates = sorted(key for key, sources in document_sources.items() if len(sources) > 1)
    if duplicates:
        return AcceptanceCheck("evidence_packages", "fail", f"duplicate RAG document IDs across sources: {', '.join(duplicates[:3])}")
    if not scopes:
        return AcceptanceCheck("evidence_packages", "fail", "evidence results have no crop scopes")
    return AcceptanceCheck(
        "evidence_packages",
        "pass",
        f"{len(packages)} packages; {len(scopes)} scoped evidence records; {rag_results} RAG results; no cross-crop or document duplicates"
        + (f"; snapshot={expected_snapshot_id}" if expected_snapshot_id else ""),
    )


def _check_graph(path: Path, crop: str | None) -> AcceptanceCheck:
    if not path.exists():
        return AcceptanceCheck("evidence_graph", "fail", "breeding_evidence_graph.json is missing")
    graph = _read_json(path)
    if not isinstance(graph, dict):
        return AcceptanceCheck("evidence_graph", "fail", "graph artifact is not a JSON object")
    nodes = graph.get("nodes") or []
    edges = graph.get("edges") or []
    if graph.get("node_count") != len(nodes) or graph.get("edge_count") != len(edges):
        return AcceptanceCheck("evidence_graph", "fail", "stored node/edge counts do not match graph contents")
    if crop:
        graph_scopes = []
        for node in nodes:
            if node.get("type") == "crop" or node.get("type") == "rag_evidence":
                scope = _canonical_crop(node.get("label") if node.get("type") == "crop" else node.get("crop_scope"))
                if scope:
                    graph_scopes.append(scope)
        foreign = sorted({scope for scope in graph_scopes if scope != crop})
        if foreign:
            return AcceptanceCheck("evidence_graph", "fail", f"foreign graph crop scopes detected: {', '.join(foreign)}")
    return AcceptanceCheck("evidence_graph", "pass", f"consistent graph: {len(nodes)} nodes, {len(edges)} edges")


def _check_final_report(artifact_root: Path, final_overview: str | None) -> AcceptanceCheck:
    overview_path = _resolve_artifact_path(artifact_root.parent.parent, final_overview)
    audit_path = artifact_root / "final" / "overview_audit.json"
    if not overview_path or not overview_path.exists():
        return AcceptanceCheck("final_report", "fail", "final overview is missing")
    if not audit_path.exists():
        return AcceptanceCheck("final_report", "fail", "overview_audit.json is missing")
    audit = _read_json(audit_path)
    records = [audit] if isinstance(audit, dict) and "status" in audit else [value for value in (audit.values() if isinstance(audit, dict) else []) if isinstance(value, dict)]
    if not records or any(record.get("status") != "pass" or record.get("missing_sections") for record in records):
        return AcceptanceCheck("final_report", "fail", "final report audit is not pass")
    return AcceptanceCheck("final_report", "pass", "overview and report audit are present and pass")


def _check_web_routes(cfg: Config, session_id: str, *, web_base_url: str | None) -> AcceptanceCheck:
    base = (web_base_url or f"http://{cfg.web_ui.host}:{cfg.web_ui.port}").rstrip("/")
    paths = (f"/sessions/{session_id}", f"/sessions/{session_id}/evidence-graph", f"/sessions/{session_id}/overview")
    failed: list[str] = []
    for path in paths:
        try:
            with urlopen(base + path, timeout=3) as response:
                if response.status != 200:
                    failed.append(f"{path}={response.status}")
        except (OSError, URLError) as exc:
            failed.append(f"{path}={exc.__class__.__name__}")
    if failed:
        return AcceptanceCheck("web_routes", "fail", "; ".join(failed))
    return AcceptanceCheck("web_routes", "pass", f"HTTP 200 for {len(paths)} session pages")


def _session_started_count(events: list[dict[str, Any]]) -> int | None:
    for event in events:
        if event.get("event") != "session_started":
            continue
        payload = _json_object(event.get("payload"))
        value = payload.get("n_initial")
        if isinstance(value, int):
            return value
    return None


def _load_json_files(directory: Path, pattern: str) -> list[dict[str, Any]]:
    return [_read_json(path) for path in sorted(directory.glob(pattern)) if isinstance(_read_json(path), dict)]


def _read_json(path: Path) -> Any:
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return None


def _json_object(value: Any) -> dict[str, Any]:
    if isinstance(value, dict):
        return value
    if isinstance(value, str):
        try:
            parsed = json.loads(value)
        except json.JSONDecodeError:
            return {}
        return parsed if isinstance(parsed, dict) else {}
    return {}


def _resolve_artifact_path(data_dir: Path, relative_path: str | None) -> Path | None:
    if not relative_path:
        return None
    path = Path(relative_path)
    return path if path.is_absolute() else data_dir / path


def _canonical_crop(value: Any) -> str | None:
    return canonical_crop(value)


def acceptance_report_json(report: SessionAcceptanceReport) -> str:
    """Return stable, pretty JSON for callers outside Typer."""

    return json.dumps(report.as_dict(), ensure_ascii=False, indent=2)


def write_session_acceptance(cfg: Config, report: SessionAcceptanceReport) -> Path:
    """Persist a completed acceptance result under the session final artifacts."""

    path = cfg.data_dir / "artifacts" / report.session_id / "final" / "session_acceptance.json"
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(acceptance_report_json(report), encoding="utf-8")
    return path


__all__ = [
    "AcceptanceCheck",
    "SessionAcceptanceReport",
    "acceptance_report_json",
    "run_session_acceptance",
    "write_session_acceptance",
]
