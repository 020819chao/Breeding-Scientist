"""Tests for the bench runner.

We mock the LLM and the BreedingDesignerAgent so the test stays offline. The
runner's job is to (a) construct per-candidate Configs with the right
provider/model, (b) shepherd design results into the candidate buckets,
(c) run pairwise calibration checks, and (d) aggregate calibration score +
win-rate correctly.
That's all unit-testable.
"""

from __future__ import annotations

from datetime import UTC, datetime
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from co_scientist.bench import PRESETS, get_preset
from co_scientist.bench.runner import (
    BenchCandidate,
    _build_summary,
    _candidate_cfg,
    _CandidateState,
    _run_cross_model_pairwise_calibration,
)
from co_scientist.config import Config
from co_scientist.models import Hypothesis, ResearchPlan, Session


def _make_hyp(hid: str, text: str = "h") -> Hypothesis:
    return Hypothesis(
        id=hid, session_id="ses", created_at=datetime.now(UTC),
        created_by="breeding_designer", strategy="literature",
        title="t", summary=text, full_text=text,
        artifact_path=f"artifacts/ses/hypotheses/{hid}.json",
        state="draft",
    )


# ----------------------------- presets ----------------------------- #


def test_baseline_preset_has_documented_candidates() -> None:
    p = get_preset("baseline")
    labels = [c.label for c in p.candidates]
    assert labels == ["gemini-flash", "gemini-pro", "gpt-5", "claude-haiku-4.5"]
    assert "gemini-3-flash-preview" in p.suggested_judge
    for c in p.candidates:
        assert c.provider == "openrouter"
    assert p.default_goal is None
    assert p.goldset is None


def test_minor_grain_preset_bundles_goal_and_goldset() -> None:
    p = get_preset("minor-grain")
    assert p.default_goal is not None
    g = p.default_goal.lower()
    assert "minor-grain" in g
    assert "drought" in g
    assert "validation plan" in g
    assert p.goldset is not None
    entity_names = {e.name for e in p.goldset.entities}
    assert entity_names == {"Seita.5G404900", "SiDREB2-like", "CAPS marker validation"}


def test_vs_direct_preset_doubles_every_candidate() -> None:
    p = get_preset("minor-grain-vs-direct")
    # Same 4 base candidates x 2 modes = 8 entries.
    assert len(p.candidates) == 8
    modes = {c.mode for c in p.candidates}
    assert modes == {"pipeline", "direct"}
    # Labels are suffixed so the result table is unambiguous.
    pipe_labels = [c.label for c in p.candidates if c.mode == "pipeline"]
    direct_labels = [c.label for c in p.candidates if c.mode == "direct"]
    assert all(lbl.endswith("[pipe]") for lbl in pipe_labels)
    assert all(lbl.endswith("[direct]") for lbl in direct_labels)
    # Each base model appears in both modes (same model id, different mode).
    base_models = {c.model for c in p.candidates}
    for m in base_models:
        modes_for_m = {c.mode for c in p.candidates if c.model == m}
        assert modes_for_m == {"pipeline", "direct"}


def test_frontier_vs_direct_preset_lists_current_models() -> None:
    p = get_preset("frontier-minor-grain-vs-direct")
    base_models = {c.model for c in p.candidates}
    baseline_models = {c.model for c in get_preset("minor-grain").candidates}
    assert base_models != baseline_models
    assert len(base_models) >= 3
    # All routed via OpenRouter so one key works.
    for c in p.candidates:
        assert c.provider == "openrouter"


def test_get_preset_raises_on_unknown_name() -> None:
    import pytest as _pytest

    with _pytest.raises(KeyError):
        get_preset("totally-made-up")


def test_presets_dict_listed() -> None:
    assert "baseline" in PRESETS
    assert "minor-grain" in PRESETS


# ----------------------------- _candidate_cfg ----------------------------- #


