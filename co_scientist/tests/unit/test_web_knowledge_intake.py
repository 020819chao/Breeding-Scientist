"""Tests for the web knowledge-batch upload boundary."""

from __future__ import annotations

import json
import shutil
import zipfile
from io import BytesIO
from pathlib import Path

import httpx

from co_scientist.knowledge.web_intake import extract_batch_zip
from co_scientist.web.app import create_app


def _make_batch(tmp_path: Path) -> Path:
    project_root = Path(__file__).resolve().parents[3]
    batch = tmp_path / "rice_upload"
    sources = batch / "sources"
    (sources / "kg").mkdir(parents=True)
    (sources / "rag").mkdir(parents=True)
    copies = {
        "germplasm_resources.csv": project_root / "docs/templates/germplasm_resources_public_seed.csv",
        "marker_qtl_library.csv": project_root / "docs/templates/marker_qtl_library_seed.csv",
        "phenotype_protocol_library.csv": project_root / "docs/templates/phenotype_protocol_library_seed.csv",
        "field_trial_records.csv": project_root / "docs/templates/field_trial_records_seed.csv",
    }
    for name, source in copies.items():
        shutil.copy2(source, sources / name)
    shutil.copy2(
        project_root / "docs/templates/foxtail_millet_kg_seed.json",
        sources / "kg/foxtail_millet.json",
    )
    shutil.copy2(
        project_root / "docs/rag_sources/flowering_synchrony_crossing_risk_preflight_2026-07.md",
        sources / "rag/field_note.md",
    )
    (batch / "outputs").mkdir()
    (batch / "manifest.json").write_text(
        json.dumps(
            {
                "batch_id": "web-test-2026-08-05",
                "schema_version": "1.0",
                "crop_scope": ["foxtail_millet"],
                "sources": {
                    "germplasm_csv": "sources/germplasm_resources.csv",
                    "crop_kg_packs": [
                        {"crop_key": "foxtail_millet", "path": "sources/kg/foxtail_millet.json"}
                    ],
                    "rag_sources_dir": "sources/rag",
                    "rag_index_json": "outputs/evidence_index.json",
                    "marker_qtl_csv": "sources/marker_qtl_library.csv",
                    "phenotype_protocol_csv": "sources/phenotype_protocol_library.csv",
                    "field_trial_csv": "sources/field_trial_records.csv",
                },
            }
        ),
        encoding="utf-8",
    )
    return batch


def _zip_bytes(batch: Path) -> bytes:
    stream = BytesIO()
    with zipfile.ZipFile(stream, "w", zipfile.ZIP_DEFLATED) as archive:
        for path in batch.rglob("*"):
            if path.is_file():
                archive.write(path, path.relative_to(batch.parent).as_posix())
    return stream.getvalue()


def test_extract_batch_zip_rejects_traversal(tmp_path: Path) -> None:
    zip_path = tmp_path / "unsafe.zip"
    with zipfile.ZipFile(zip_path, "w") as archive:
        archive.writestr("../outside.txt", "blocked")

    try:
        extract_batch_zip(zip_path, tmp_path / "extract")
    except ValueError as exc:
        assert "不安全路径" in str(exc)
    else:
        raise AssertionError("unsafe ZIP should be rejected")
    assert not (tmp_path / "outside.txt").exists()


async def test_web_upload_runs_knowledge_import(tmp_path: Path, tmp_cfg) -> None:
    tmp_cfg.knowledge.active_catalog = str(tmp_path / "active" / "catalog.json")
    tmp_cfg.knowledge.allow_direct_activation = True
    batch = _make_batch(tmp_path)
    app = create_app(tmp_cfg)
    transport = httpx.ASGITransport(app=app)
    async with httpx.AsyncClient(transport=transport, base_url="http://test") as client:
        response = await client.post(
            "/knowledge/upload",
            files={"batch_file": ("batch.zip", _zip_bytes(batch), "application/zip")},
        )

        assert response.status_code == 200
        assert "批次已激活" in response.text
        assert "本次新增资料已完成安全检查" in response.text
        assert "知识库接入中心" in response.text
        assert "web_test_2026_08_05" in response.text
        assert "知识批次历史" in response.text
        assert "查看完整处理统计" not in response.text

        detail = await client.get("/knowledge/batches/web_test_2026_08_05")
        assert detail.status_code == 200
        assert "知识批次详情" in detail.text
        assert "本次新增资料" in detail.text
        assert "文件 hash 差异" not in detail.text
        assert "本批次处理统计" not in detail.text
        assert "rag_chunks" not in detail.text

    catalog = json.loads((tmp_path / "active" / "catalog.json").read_text(encoding="utf-8"))
    assert catalog["active_batch_id"] == "web_test_2026_08_05"
    assert (tmp_path / "active" / "evidence_index.json").is_file()


