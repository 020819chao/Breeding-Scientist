"""Controlled incoming-folder monitor for knowledge-batch preflight."""

from __future__ import annotations

import asyncio
import contextlib
import hashlib
import json
import shutil
import time
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path
from typing import Any
from uuid import uuid4

from .intake import import_knowledge_batch
from .versions import load_batch_history, save_pending_batch
from .web_intake import extract_batch_zip


@dataclass
class _Observation:
    size: int
    mtime_ns: int
    first_seen: float


class KnowledgeFolderMonitor:
    """Watch an incoming directory and convert stable ZIPs into pending batches.

    The monitor never activates a batch. It only performs the same validated
    preflight used by the web upload and places successful packages in the
    existing pending-review area.
    """

    def __init__(
        self,
        cfg: Any,
        *,
        interval_seconds: float | None = None,
        stability_seconds: float | None = None,
    ) -> None:
        self.cfg = cfg
        self.incoming_dir = Path(cfg.knowledge_incoming_path).resolve()
        self.quarantine_dir = Path(cfg.knowledge_quarantine_path).resolve()
        self.processed_dir = Path(cfg.knowledge_processed_path).resolve()
        self.active_root = Path(cfg.active_knowledge_catalog_path).resolve().parent
        self.work_dir = self.active_root.parent / "monitor_work"
        self.state_path = self.active_root.parent / "incoming_monitor_state.json"
        self.interval_seconds = (
            float(interval_seconds)
            if interval_seconds is not None
            else float(cfg.knowledge.incoming_watch_interval_seconds)
        )
        self.stability_seconds = (
            float(stability_seconds)
            if stability_seconds is not None
            else float(cfg.knowledge.incoming_stability_seconds)
        )
        self._observations: dict[str, _Observation] = {}
        self._stop_event = asyncio.Event()
        self._status: dict[str, Any] = {
            "enabled": bool(cfg.knowledge.incoming_watch_enabled),
            "running": False,
            "last_scan_at": None,
            "last_event": None,
            "last_error": None,
            "processed_count": 0,
            "quarantined_count": 0,
        }
        self._load_state()

    async def run_forever(self) -> None:
        self.incoming_dir.mkdir(parents=True, exist_ok=True)
        self._status["running"] = True
        self._write_status()
        try:
            while not self._stop_event.is_set():
                await asyncio.to_thread(self.scan_once)
                with contextlib.suppress(TimeoutError):
                    await asyncio.wait_for(self._stop_event.wait(), timeout=self.interval_seconds)
        finally:
            self._status["running"] = False
            self._write_status()

    def stop(self) -> None:
        self._stop_event.set()

    def scan_once(self) -> list[dict[str, Any]]:
        """Process stable ZIPs once and return per-file events."""

        self.incoming_dir.mkdir(parents=True, exist_ok=True)
        events: list[dict[str, Any]] = []
        now = time.time()
        for path in sorted(self.incoming_dir.glob("*.zip")):
            if not path.is_file():
                continue
            if not self._is_stable(path, now):
                continue
            try:
                events.append(self._process_zip(path))
            except Exception as exc:  # quarantine must protect the monitor loop
                event = self._quarantine(path, str(exc))
                events.append(event)
                self._status["last_error"] = str(exc)
        self._status["last_scan_at"] = datetime.now(UTC).isoformat()
        if events:
            self._status["last_event"] = events[-1]
        self._write_status()
        return events

    def status(self) -> dict[str, Any]:
        payload = dict(self._status)
        payload["incoming_dir"] = str(self.incoming_dir)
        payload["quarantine_dir"] = str(self.quarantine_dir)
        payload["processed_dir"] = str(self.processed_dir)
        payload["incoming_count"] = len(list(self.incoming_dir.glob("*.zip"))) if self.incoming_dir.is_dir() else 0
        payload["pending_count"] = len(list((self.active_root.parent / "pending").glob("*/audit.json"))) if (self.active_root.parent / "pending").is_dir() else 0
        return payload

    def dashboard(self) -> dict[str, Any]:
        """Return a UI-ready snapshot of all monitor queues."""

        return {
            "status": self.status(),
            "incoming": self._file_rows(self.incoming_dir),
            "pending": [
                row for row in load_batch_history(self.cfg) if row.get("is_pending")
            ],
            "processed": self._file_rows(self.processed_dir),
            "quarantine": self._quarantine_rows(),
        }

    def retry_quarantined(self, filename: str) -> Path:
        """Return a failed ZIP to incoming for another preflight attempt."""

        root = self.quarantine_dir.resolve()
        candidate = (root / filename).resolve()
        candidate.relative_to(root)
        if not candidate.is_file() or not candidate.name.startswith("failed_") or candidate.suffix.lower() != ".zip":
            raise ValueError("only failed ZIP packages can be retried")
        return self._move_with_suffix(candidate, self.incoming_dir, "retry")

    def _file_rows(self, root: Path) -> list[dict[str, Any]]:
        if not root.is_dir():
            return []
        rows = []
        for path in sorted(root.iterdir(), key=lambda item: item.stat().st_mtime, reverse=True):
            if not path.is_file() or path.suffix.lower() != ".zip":
                continue
            stat = path.stat()
            rows.append(
                {
                    "filename": path.name,
                    "size": stat.st_size,
                    "updated_at": datetime.fromtimestamp(stat.st_mtime, UTC).isoformat(),
                }
            )
        return rows[:100]

    def _quarantine_rows(self) -> list[dict[str, Any]]:
        rows = self._file_rows(self.quarantine_dir)
        for row in rows:
            reason_path = self.quarantine_dir / f"{row['filename']}.json"
            try:
                reason = json.loads(reason_path.read_text(encoding="utf-8"))
            except (OSError, ValueError):
                reason = {}
            row["reason"] = reason.get("reason", "")
        return rows

    def _process_zip(self, path: Path) -> dict[str, Any]:
        digest = _sha256(path)
        state = self._load_state()
        processed_hashes = state.setdefault("processed_hashes", {})
        if digest in processed_hashes:
            destination = self._move_with_suffix(path, self.quarantine_dir, "duplicate")
            reason_path = destination.with_suffix(destination.suffix + ".json")
            reason_path.write_text(
                json.dumps(
                    {"reason": "duplicate_content_hash", "sha256": digest, "original": processed_hashes[digest]},
                    ensure_ascii=False,
                    indent=2,
                ),
                encoding="utf-8",
            )
            self._status["quarantined_count"] += 1
            return {"filename": path.name, "status": "duplicate", "sha256": digest}

        job_dir = self.work_dir / f"scan_{uuid4().hex[:12]}"
        extract_dir = job_dir / "extracted"
        self.work_dir.mkdir(parents=True, exist_ok=True)
        try:
            batch_dir = extract_batch_zip(path, extract_dir)
            manifest = json.loads((batch_dir / "manifest.json").read_text(encoding="utf-8"))
            imported = import_knowledge_batch(
                batch_dir,
                active_root=self.active_root,
                catalog_path=Path(self.cfg.active_knowledge_catalog_path),
                dry_run=True,
            )
            pending = save_pending_batch(
                self.active_root,
                batch_dir,
                batch_id=imported.batch_id,
                crop_scope=list(manifest.get("crop_scope") or []),
                stats=imported.stats,
                source_filename=path.name,
            )
            processed = self._move_with_suffix(path, self.processed_dir, "processed")
            processed_hashes[digest] = str(processed)
            state["processed_hashes"] = processed_hashes
            self._save_state(state)
            self._status["processed_count"] += 1
            return {
                "filename": path.name,
                "status": "preflight_passed",
                "batch_id": imported.batch_id,
                "pending_path": str(pending),
                "sha256": digest,
            }
        finally:
            if job_dir.exists():
                shutil.rmtree(job_dir, ignore_errors=True)

    def _quarantine(self, path: Path, reason: str) -> dict[str, Any]:
        digest = _sha256(path) if path.is_file() else ""
        if path.is_file():
            destination = self._move_with_suffix(path, self.quarantine_dir, "failed")
        else:
            destination = self.quarantine_dir / f"missing_{path.name}"
            self.quarantine_dir.mkdir(parents=True, exist_ok=True)
        destination.with_suffix(destination.suffix + ".json").write_text(
            json.dumps(
                {"reason": reason, "sha256": digest, "source": path.name, "quarantined_at": datetime.now(UTC).isoformat()},
                ensure_ascii=False,
                indent=2,
            ),
            encoding="utf-8",
        )
        self._status["quarantined_count"] += 1
        return {"filename": path.name, "status": "quarantined", "reason": reason, "sha256": digest}

    def _is_stable(self, path: Path, now: float) -> bool:
        stat = path.stat()
        key = str(path)
        previous = self._observations.get(key)
        if previous is None or (previous.size, previous.mtime_ns) != (stat.st_size, stat.st_mtime_ns):
            self._observations[key] = _Observation(stat.st_size, stat.st_mtime_ns, now)
            return self.stability_seconds <= 0
        return now - previous.first_seen >= self.stability_seconds

    def _move_with_suffix(self, source: Path, root: Path, prefix: str) -> Path:
        root.mkdir(parents=True, exist_ok=True)
        destination = root / f"{prefix}_{source.name}"
        index = 2
        while destination.exists():
            destination = root / f"{prefix}_{index}_{source.name}"
            index += 1
        shutil.move(str(source), str(destination))
        self._observations.pop(str(source), None)
        return destination

    def _load_state(self) -> dict[str, Any]:
        if not self.state_path.is_file():
            return {"processed_hashes": {}}
        try:
            payload = json.loads(self.state_path.read_text(encoding="utf-8"))
        except (OSError, ValueError):
            return {"processed_hashes": {}}
        return payload if isinstance(payload, dict) else {"processed_hashes": {}}

    def _save_state(self, payload: dict[str, Any]) -> None:
        self.state_path.parent.mkdir(parents=True, exist_ok=True)
        temporary = self.state_path.with_name(f".{self.state_path.name}.tmp")
        temporary.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
        temporary.replace(self.state_path)

    def _write_status(self) -> None:
        self._status["status_path"] = str(self.active_root.parent / "incoming_monitor_status.json")
        path = Path(self._status["status_path"])
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(json.dumps(self.status(), ensure_ascii=False, indent=2), encoding="utf-8")


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


__all__ = ["KnowledgeFolderMonitor"]
