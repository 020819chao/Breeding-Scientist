"""Pairwise calibration repository API."""

from __future__ import annotations

import time
from datetime import datetime

import aiosqlite

from ...models import PairwiseCalibrationMatch


async def record_pairwise_calibration(
    conn: aiosqlite.Connection, m: PairwiseCalibrationMatch
) -> bool:
    """Insert the descriptive pairwise calibration row. Idempotent by id."""
    cur = await conn.execute(
        """INSERT OR IGNORE INTO pairwise_calibration_matches(
               id, session_id, created_at, hyp_a, hyp_b, mode, winner,
               calibration_a_before, calibration_b_before,
               calibration_a_after, calibration_b_after,
               rationale, transcript_id, similarity)
           VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?)""",
        (
            m.id, m.session_id, m.created_at.isoformat(),
            m.hyp_a, m.hyp_b, m.mode, m.winner,
            m.calibration_a_before,
            m.calibration_b_before,
            m.calibration_a_after,
            m.calibration_b_after,
            m.rationale, m.transcript_id, m.similarity,
        ),
    )
    ok = cur.rowcount > 0
    await conn.commit()
    return ok


async def apply_pairwise_calibration_update(
    conn: aiosqlite.Connection,
    *,
    match_id: str,
    hyp_a: str,
    hyp_b: str,
    winner: str,
    calibration_a_before: float | None = None,
    calibration_b_before: float | None = None,
    calibration_a_after: float | None = None,
    calibration_b_after: float | None = None,
) -> bool:
    """Apply a pairwise calibration update atomically and idempotently.

    Returns True if the update was newly applied; False if the journal already
    has this match_id (re-run; we skip).
    """
    calibration_a_before = _required_calibration_value(
        calibration_a_before, "calibration_a_before"
    )
    calibration_b_before = _required_calibration_value(
        calibration_b_before, "calibration_b_before"
    )
    calibration_a_after = _required_calibration_value(
        calibration_a_after, "calibration_a_after"
    )
    calibration_b_after = _required_calibration_value(
        calibration_b_after, "calibration_b_after"
    )
    applied_at = int(time.time() * 1000)
    try:
        await conn.execute("BEGIN IMMEDIATE")
        await conn.execute(
            """INSERT INTO pairwise_calibration_journal(
                   update_id, match_id, hyp_a, hyp_b, winner,
                   calibration_a_before, calibration_b_before,
                   calibration_a_after, calibration_b_after, applied_at)
               VALUES (?,?,?,?,?,?,?,?,?,?)""",
            (match_id, match_id, hyp_a, hyp_b, winner,
             calibration_a_before, calibration_b_before,
             calibration_a_after, calibration_b_after, applied_at),
        )
        await conn.execute(
            """UPDATE hypotheses
                  SET calibration_score=?,
                      pairwise_calibrations_played=pairwise_calibrations_played+1
                WHERE id=?""",
            (calibration_a_after, hyp_a),
        )
        await conn.execute(
            """UPDATE hypotheses
                  SET calibration_score=?,
                      pairwise_calibrations_played=pairwise_calibrations_played+1
                WHERE id=?""",
            (calibration_b_after, hyp_b),
        )
        await conn.execute(
            """UPDATE pairwise_calibration_matches
                  SET calibration_a_after=?, calibration_b_after=?
                WHERE id=?""",
            (calibration_a_after, calibration_b_after, match_id),
        )
        await conn.commit()
        return True
    except aiosqlite.IntegrityError:
        await conn.rollback()
        return False


async def count_pairwise_calibrations(
    conn: aiosqlite.Connection, session_id: str
) -> int:
    async with conn.execute(
        """SELECT COUNT(*) AS n FROM pairwise_calibration_matches
             WHERE session_id=? AND mode != 'invalid'""",
        (session_id,),
    ) as cur:
        row = await cur.fetchone()
    return row["n"] if row else 0


async def recent_pairwise_rationales(
    conn: aiosqlite.Connection, session_id: str, limit: int = 50
) -> list[str]:
    async with conn.execute(
        """SELECT rationale FROM pairwise_calibration_matches
              WHERE session_id=? AND rationale IS NOT NULL
              ORDER BY created_at DESC LIMIT ?""",
        (session_id, limit),
    ) as cur:
        rows = await cur.fetchall()
    return [r["rationale"] for r in rows]


def _row_to_match(row: aiosqlite.Row) -> PairwiseCalibrationMatch:
    return PairwiseCalibrationMatch(
        id=row["id"],
        session_id=row["session_id"],
        created_at=datetime.fromisoformat(row["created_at"]),
        hyp_a=row["hyp_a"], hyp_b=row["hyp_b"], mode=row["mode"],
        winner=row["winner"],
        calibration_a_before=row["calibration_a_before"],
        calibration_b_before=row["calibration_b_before"],
        calibration_a_after=row["calibration_a_after"],
        calibration_b_after=row["calibration_b_after"],
        rationale=row["rationale"], transcript_id=row["transcript_id"],
        similarity=row["similarity"],
    )


def _required_calibration_value(
    value: float | None,
    name: str,
) -> float:
    if value is None:
        raise ValueError(f"{name} is required")
    return value


__all__ = [
    "apply_pairwise_calibration_update",
    "count_pairwise_calibrations",
    "recent_pairwise_rationales",
    "record_pairwise_calibration",
]
