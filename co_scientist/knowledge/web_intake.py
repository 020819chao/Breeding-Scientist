"""Safe helpers for importing knowledge batches uploaded through the web UI."""

from __future__ import annotations

import json
import shutil
import zipfile
from pathlib import Path
from typing import Any

MAX_UPLOAD_BYTES = 50 * 1024 * 1024
MAX_EXTRACTED_BYTES = 250 * 1024 * 1024
MAX_EXTRACTED_FILES = 2000


def save_uploaded_zip(uploaded_file: Any, destination: Path) -> int:
    """Stream an UploadFile-like object to disk and enforce a compressed-size limit."""

    destination.parent.mkdir(parents=True, exist_ok=True)
    total = 0
    with destination.open("wb") as stream:
        while True:
            chunk = uploaded_file.file.read(1024 * 1024)
            if not chunk:
                break
            total += len(chunk)
            if total > MAX_UPLOAD_BYTES:
                stream.close()
                destination.unlink(missing_ok=True)
                raise ValueError(f"上传文件超过 {MAX_UPLOAD_BYTES // (1024 * 1024)} MB 限制")
            stream.write(chunk)
    return total


def extract_batch_zip(zip_path: Path, destination: Path) -> Path:
    """Extract a batch ZIP while rejecting traversal, links, and zip bombs."""

    destination = destination.resolve()
    if destination.exists():
        shutil.rmtree(destination)
    destination.mkdir(parents=True, exist_ok=True)
    extracted_bytes = 0
    extracted_files = 0
    try:
        with zipfile.ZipFile(zip_path) as archive:
            members = archive.infolist()
            if not members:
                raise ValueError("上传 ZIP 为空")
            for member in members:
                name = member.filename.replace("\\", "/")
                member_path = Path(name)
                if not name or member_path.is_absolute() or ".." in member_path.parts:
                    raise ValueError(f"ZIP 包含不安全路径: {member.filename}")
                mode = (member.external_attr >> 16) & 0o170000
                if mode == 0o120000:
                    raise ValueError(f"ZIP 不允许包含符号链接: {member.filename}")
                if member.is_dir():
                    continue
                extracted_files += 1
                extracted_bytes += member.file_size
                if extracted_files > MAX_EXTRACTED_FILES:
                    raise ValueError(f"ZIP 文件数量超过 {MAX_EXTRACTED_FILES} 个限制")
                if extracted_bytes > MAX_EXTRACTED_BYTES:
                    raise ValueError(
                        f"ZIP 解压后超过 {MAX_EXTRACTED_BYTES // (1024 * 1024)} MB 限制"
                    )
                target = (destination / member_path).resolve()
                target.relative_to(destination)
                target.parent.mkdir(parents=True, exist_ok=True)
                with archive.open(member) as source, target.open("wb") as stream:
                    shutil.copyfileobj(source, stream, length=1024 * 1024)
    except (KeyError, OSError, zipfile.BadZipFile) as exc:
        shutil.rmtree(destination, ignore_errors=True)
        if isinstance(exc, zipfile.BadZipFile):
            raise ValueError("上传文件不是有效的 ZIP 压缩包") from exc
        raise ValueError(f"解压上传批次失败: {exc}") from exc
    except Exception:
        shutil.rmtree(destination, ignore_errors=True)
        raise

    manifest = destination / "manifest.json"
    if manifest.is_file():
        return destination
    candidates = [path.parent for path in destination.rglob("manifest.json")]
    if len(candidates) == 1:
        return candidates[0]
    if not candidates:
        raise ValueError("ZIP 中没有找到 manifest.json")
    raise ValueError("ZIP 中找到多个 manifest.json, 无法确定批次根目录")


def active_root_from_config(cfg: Any) -> Path:
    """Resolve the active knowledge directory beside the configured catalog."""

    return Path(cfg.active_knowledge_catalog_path).resolve().parent


def catalog_summary(cfg: Any) -> dict[str, Any]:
    """Return the current active batch summary for the upload page."""

    catalog_path = Path(cfg.active_knowledge_catalog_path)
    if not catalog_path.is_file():
        return {"available": False, "catalog_path": str(catalog_path)}
    try:
        payload = json.loads(catalog_path.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return {"available": False, "catalog_path": str(catalog_path)}
    if not isinstance(payload, dict):
        return {"available": False, "catalog_path": str(catalog_path)}
    return {
        "available": True,
        "batch_id": payload.get("active_batch_id"),
        "updated_at": payload.get("updated_at"),
        "history_count": len(payload.get("batch_history") or []),
        "catalog_path": str(catalog_path),
    }