def test_candidate_cfg_sets_provider_and_propagates_model_to_all_roles() -> None:
    base = Config()
    base.llm.provider = "anthropic"
    cfg = _candidate_cfg(base, "openrouter", "google/gemini-3-flash-preview")
    assert cfg.llm.provider == "openrouter"
    assert cfg.models.goal_interpreter == "google/gemini-3-flash-preview"
    assert cfg.models.breeding_designer == "google/gemini-3-flash-preview"
    assert cfg.models.breeding_designer_revision == "google/gemini-3-flash-preview"
    assert cfg.models.risk_reviewer_evidence == "google/gemini-3-flash-preview"
    assert cfg.models.validation_planner == "google/gemini-3-flash-preview"
    assert cfg.models.risk_reviewer == "google/gemini-3-flash-preview"
    assert cfg.models.pairwise_calibration == "google/gemini-3-flash-preview"


def test_candidate_cfg_zeros_thinking_for_non_anthropic() -> None:
    """Thinking budgets are Anthropic-only; bench shouldn't try to use them
    against OpenAI/Gemini and risk a wasted reservation."""
    base = Config()
    base.thinking.breeding_designer_literature = 8000  # non-zero
    cfg = _candidate_cfg(base, "openrouter", "google/gemini-3-flash-preview")
    assert cfg.thinking.breeding_designer_literature == 0
    assert cfg.thinking.verification_review == 0


def test_candidate_cfg_preserves_thinking_for_anthropic() -> None:
    base = Config()
    base.thinking.breeding_designer_literature = 4000
    cfg = _candidate_cfg(base, "anthropic", "claude-opus-4-7")
    assert cfg.thinking.breeding_designer_literature == 4000


def test_candidate_cfg_is_deep_copy() -> None:
    """Mutations to the per-candidate cfg must not leak back to the base."""
    base = Config()
    base.run.budget_usd = 25.0
    cfg = _candidate_cfg(base, "openai", "gpt-5")
    cfg.run.budget_usd = 999.0
    assert base.run.budget_usd == 25.0


def test_candidate_cfg_flattens_budget_shares_onto_breeding_designer() -> None:
    """Expensive candidate models need the full per-candidate budget share."""
    base = Config()
    cfg = _candidate_cfg(base, "openrouter", "openai/o1")
    assert cfg.budget_shares.goal_interpreter == 0.0
    assert cfg.budget_shares.evidence_curator == 0.0
    assert cfg.budget_shares.reserve == 0.0
    assert cfg.budget_shares.breeding_designer == 1.0
    assert cfg.budget_shares.validation_planner == 0.0
    assert cfg.budget_shares.risk_reviewer == 0.0
    assert cfg.budget_shares.iteration_orchestrator == 0.0
    # Base must remain untouched.
    assert base.budget_shares.breeding_designer == 0.35


# ----------------------------- summary aggregation ----------------------------- #


def test_build_summary_orders_by_mean_calibration_score_descending() -> None:
    a = _CandidateState(candidate_id="bcd_a", spec=BenchCandidate("low", "openrouter", "x"))
    a.calibration_scores = {"h1": 1000.0, "h2": 1100.0}
    a.wins, a.losses = 1, 5

    b = _CandidateState(candidate_id="bcd_b", spec=BenchCandidate("high", "openrouter", "y"))
    b.calibration_scores = {"h3": 1300.0, "h4": 1200.0}
    b.wins, b.losses = 5, 1

    s = _build_summary(
        "bnc_x",
        "goal",
        [a, b],
        "anthropic",
        "claude-sonnet-4-6",
        pairwise_checks_played=6,
    )
    labels = [row["label"] for row in s["candidates"]]
    assert labels == ["high", "low"]


def test_build_summary_handles_no_matches() -> None:
    """A candidate that produced 0 hypotheses gets no calibration score and sorts last."""
    a = _CandidateState(candidate_id="a", spec=BenchCandidate("with_hyps", "p", "m"))
    a.calibration_scores = {"h": 1234.0}
    b = _CandidateState(candidate_id="b", spec=BenchCandidate("no_hyps", "p", "m"))
    # b has no calibration scores.
    s = _build_summary("bnc", "g", [a, b], "anthropic", "x", pairwise_checks_played=1)
    assert s["candidates"][0]["label"] == "with_hyps"
    assert s["candidates"][1]["label"] == "no_hyps"
    assert s["candidates"][1]["mean_calibration_score"] is None


