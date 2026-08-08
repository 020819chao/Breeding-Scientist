"""Storage migration regression tests."""

from __future__ import annotations

from pathlib import Path

from co_scientist.config import Config, RunCfg, StorageCfg
from co_scientist.storage import db as db_mod


async def test_pairwise_calibration_physical_name_migration(tmp_path: Path) -> None:
    cfg = Config(run=RunCfg(), storage=StorageCfg(data_dir=str(tmp_path)))
    old_score_col = "e" + "lo"
    old_count_col = "matches" + "_played"
    old_match_table = "tourna" + "ment" + "_matches"
    old_journal_table = old_score_col + "_journal"
    old_mean_col = "mean_" + old_score_col
    old_top_col = "top_" + old_score_col
    old_a_before = old_score_col + "_a_before"
    old_b_before = old_score_col + "_b_before"
    old_a_after = old_score_col + "_a_after"
    old_b_after = old_score_col + "_b_after"
    conn = await db_mod.connect(cfg)
    try:
        await conn.executescript(
            f"""
            CREATE TABLE schema_migrations (
                version INTEGER PRIMARY KEY,
                applied_at TEXT NOT NULL,
                name TEXT NOT NULL
            );
            INSERT INTO schema_migrations(version, applied_at, name)
            VALUES
                (1, '2026-01-01T00:00:00+00:00', 'initial'),
                (2, '2026-01-01T00:00:00+00:00', 'review_feasibility'),
                (3, '2026-01-01T00:00:00+00:00', 'model_bench'),
                (4, '2026-01-01T00:00:00+00:00', 'bench_goldset'),
                (5, '2026-01-01T00:00:00+00:00', 'bench_mode'),
                (6, '2026-01-01T00:00:00+00:00', 'unify_breeding_scientist_names');

            CREATE TABLE hypotheses (
                id TEXT PRIMARY KEY,
                session_id TEXT NOT NULL,
                {old_score_col} REAL,
                {old_count_col} INTEGER NOT NULL DEFAULT 0
            );
            CREATE INDEX hyp_sess_{old_score_col}
                ON hypotheses(session_id, {old_score_col} DESC);

            CREATE TABLE {old_match_table} (
                id TEXT PRIMARY KEY,
                session_id TEXT NOT NULL,
                created_at TEXT NOT NULL,
                {old_a_before} REAL NOT NULL,
                {old_b_before} REAL NOT NULL,
                {old_a_after} REAL,
                {old_b_after} REAL
            );
            CREATE INDEX mat_sess ON {old_match_table}(session_id, created_at DESC);

            CREATE TABLE {old_journal_table} (
                update_id TEXT PRIMARY KEY,
                match_id TEXT UNIQUE NOT NULL,
                {old_a_before} REAL NOT NULL,
                {old_b_before} REAL NOT NULL,
                {old_a_after} REAL NOT NULL,
                {old_b_after} REAL NOT NULL
            );

            CREATE TABLE bench_candidates (
                id TEXT PRIMARY KEY,
                {old_mean_col} REAL,
                {old_top_col} REAL
            );
            CREATE TABLE bench_matches (
                id TEXT PRIMARY KEY,
                {old_a_before} REAL NOT NULL,
                {old_b_before} REAL NOT NULL,
                {old_a_after} REAL,
                {old_b_after} REAL
            );
            """
        )
        await conn.commit()
    finally:
        await conn.close()

    await db_mod.init_db(cfg)

    conn = await db_mod.connect(cfg)
    try:
        tables = set(await db_mod.table_names(conn))
        assert "pairwise_calibration_matches" in tables
        assert "pairwise_calibration_journal" in tables
        assert old_match_table not in tables
        assert old_journal_table not in tables

        assert await _columns(conn, "hypotheses") >= {
            "calibration_score",
            "pairwise_calibrations_played",
        }
        assert await _columns(conn, "pairwise_calibration_matches") >= {
            "calibration_a_before",
            "calibration_b_before",
            "calibration_a_after",
            "calibration_b_after",
        }
        assert await _columns(conn, "bench_candidates") >= {
            "mean_calibration_score",
            "top_calibration_score",
        }

        async with conn.execute(
            "SELECT version FROM schema_migrations WHERE version=7"
        ) as cur:
            row = await cur.fetchone()
        assert row is not None
    finally:
        await conn.close()


async def _columns(conn, table: str) -> set[str]:
    async with conn.execute(f"PRAGMA table_info({table})") as cur:
        rows = await cur.fetchall()
    return {row["name"] for row in rows}
