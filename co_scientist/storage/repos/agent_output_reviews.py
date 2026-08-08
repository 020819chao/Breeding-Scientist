"""Mentor review repository for six-agent output artifacts."""

from __future__ import annotations

import aiosqlite

from ...models import AgentOutputReview


async def insert(conn: aiosqlite.Connection, review: AgentOutputReview) -> None:
    await conn.execute(
        """INSERT INTO agent_output_reviews(
               id, session_id, created_at, agent, output_key, output_path,
               target_id, status, reviewer, note)
           VALUES (?,?,?,?,?,?,?,?,?,?)""",
        (
            review.id,
            review.session_id,
            review.created_at.isoformat(),
            review.agent,
            review.output_key,
            review.output_path,
            review.target_id,
            review.status,
            review.reviewer,
            review.note,
        ),
    )
    await conn.commit()


async def list_for_session(
    conn: aiosqlite.Connection,
    session_id: str,
) -> list[AgentOutputReview]:
    async with conn.execute(
        """SELECT * FROM agent_output_reviews
             WHERE session_id=?
             ORDER BY created_at DESC""",
        (session_id,),
    ) as cur:
        rows = await cur.fetchall()
    return [_row_to_review(row) for row in rows]


async def latest_for_session(
    conn: aiosqlite.Connection,
    session_id: str,
) -> dict[str, AgentOutputReview]:
    reviews = await list_for_session(conn, session_id)
    latest: dict[str, AgentOutputReview] = {}
    for review in reviews:
        latest.setdefault(review.output_key, review)
    return latest


def _row_to_review(row: aiosqlite.Row) -> AgentOutputReview:
    from datetime import datetime

    return AgentOutputReview(
        id=row["id"],
        session_id=row["session_id"],
        created_at=datetime.fromisoformat(row["created_at"]),
        agent=row["agent"],
        output_key=row["output_key"],
        output_path=row["output_path"],
        target_id=row["target_id"],
        status=row["status"],
        reviewer=row["reviewer"],
        note=row["note"] or "",
    )
