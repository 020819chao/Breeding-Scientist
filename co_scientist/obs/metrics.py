"""Read-only metrics aggregations for the web UI dashboards.

All counts roll up from existing tables (transcripts, pairwise calibration
tables, etc.) — no separate metrics store. Keep
queries small and indexed.
"""

from __future__ import annotations

import time
from dataclasses import dataclass
from typing import Any

import aiosqlite

from ..models import RANKABLE_HYPOTHESIS_STATES


@dataclass
class SessionMetrics:
    n_calls: int = 0
    input_tokens: int = 0
    output_tokens: int = 0
    cache_read: int = 0
    cache_write: int = 0
    cost_usd: float = 0.0
    cache_hit_ratio: float | None = None
    n_pairwise_calibrations: int = 0
    n_invalid_pairwise_calibrations: int = 0
    n_hypotheses: int = 0
    n_in_calibration_pool: int = 0
    n_reviewed: int = 0
    p50_latency_ms: float | None = None
    p95_latency_ms: float | None = None
    tools_called: int = 0
    tool_errors: int = 0
    dead_tasks: int = 0

async def session_metrics(conn: aiosqlite.Connection, session_id: str) -> SessionMetrics:
    out = SessionMetrics()

    # LLM usage (from transcripts)
    async with conn.execute(
        """SELECT
              COUNT(*)                    AS n_calls,
              COALESCE(SUM(input_tokens),0)  AS input_tokens,
              COALESCE(SUM(output_tokens),0) AS output_tokens,
              COALESCE(SUM(cache_read),0)    AS cache_read,
              COALESCE(SUM(cache_write),0)   AS cache_write,
              COALESCE(SUM(cost_usd),0.0)    AS cost_usd
           FROM transcripts WHERE session_id=?""",
        (session_id,),
    ) as cur:
        row = await cur.fetchone()
    if row is not None:
        out.n_calls = row["n_calls"]
        out.input_tokens = row["input_tokens"]
        out.output_tokens = row["output_tokens"]
        out.cache_read = row["cache_read"]
        out.cache_write = row["cache_write"]
        out.cost_usd = float(row["cost_usd"])
        denom = out.cache_read + out.cache_write + out.input_tokens
        if denom > 0:
            out.cache_hit_ratio = out.cache_read / denom

    # Pairwise calibration checks.
    async with conn.execute(
        """SELECT
              SUM(CASE WHEN mode != 'invalid' THEN 1 ELSE 0 END) AS valid,
              SUM(CASE WHEN mode  = 'invalid' THEN 1 ELSE 0 END) AS invalid
           FROM pairwise_calibration_matches WHERE session_id=?""",
        (session_id,),
    ) as cur:
        row = await cur.fetchone()
    if row is not None:
        out.n_pairwise_calibrations = row["valid"] or 0
        out.n_invalid_pairwise_calibrations = row["invalid"] or 0

    # Hypotheses
    rankable_placeholders = ",".join("?" for _ in RANKABLE_HYPOTHESIS_STATES)
    async with conn.execute(
        f"""SELECT
              COUNT(*) AS total,
              SUM(CASE WHEN state IN ({rankable_placeholders}) THEN 1 ELSE 0 END)
                  AS calibration_pool,
              SUM(CASE WHEN state IN ('reviewed',{rankable_placeholders}) THEN 1 ELSE 0 END)
                  AS reviewed
           FROM hypotheses WHERE session_id=?""",
        (*RANKABLE_HYPOTHESIS_STATES, *RANKABLE_HYPOTHESIS_STATES, session_id),
    ) as cur:
        row = await cur.fetchone()
    if row is not None:
        out.n_hypotheses = row["total"] or 0
        out.n_in_calibration_pool = row["calibration_pool"] or 0
        out.n_reviewed = row["reviewed"] or 0

    # Latency P50/P95 from transcripts (rough approximation using
    # finished_at - started_at parsed by SQLite's julianday function).
    async with conn.execute(
        """SELECT (strftime('%s', finished_at) - strftime('%s', started_at)) * 1000 AS dur_ms
              FROM transcripts WHERE session_id=? ORDER BY dur_ms""",
        (session_id,),
    ) as cur:
        durations = [r["dur_ms"] for r in await cur.fetchall() if r["dur_ms"] is not None]
    if durations:
        out.p50_latency_ms = _percentile(durations, 0.50)
        out.p95_latency_ms = _percentile(durations, 0.95)

    # Tool calls + errors (from events)
    async with conn.execute(
        """SELECT
              SUM(CASE WHEN event='tool_call' THEN 1 ELSE 0 END) AS tools_called,
              SUM(CASE WHEN event='tool_call' AND payload LIKE '%"is_error": true%' THEN 1 ELSE 0 END) AS tool_errors
           FROM events WHERE session_id=?""",
        (session_id,),
    ) as cur:
        row = await cur.fetchone()
    if row is not None:
        out.tools_called = row["tools_called"] or 0
        out.tool_errors = row["tool_errors"] or 0

    # Dead-lettered tasks
    async with conn.execute(
        "SELECT COUNT(*) AS n FROM tasks WHERE session_id=? AND status='dead'",
        (session_id,),
    ) as cur:
        row = await cur.fetchone()
    if row is not None:
        out.dead_tasks = row["n"]

    return out


