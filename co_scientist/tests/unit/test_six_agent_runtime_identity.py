from __future__ import annotations

from typing import Any, cast

from co_scientist.agents.base import AgentDeps
from co_scientist.agents.supervisor import Supervisor, _ActionRouter


def test_runtime_task_agents_expose_only_the_five_queued_agents(tmp_cfg, conn) -> None:
    deps = AgentDeps(
        cfg=tmp_cfg,
        db=conn,
        llm=cast(Any, None),
        tools=cast(Any, None),
    )

    agents = Supervisor(tmp_cfg)._build_agents(deps)

    assert set(agents) == {
        "evidence_curator",
        "breeding_designer",
        "validation_planner",
        "risk_reviewer",
        "iteration_orchestrator",
    }
    iteration_agent = agents["iteration_orchestrator"]
    assert isinstance(iteration_agent, _ActionRouter)