async def test_web_preflight_requires_approval_before_activation(tmp_path: Path, tmp_cfg) -> None:
    tmp_cfg.knowledge.active_catalog = str(tmp_path / "active" / "catalog.json")
    batch = _make_batch(tmp_path)
    app = create_app(tmp_cfg)
    transport = httpx.ASGITransport(app=app)
    async with httpx.AsyncClient(transport=transport, base_url="http://test") as client:
        response = await client.post(
            "/knowledge/upload",
            data={"dry_run": "true"},
            files={"batch_file": ("batch.zip", _zip_bytes(batch), "application/zip")},
        )
        assert response.status_code == 200
        assert "预检通过" in response.text
        assert "进入专家审核" in response.text
        assert not (tmp_path / "active" / "catalog.json").exists()

        detail = await client.get("/knowledge/batches/web_test_2026_08_05")
        assert detail.status_code == 200
        assert "待专家审核" in detail.text
        assert "审核通过并激活" in detail.text

        dashboard = await client.get("/knowledge/monitor")
        assert dashboard.status_code == 200
        assert "知识库监控中心" in dashboard.text
        assert "web_test_2026_08_05" in dashboard.text

        dashboard_api = await client.get("/api/knowledge/monitor/dashboard")
        assert dashboard_api.status_code == 200
        assert dashboard_api.json()["pending"][0]["batch_id"] == "web_test_2026_08_05"

        approval = await client.post(
            "/knowledge/batches/web_test_2026_08_05/approve",
            data={"reviewer": "导师甲", "note": "范围和结构检查通过"},
        )
        assert approval.status_code == 200
        assert "审核通过并已激活" in approval.text

    catalog = json.loads((tmp_path / "active" / "catalog.json").read_text(encoding="utf-8"))
    assert catalog["active_batch_id"] == "web_test_2026_08_05"
    history = catalog["batch_history"][-1]
    assert history["approval_status"] == "approved"
    assert history["reviewer"] == "导师甲"
    assert not (tmp_path / "pending" / "web_test_2026_08_05").exists()


async def test_web_knowledge_template_download(tmp_cfg) -> None:
    app = create_app(tmp_cfg)
    transport = httpx.ASGITransport(app=app)
    async with httpx.AsyncClient(transport=transport, base_url="http://test") as client:
        response = await client.get("/knowledge/template")

    assert response.status_code == 200
    assert response.headers["content-type"].startswith("application/zip")
    with zipfile.ZipFile(BytesIO(response.content)) as archive:
        names = set(archive.namelist())
        assert "knowledge_batch_template/manifest.json" in names
        assert "knowledge_batch_template/sources/germplasm_resources.csv" in names
        assert "knowledge_batch_template/sources/kg/crop_kg.json" in names
        assert "knowledge_batch_template/sources/rag/README.md" in names


async def test_web_knowledge_demo_download(tmp_cfg) -> None:
    app = create_app(tmp_cfg)
    transport = httpx.ASGITransport(app=app)
    async with httpx.AsyncClient(transport=transport, base_url="http://test") as client:
        response = await client.get("/knowledge/demo")

    assert response.status_code == 200
    assert "foxtail_millet_drought_demo_2026.zip" in response.headers["content-disposition"]
    with zipfile.ZipFile(BytesIO(response.content)) as archive:
        names = set(archive.namelist())
        assert "foxtail_millet_drought_demo_2026/manifest.json" in names
        assert "foxtail_millet_drought_demo_2026/sources/kg/foxtail_millet.json" in names
        assert "foxtail_millet_drought_demo_2026/sources/rag/foxtail_millet_drought_testing_note.md" in names
