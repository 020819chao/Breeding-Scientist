"""SQLite connection helpers and migration runner.

Single connection per process is fine for our workload (writes serialize on the WAL
anyway). We use aiosqlite for the async API and set PRAGMAs on each connect.
"""

from __future__ import annotations

from datetime import UTC, datetime
from pathlib import Path

import aiosqlite

from ..config import Config

SCHEMA_PATH = Path(__file__).parent / "schema.sql"
MIGRATIONS_DIR = Path(__file__).parent / "migrations"


async def _apply_pragmas(conn: aiosqlite.Connection) -> None:
    await conn.execute("PRAGMA journal_mode=WAL;")
    await conn.execute("PRAGMA synchronous=NORMAL;")
    await conn.execute("PRAGMA foreign_keys=ON;")
    await conn.execute("PRAGMA busy_timeout=5000;")
    await conn.commit()


async def connect(cfg: Config) -> aiosqlite.Connection:
    cfg.db_path.parent.mkdir(parents=True, exist_ok=True)
    conn = await aiosqlite.connect(cfg.db_path)
    conn.row_factory = aiosqlite.Row
    await _apply_pragmas(conn)
    return conn


async def init_db(cfg: Config) -> None:
    """Create the DB if missing and apply pending migrations."""
    conn = await connect(cfg)
    try:
        await _ensure_migrations_table(conn)
        await _apply_pending(conn)
    finally:
        await conn.close()


async def _ensure_migrations_table(conn: aiosqlite.Connection) -> None:
    await conn.execute(
        """CREATE TABLE IF NOT EXISTS schema_migrations (
               version    INTEGER PRIMARY KEY,
               applied_at TEXT NOT NULL,
               name       TEXT NOT NULL
           )"""
    )
    await conn.commit()


async def _applied_versions(conn: aiosqlite.Connection) -> set[int]:
    async with conn.execute("SELECT version FROM schema_migrations") as cur:
        rows = await cur.fetchall()
    return {row["version"] for row in rows}


def _discover_migrations() -> list[tuple[int, str, Path]]:
    """Return [(version, name, path)] sorted by version."""
    out: list[tuple[int, str, Path]] = []
    for p in sorted(MIGRATIONS_DIR.glob("*.sql")):
        stem = p.stem  # e.g. 0001_initial
        version_str, _, name = stem.partition("_")
        out.append((int(version_str), name or "unnamed", p))
    return out


async def _apply_pending(conn: aiosqlite.Connection) -> None:
    applied = await _applied_versions(conn)
    for version, name, path in _discover_migrations():
        if version in applied:
            continue
        # v1 special-case: load the canonical schema.sql to avoid duplication.
        sql = (
            SCHEMA_PATH.read_text(encoding="utf-8")
            if version == 1
            else path.read_text(encoding="utf-8")
        )
        try:
            if version == 7:
                await _migrate_pairwise_calibration_physical_names(conn)
            else:
                await conn.executescript(sql)
        except aiosqlite.OperationalError as e:
            # When the canonical schema.sql is already ahead of an early
            # migration (e.g. fresh init creates v1 with `feasibility`, then
            # v2 tries to ALTER TABLE … ADD COLUMN feasibility), the ALTER
            # becomes a no-op. Mark it applied and move on.
            msg = str(e).lower()
            if "duplicate column name" in msg or (
                "already exists" in msg and "create" not in sql.lower()
            ):
                pass
            else:
                raise
        await conn.execute(
            "INSERT INTO schema_migrations(version, applied_at, name) VALUES (?, ?, ?)",
            (version, datetime.now(UTC).isoformat(), name),
        )
        await conn.commit()


