from __future__ import annotations

from pathlib import Path

from co_scientist.config import Config, KnowledgeCfg
from co_scientist.knowledge.folder_monitor import KnowledgeFolderMonitor
from co_scientist.tests.unit.test_web_knowledge_intake import _make_batch, _zip_bytes


def _monitor(tmp_path: Path) -> KnowledgeFolderMonitor:
    cfg = Config(
        knowledge=KnowledgeCfg(
            active_catalog=str(tmp_path / "active" / "catalog.json"),
            incoming_dir=str(tmp_path / "incoming"),
            quarantine_dir=str(tmp_path / "quarantine"),
            processed_dir=str(tmp_path / "processed"),
            incoming_watch_enabled=False,
        )
    )
    return KnowledgeFolderMonitor(cfg, stability_seconds=0)


def test_folder_monitor_preflights_to_pending_and_deduplicates(tmp_path: Path) -> None:
    monitor = _monitor(tmp_path)
    monitor.incoming_dir.mkdir(parents=True)
    payload = _zip_bytes(_make_batch(tmp_path))
    (monitor.incoming_dir / "rice.zip").write_bytes(payload)

    events = monitor.scan_once()

    assert events[0]["status"] == "preflight_passed"
    assert events[0]["batch_id"] == "web_test_2026_08_05"
    assert (tmp_path / "pending" / "web_test_2026_08_05" / "audit.json").is_file()
    assert not (tmp_path / "active" / "catalog.json").exists()
    assert list((tmp_path / "processed").glob("*.zip"))

    (monitor.incoming_dir / "duplicate.zip").write_bytes(payload)
    duplicate_events = monitor.scan_once()

    assert duplicate_events[0]["status"] == "duplicate"
    assert list((tmp_path / "quarantine").glob("duplicate_*.zip"))


def test_folder_monitor_quarantines_invalid_zip(tmp_path: Path) -> None:
    monitor = _monitor(tmp_path)
    monitor.incoming_dir.mkdir(parents=True)
    (monitor.incoming_dir / "broken.zip").write_bytes(b"not a zip")

    events = monitor.scan_once()

    assert events[0]["status"] == "quarantined"
    assert list((tmp_path / "quarantine").glob("failed_*.zip"))
    assert list((tmp_path / "quarantine").glob("failed_*.zip.json"))
