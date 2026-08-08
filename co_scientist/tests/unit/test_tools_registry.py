"""Smoke tests for tool registry + science-skills bridge parsing."""

from __future__ import annotations

from pathlib import Path
from textwrap import dedent

from co_scientist.tools.registry import ToolRegistry
from co_scientist.tools.science_skills import discover_skills, parse_skill_md


def test_registry_discovers_builtins(tmp_cfg) -> None:
    """web_search needs a TAVILY/BRAVE key; the others are always available."""
    tmp_cfg.secrets.TAVILY_API_KEY = "sk-fake"
    reg = ToolRegistry(tmp_cfg).discover()
    names = {t.name for t in reg.all()}
    assert {
        "web_search", "web_fetch", "germplasm_search",
        "crop_kg_search", "evidence_search",
        "pubmed_search", "arxiv_search", "europe_pmc_search",
    } <= names


def test_web_search_skipped_when_no_search_api_key(tmp_cfg) -> None:
    """Without a Tavily/Brave key the model would only see a tool that returns
    errors; small models tend to abort instead of falling back to PubMed.
    Auto-skip the registration to remove that footgun."""
    tmp_cfg.secrets.TAVILY_API_KEY = ""
    tmp_cfg.secrets.BRAVE_API_KEY = ""
    reg = ToolRegistry(tmp_cfg).discover()
    names = {t.name for t in reg.all()}
    assert "web_search" not in names
    # Other literature tools still available.
    assert "germplasm_search" in names
    assert "crop_kg_search" in names
    assert "evidence_search" in names
    assert "pubmed_search" in names
    assert "europe_pmc_search" in names


def test_agent_allowlist_resolution(tmp_cfg) -> None:
    tmp_cfg.secrets.TAVILY_API_KEY = "sk-fake"
    reg = ToolRegistry(tmp_cfg).discover()
    for agent in ("breeding_designer", "iteration_orchestrator"):
        ts = {t.name for t in reg.tools_for(agent)}
        assert "web_search" in ts
        assert "germplasm_search" in ts
        assert "crop_kg_search" in ts
        assert "evidence_search" in ts
        assert "pubmed_search" in ts


async def test_germplasm_search_tool_returns_local_resource_clues(tmp_cfg) -> None:
    reg = ToolRegistry(tmp_cfg).discover()
    result = await reg.call(
        "germplasm_search",
        {"query": "263A", "crop": "foxtail millet", "max_results": 1},
        ctx=None,  # type: ignore[arg-type]
    )

    assert not result.is_error
    assert result.content["n"] == 1
    record = result.content["results"][0]
    assert record["accession_id"] == "ARCH-263A"
    assert record["url"] == "https://doi.org/10.1016/j.cj.2022.09.003"
    assert "usage_boundary" in record


async def test_crop_kg_search_tool_returns_local_graph_clues(tmp_cfg) -> None:
    reg = ToolRegistry(tmp_cfg).discover()
    result = await reg.call(
        "crop_kg_search",
        {
            "query": "CAPS Seita.5G404900",
            "crop": "\u8c37\u5b50",
            "node_type": "marker",
            "max_results": 1,
        },
        ctx=None,  # type: ignore[arg-type]
    )

    assert not result.is_error
    assert result.content["crop_pack"] == "foxtail_millet"
    assert result.content["n"] == 1
    record = result.content["results"][0]
    assert record["id"] == "marker:Seita.5G404900_CAPS"
    assert record["crop_pack"] == "foxtail_millet"
    assert record["edges"]
    assert "usage_boundary" in record


async def test_evidence_search_tool_returns_local_rag_snippets(tmp_path: Path, tmp_cfg) -> None:
    from co_scientist.knowledge.rag import build_evidence_index, save_evidence_index

    sources = tmp_path / "sources"
    sources.mkdir()
    (sources / "millet_note.md").write_text(
        "# Millet note\n\nCAPS marker evidence should be validated in field trials.\n",
        encoding="utf-8",
    )
    index_path = tmp_path / "index.json"
    save_evidence_index(build_evidence_index(sources), index_path)
    tmp_cfg.knowledge.rag_index_json = str(index_path)

    reg = ToolRegistry(tmp_cfg).discover()
    result = await reg.call(
        "evidence_search",
        {"query": "CAPS marker field", "max_results": 1},
        ctx=None,  # type: ignore[arg-type]
    )

    assert not result.is_error
    assert result.content["n"] == 1
    record = result.content["results"][0]
    assert record["url"].startswith("local-rag://millet_note.md#L")
    assert record["source_path"] == "millet_note.md"
    assert "line_range" in record
    assert "usage_boundary" in record


def test_skill_md_parsing(tmp_path: Path, tmp_cfg, monkeypatch) -> None:
    skills_root = tmp_path / "skills"
    sk = skills_root / "my_test_skill"
    (sk / "scripts").mkdir(parents=True)
    (sk / "SKILL.md").write_text(
        dedent(
            """\
            ---
            name: my_test_skill
            description: A short description for the LLM
            entrypoint: scripts/run.py
            timeout_seconds: 30
            ---

            More detail follows.
            """
        )
    )
    (sk / "scripts" / "run.py").write_text("print('{}')\n")

    meta = parse_skill_md(sk)
    assert meta is not None
    assert meta.name == "my_test_skill"
    assert meta.description.startswith("A short description")
    assert meta.entrypoint is not None and meta.entrypoint.name == "run.py"
    assert meta.timeout_seconds == 30

    # discover_skills walks <science_skills.path>/skills
    monkeypatch.setattr(tmp_cfg.science_skills, "path", str(tmp_path))
    discovered = discover_skills(tmp_cfg)
    assert any(d.name == "my_test_skill" for d in discovered)


def test_skill_md_without_front_matter_still_parses(tmp_path: Path) -> None:
    sk = tmp_path / "raw_skill"
    (sk / "scripts").mkdir(parents=True)
    (sk / "SKILL.md").write_text("# Raw skill\n\nThis describes what it does.\n")
    (sk / "scripts" / "main.py").write_text("print('{}')\n")
    meta = parse_skill_md(sk)
    assert meta is not None
    assert meta.name == "raw_skill"
    assert meta.entrypoint is not None and meta.entrypoint.name == "main.py"