# ----------------------------- cross-model pairwise calibration ----------------------------- #


@pytest.mark.asyncio
async def test_cross_model_pairwise_calibration_runs_n_checks_per_pair(conn) -> None:
    """With 3 candidates the round-robin is C(3,2)=3 pairs.
    pairwise_checks_per_pair=2 gives 6 total checks; each candidate appears in
    exactly 2*2=4 of them.
    """
    cfg = Config()
    plan = ResearchPlan(objective="g", preferences=[])
    ses = Session(
        id="ses_b", created_at=datetime.now(UTC), updated_at=datetime.now(UTC),
        status="running", research_goal="g", research_plan=plan,
        config_snapshot={}, budget_tokens=10_000, budget_usd=1.0,
    )

    # Make 3 candidates, each with 1 hypothesis
    states = []
    for lbl in ["A", "B", "C"]:
        st = _CandidateState(candidate_id=f"bcd_{lbl}",
                             spec=BenchCandidate(lbl, "openrouter", f"model-{lbl}"))
        h = _make_hyp(f"hyp_{lbl}")
        st.hypotheses = [h]
        st.calibration_scores = {h.id: 1200.0}
        st.pairwise_calibrations_played = {h.id: 0}
        states.append(st)

    # We still need a bench row so the bench match FK is satisfied.
    await conn.execute(
        """INSERT INTO bench_runs(id, created_at, updated_at, status, research_goal,
                                  judge_provider, judge_model, config_snapshot)
           VALUES ('bnc_t', ?, ?, 'running', 'g', 'mock', 'mock', '{}')""",
        (datetime.now(UTC).isoformat(), datetime.now(UTC).isoformat()),
    )
    for st in states:
        await conn.execute(
            """INSERT INTO bench_candidates(id, bench_id, label, provider, model)
               VALUES (?, 'bnc_t', ?, ?, ?)""",
            (st.candidate_id, st.spec.label, st.spec.provider, st.spec.model),
        )
    await conn.commit()

    # Mock the judge: A always wins, B always loses to A, C loses to both.
    async def fake_judge(judge_llm, judge_cfg, ses, a, b):
        winner = "a" if a.id < b.id else "b"
        return winner, "mock rationale", 0.0001, 50

    with patch("co_scientist.bench.runner._judge_match", side_effect=fake_judge):
        n = await _run_cross_model_pairwise_calibration(
            conn, "bnc_t", ses, states,
            judge_llm=MagicMock(), judge_cfg=cfg, pairwise_checks_per_pair=2,
        )

    assert n == 6
    # Each candidate played 2 (vs each other candidate) * 2 = 4 matches
    for st in states:
        assert st.wins + st.losses == 4
    # The candidate with the lexicographically smallest hyp_id ("hyp_A") wins
    # every match it plays (4 wins, 0 losses).
    assert states[0].wins == 4
    assert states[0].losses == 0