def _percentile(sorted_values: list[float], p: float) -> float:
    if not sorted_values:
        return 0.0
    i = max(0, min(len(sorted_values) - 1, round(p * (len(sorted_values) - 1))))
    return float(sorted_values[i])


@dataclass
class PrioritizedRouteEntry:
    hypothesis_id: str
    title: str
    calibration_score: float | None
    pairwise_calibrations_played: int

async def prioritized_routes(
    conn: aiosqlite.Connection, session_id: str, k: int = 10
) -> list[PrioritizedRouteEntry]:
    placeholders = ",".join("?" for _ in RANKABLE_HYPOTHESIS_STATES)
    async with conn.execute(
        f"""SELECT id, title,
                  calibration_score,
                  pairwise_calibrations_played
              FROM hypotheses
              WHERE session_id=? AND state IN ({placeholders})
              ORDER BY calibration_score DESC NULLS LAST LIMIT ?""",
        (session_id, *RANKABLE_HYPOTHESIS_STATES, k),
    ) as cur:
        rows = await cur.fetchall()
    return [
        PrioritizedRouteEntry(
            hypothesis_id=r["id"],
            title=r["title"],
            calibration_score=r["calibration_score"],
            pairwise_calibrations_played=r["pairwise_calibrations_played"],
        )
        for r in rows
    ]


# Tiny in-memory cache to dampen UI hot-polling.
_CACHE: dict[str, tuple[float, SessionMetrics]] = {}


async def session_metrics_cached(
    conn: aiosqlite.Connection, session_id: str, *, ttl_s: float = 1.0
) -> SessionMetrics:
    now = time.monotonic()
    hit = _CACHE.get(session_id)
    if hit is not None and now - hit[0] < ttl_s:
        return hit[1]
    m = await session_metrics(conn, session_id)
    _CACHE[session_id] = (now, m)
    return m


def to_dict(m: SessionMetrics) -> dict[str, Any]:
    return {
        "n_calls": m.n_calls,
        "input_tokens": m.input_tokens,
        "output_tokens": m.output_tokens,
        "cache_read": m.cache_read,
        "cache_write": m.cache_write,
        "cost_usd": m.cost_usd,
        "cache_hit_ratio": m.cache_hit_ratio,
        "n_pairwise_calibrations": m.n_pairwise_calibrations,
        "n_invalid_pairwise_calibrations": m.n_invalid_pairwise_calibrations,
        "n_hypotheses": m.n_hypotheses,
        "n_in_calibration_pool": m.n_in_calibration_pool,
        "n_reviewed": m.n_reviewed,
        "p50_latency_ms": m.p50_latency_ms,
        "p95_latency_ms": m.p95_latency_ms,
        "tools_called": m.tools_called,
        "tool_errors": m.tool_errors,
        "dead_tasks": m.dead_tasks,
    }