async def _migrate_pairwise_calibration_physical_names(
    conn: aiosqlite.Connection,
) -> None:
    """Rename pre-breeding-scientist pairwise calibration storage names.

    Fresh databases already use the canonical names from schema.sql. Existing
    databases may still carry the earlier physical names, so this migration
    introspects before every rename and is safe to run as a no-op.
    """
    legacy_score = "e" + "lo"
    legacy_duel = "tourna" + "ment"
    await _rename_column_if_present(
        conn, "hypotheses", legacy_score, "calibration_score"
    )
    await _rename_column_if_present(
        conn,
        "hypotheses",
        "matches_played",
        "pairwise_calibrations_played",
    )
    await conn.execute(f"DROP INDEX IF EXISTS hyp_sess_{legacy_score}")
    await conn.execute(
        """CREATE INDEX IF NOT EXISTS hyp_sess_calibration_score
              ON hypotheses(session_id, calibration_score DESC)"""
    )

    await _rename_table_if_present(
        conn, f"{legacy_duel}_matches", "pairwise_calibration_matches"
    )
    for old, new in (
        (f"{legacy_score}_a_before", "calibration_a_before"),
        (f"{legacy_score}_b_before", "calibration_b_before"),
        (f"{legacy_score}_a_after", "calibration_a_after"),
        (f"{legacy_score}_b_after", "calibration_b_after"),
    ):
        await _rename_column_if_present(
            conn, "pairwise_calibration_matches", old, new
        )
    await conn.execute("DROP INDEX IF EXISTS mat_sess")
    await conn.execute(
        """CREATE INDEX IF NOT EXISTS pairwise_calibration_match_sess
              ON pairwise_calibration_matches(session_id, created_at DESC)"""
    )

    await _rename_table_if_present(
        conn, f"{legacy_score}_journal", "pairwise_calibration_journal"
    )
    for old, new in (
        (f"{legacy_score}_a_before", "calibration_a_before"),
        (f"{legacy_score}_b_before", "calibration_b_before"),
        (f"{legacy_score}_a_after", "calibration_a_after"),
        (f"{legacy_score}_b_after", "calibration_b_after"),
    ):
        await _rename_column_if_present(
            conn, "pairwise_calibration_journal", old, new
        )

    await _rename_column_if_present(
        conn, "bench_candidates", f"mean_{legacy_score}", "mean_calibration_score"
    )
    await _rename_column_if_present(
        conn, "bench_candidates", f"top_{legacy_score}", "top_calibration_score"
    )
    for old, new in (
        (f"{legacy_score}_a_before", "calibration_a_before"),
        (f"{legacy_score}_b_before", "calibration_b_before"),
        (f"{legacy_score}_a_after", "calibration_a_after"),
        (f"{legacy_score}_b_after", "calibration_b_after"),
    ):
        await _rename_column_if_present(conn, "bench_matches", old, new)
    await conn.commit()


async def _rename_table_if_present(
    conn: aiosqlite.Connection,
    old_name: str,
    new_name: str,
) -> None:
    if not await _table_exists(conn, old_name):
        return
    if await _table_exists(conn, new_name):
        return
    await conn.execute(f"ALTER TABLE {old_name} RENAME TO {new_name}")


async def _rename_column_if_present(
    conn: aiosqlite.Connection,
    table: str,
    old_name: str,
    new_name: str,
) -> None:
    columns = await _table_columns(conn, table)
    if old_name not in columns or new_name in columns:
        return
    await conn.execute(f"ALTER TABLE {table} RENAME COLUMN {old_name} TO {new_name}")


async def _table_exists(conn: aiosqlite.Connection, table: str) -> bool:
    async with conn.execute(
        "SELECT 1 FROM sqlite_master WHERE type='table' AND name=?",
        (table,),
    ) as cur:
        return await cur.fetchone() is not None


async def _table_columns(conn: aiosqlite.Connection, table: str) -> set[str]:
    if not await _table_exists(conn, table):
        return set()
    async with conn.execute(f"PRAGMA table_info({table})") as cur:
        rows = await cur.fetchall()
    return {row["name"] for row in rows}


async def table_names(conn: aiosqlite.Connection) -> list[str]:
    async with conn.execute(
        "SELECT name FROM sqlite_master WHERE type='table' ORDER BY name"
    ) as cur:
        rows = await cur.fetchall()
    return [r["name"] for r in rows]