@pytest.mark.asyncio
async def test_cross_model_pairwise_calibration_handles_empty_candidate(conn) -> None:
    """A candidate whose design step failed (no hyps) is skipped, not crashed."""
    cfg = Config()
    plan = ResearchPlan(objective="g", preferences=[])
    ses = Session(
        id="ses_b2", created_at=datetime.now(UTC), updated_at=datetime.now(UTC),
        status="running", research_goal="g", research_plan=plan,
        config_snapshot={}, budget_tokens=10_000, budget_usd=1.0,
    )

    good = _CandidateState(candidate_id="bcd_good",
                           spec=BenchCandidate("good", "openrouter", "m"))
    h = _make_hyp("hyp_g")
    good.hypotheses = [h]
    good.calibration_scores = {h.id: 1200.0}
    good.pairwise_calibrations_played = {h.id: 0}

    bad = _CandidateState(candidate_id="bcd_bad",
                          spec=BenchCandidate("bad", "openrouter", "m"))
    bad.error = "API unavailable"
    # bad.hypotheses stays empty

    await conn.execute(
        """INSERT INTO bench_runs(id, created_at, updated_at, status, research_goal,
                                  judge_provider, judge_model, config_snapshot)
           VALUES ('bnc_t2', ?, ?, 'running', 'g', 'mock', 'mock', '{}')""",
        (datetime.now(UTC).isoformat(), datetime.now(UTC).isoformat()),
    )
    await conn.execute(
        "INSERT INTO bench_candidates(id, bench_id, label, provider, model) VALUES ('bcd_good', 'bnc_t2', 'g', 'p', 'm')"
    )
    await conn.execute(
        "INSERT INTO bench_candidates(id, bench_id, label, provider, model) VALUES ('bcd_bad', 'bnc_t2', 'b', 'p', 'm')"
    )
    await conn.commit()

    with patch("co_scientist.bench.runner._judge_match", new=AsyncMock(return_value=("a", "ok", 0.0, 10))):
        n = await _run_cross_model_pairwise_calibration(
            conn, "bnc_t2", ses, [good, bad],
            judge_llm=MagicMock(), judge_cfg=cfg, pairwise_checks_per_pair=2,
        )
    # No matches possible because `bad` has no hypotheses.
    assert n == 0


# ----------------------------- run_bench: end-to-end ----------------------------- #


@pytest.mark.asyncio
async def test_run_bench_writes_summary_and_status(tmp_cfg) -> None:
    """End-to-end with a mocked design step + judge 鈥?confirms persistence."""
    from co_scientist.bench import run_bench

    # Drive hypothesis design to produce 1 hypothesis per call, deterministically.
    async def fake_execute(self, task):
        from co_scientist.models import TaskResult
        hid = f"hyp_{task.payload.get('strategy', 'x')}_{task.id[-6:]}"
        async with self.deps.db.execute(
            """INSERT INTO hypotheses(id, session_id, created_at, created_by,
                                       strategy, title, summary, full_text,
                                       artifact_path, state)
               VALUES (?, ?, ?, 'breeding_designer', 'literature',
                       't', 'a summary', 'a body',
                       ?, 'draft')""",
            (hid, task.session_id, datetime.now(UTC).isoformat(),
             f"artifacts/{task.session_id}/hypotheses/{hid}.json"),
        ):
            pass
        await self.deps.db.commit()
        return TaskResult(kind="hypothesis_created", hypothesis_ids=[hid])

    # Mock the judge with a stable side: a always wins.
    async def fake_judge(judge_llm, judge_cfg, ses, a, b):
        return "a", "fake", 0.0, 5

    tmp_cfg.secrets.OPENROUTER_API_KEY = "fake"
    tmp_cfg.secrets.ANTHROPIC_API_KEY = "fake"

    with (
        patch("co_scientist.bench.runner.BreedingDesignerAgent.execute", new=fake_execute),
        patch("co_scientist.bench.runner._judge_match", side_effect=fake_judge),
        patch("co_scientist.bench.runner.get_provider", return_value=MagicMock()),
    ):
        outcome = await run_bench(
            tmp_cfg,
            goal="test goal",
            candidates=[
                BenchCandidate("a", "openrouter", "google/gemini-3-flash-preview"),
                BenchCandidate("b", "openrouter", "openai/gpt-5"),
            ],
            n_hyps_per_candidate=1,
            pairwise_checks_per_pair=2,
            judge_provider="anthropic",
            judge_model="claude-sonnet-4-6",
        )

    assert outcome.bench_id.startswith("bnc_")
    assert outcome.pairwise_checks_played == 2
    # Both candidates produced 1 hyp; both played 2 matches; one is fully
    # dominated by the fake judge.
    labels = {row["label"]: row for row in outcome.candidates}
    assert set(labels) == {"a", "b"}
    # Each candidate has its mean calibration score populated.
    assert all(row["mean_calibration_score"] is not None for row in outcome.candidates)
