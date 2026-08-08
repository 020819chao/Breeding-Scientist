from __future__ import annotations

from pathlib import Path
from types import SimpleNamespace

import pytest

from co_scientist.agents.supervisor import Supervisor
from co_scientist.orchestrator.session_acceptance import (
    AcceptanceCheck,
    SessionAcceptanceReport,
    _canonical_crop,
    _session_started_count,
    write_session_acceptance,
)


def test_canonical_crop_supports_minor_grain_aliases() -> None:
    assert _canonical_crop("Setaria italica") == "foxtail millet"
    assert _canonical_crop("oryza_sativa") == "rice"
    assert _canonical_crop("\u6c34\u7a3b") == "rice"
    assert _canonical_crop("\u8c37\u5b50") == "foxtail millet"
    assert _canonical_crop("\u9ad8\u7cb1") == "sorghum"
    assert _canonical_crop("Panicum miliaceum") == "proso millet"
    assert _canonical_crop("\u7389\u7c73") == "maize"
    assert _canonical_crop("Zea mays") == "maize"
    assert _canonical_crop("managed drought") == "managed drought"


@pytest.mark.parametrize(
    ("alias", "canonical"),
    [
        ("\u5c0f\u9ea6", "wheat"),
        ("Hordeum vulgare", "barley"),
        ("\u71d5\u9ea6", "oat"),
        ("Chenopodium quinoa", "quinoa"),
        ("\u8349\u9ea6", "buckwheat"),
        ("Glycine max", "soybean"),
        ("\u7eff\u8c46", "mung bean"),
        ("Cicer arietinum", "chickpea"),
        ("Arachis hypogaea", "peanut"),
        ("Solanum tuberosum", "potato"),
        ("\u7518\u85af", "sweet potato"),
    ],
)
def test_canonical_crop_supports_common_crop_aliases(alias: str, canonical: str) -> None:
    assert _canonical_crop(alias) == canonical


def test_canonical_crop_does_not_use_unsafe_substring_matching() -> None:
    assert _canonical_crop("ricebean") == "ricebean"
    assert _canonical_crop("cornflower") == "cornflower"
    assert _canonical_crop("maizeflower") == "maizeflower"
    assert _canonical_crop("setaria_like") == "setaria like"
    assert _canonical_crop("rice and maize") == "rice and maize"


def test_session_started_count_reads_initial_count() -> None:
    events = [
        {"event": "other", "payload": "{}"},
        {"event": "session_started", "payload": '{"n_initial": 3}'},
    ]
    assert _session_started_count(events) == 3


def test_write_session_acceptance_persists_machine_readable_result(tmp_path) -> None:
    report = SessionAcceptanceReport(
        session_id="ses_test",
        status="pass",
        checks=(AcceptanceCheck("final_report", "pass", "ok"),),
    )
    path = write_session_acceptance(SimpleNamespace(data_dir=tmp_path), report)

    assert path == tmp_path / "artifacts" / "ses_test" / "final" / "session_acceptance.json"
    assert '"status": "pass"' in path.read_text(encoding="utf-8")


@pytest.mark.asyncio
async def test_new_session_freezes_knowledge_snapshot(tmp_cfg, conn) -> None:
    session = await Supervisor(tmp_cfg)._create_session(
        conn,
        "Improve rice drought recovery",
        None,
        60,
    )

    snapshot = session.config_snapshot["knowledge_snapshot"]
    assert snapshot["snapshot_id"].startswith("kb_")
    assert Path(snapshot["runtime_catalog_path"]).is_file()
    assert Path(snapshot["runtime_root"]).is_dir()
    assert (tmp_cfg.data_dir / "artifacts" / session.id / "meta" / "knowledge_snapshot.json").is_file()
