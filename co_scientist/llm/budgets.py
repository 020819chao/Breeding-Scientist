"""Token + USD budgets, per-session and per-agent.

Concurrent agents share the same TokenBudget; admission is serialized by an
asyncio.Lock so two workers can't simultaneously over-reserve.
"""

from __future__ import annotations

import asyncio
from dataclasses import dataclass, field

from ..config import Config


class BudgetExceeded(Exception):
    """Raised by `BudgetGuard.admit` when no headroom remains."""


@dataclass
class _Counter:
    used_tokens: int = 0                # input + output, kept for older callers
    used_input_tokens: int = 0
    used_output_tokens: int = 0
    used_usd: float = 0.0
    reserved_tokens: int = 0
    reserved_usd: float = 0.0


@dataclass
class TokenBudget:
    """Total session budget. Per-agent shares are computed from cfg.budget_shares."""

    cfg: Config
    budget_tokens: int
    budget_usd: float
    _lock: asyncio.Lock = field(default_factory=asyncio.Lock)
    _global: _Counter = field(default_factory=_Counter)
    _per_agent: dict[str, _Counter] = field(default_factory=dict)

    # ----------------------------- shares ------------------------------- #

    def share_tokens(self, agent: str) -> int:
        pct = self._agent_share_pct(agent)
        return int(self.budget_tokens * pct)

    def share_usd(self, agent: str) -> float:
        pct = self._agent_share_pct(agent)
        return self.budget_usd * pct

    def _agent_share_pct(self, agent: str) -> float:
        shares = self.cfg.budget_shares
        return {
            "goal_interpreter": shares.goal_interpreter,
            "parse_goal": shares.goal_interpreter,
            "evidence_curator": shares.evidence_curator,
            "breeding_designer": shares.breeding_designer,
            "iteration_orchestrator": shares.iteration_orchestrator,
            "validation_planner": shares.validation_planner,
            "risk_reviewer": shares.risk_reviewer,
        }.get(agent, 0.0)

    def reserve_usd(self) -> float:
        """Return the shared USD reserve available to all agent roles."""

        return self.budget_usd * self.cfg.budget_shares.reserve

    def _reserve_commitment_usd(self, agent: str, ctr: _Counter) -> float:
        """Return the part of an agent's commitment above its base share."""

        committed = ctr.used_usd + ctr.reserved_usd
        return max(0.0, committed - self.share_usd(agent))

    def _committed_reserve_usd(self, *, replacement: tuple[str, float] | None = None) -> float:
        """Calculate reserve usage, optionally replacing one agent's commitment.

        Reserve is a pool, rather than a fixed allowance copied onto every
        agent. This prevents concurrent agents from collectively overspending
        the same reserve while still allowing an underused role's budget to be
        borrowed by a role with extra review work.
        """

        total = 0.0
        replacement_agent = replacement[0] if replacement else None
        for agent, ctr in self._per_agent.items():
            if agent == replacement_agent:
                total += replacement[1]
            else:
                total += self._reserve_commitment_usd(agent, ctr)
        if replacement and replacement_agent not in self._per_agent:
            total += replacement[1]
        return total

    # ----------------------------- ops ---------------------------------- #

    async def admit(
        self, agent: str, *, est_tokens: int, est_usd: float
    ) -> None:
        """Block-style admission: raise BudgetExceeded if we can't afford this call."""
        async with self._lock:
            ctr = self._per_agent.setdefault(agent, _Counter())
            # Session-wide cap first (includes reserve)
            if (
                self._global.used_tokens + self._global.reserved_tokens + est_tokens
                > self.budget_tokens
            ) or (
                self._global.used_usd + self._global.reserved_usd + est_usd
                > self.budget_usd
            ):
                raise BudgetExceeded(
                    f"session budget exhausted (used_usd={self._global.used_usd:.2f},"
                    f" reserved={self._global.reserved_usd:.2f}, cap={self.budget_usd:.2f})"
                )
            # Base share plus a dynamically borrowed portion of the shared
            # reserve. The reserve is committed only for the amount above the
            # agent's base share and cannot be promised to multiple agents.
            base_share_usd = self.share_usd(agent)
            candidate_commitment = ctr.used_usd + ctr.reserved_usd + est_usd
            candidate_reserve = max(0.0, candidate_commitment - base_share_usd)
            reserve_total = self._committed_reserve_usd(
                replacement=(agent, candidate_reserve)
            )
            if reserve_total > self.reserve_usd() + 1e-12:
                raise BudgetExceeded(
                    f"agent {agent!r} share exhausted (used={ctr.used_usd:.2f},"
                    f" reserved={ctr.reserved_usd:.2f}, base_share={base_share_usd:.2f},"
                    f" reserve_used={reserve_total:.2f}, reserve_cap={self.reserve_usd():.2f})"
                )
            ctr.reserved_tokens += est_tokens
            ctr.reserved_usd += est_usd
            self._global.reserved_tokens += est_tokens
            self._global.reserved_usd += est_usd

    async def settle(
        self,
        agent: str,
        *,
        est_tokens: int,
        est_usd: float,
        actual_usd: float,
        actual_input_tokens: int = 0,
        actual_output_tokens: int = 0,
        actual_tokens: int | None = None,
    ) -> None:
        """Release the reservation and credit actual usage.

        Pass `actual_input_tokens` and `actual_output_tokens` separately so the
        bench (and any future per-input/output accounting) can read them from
        the snapshot. The older `actual_tokens` kwarg is treated as a combined
        total and credited only to `used_tokens` — its split is unknown so the
        per-input/output counters stay at 0 for that call.
        """
        if actual_tokens is None:
            actual_tokens = actual_input_tokens + actual_output_tokens
        async with self._lock:
            ctr = self._per_agent.setdefault(agent, _Counter())
            ctr.reserved_tokens = max(0, ctr.reserved_tokens - est_tokens)
            ctr.reserved_usd = max(0.0, ctr.reserved_usd - est_usd)
            ctr.used_tokens += actual_tokens
            ctr.used_input_tokens += actual_input_tokens
            ctr.used_output_tokens += actual_output_tokens
            ctr.used_usd += actual_usd
            self._global.reserved_tokens = max(0, self._global.reserved_tokens - est_tokens)
            self._global.reserved_usd = max(0.0, self._global.reserved_usd - est_usd)
            self._global.used_tokens += actual_tokens
            self._global.used_input_tokens += actual_input_tokens
            self._global.used_output_tokens += actual_output_tokens
            self._global.used_usd += actual_usd

    def snapshot(self) -> dict[str, dict[str, float | int]]:
        out: dict[str, dict[str, float | int]] = {
            "_global": {
                "used_tokens": self._global.used_tokens,
                "used_input_tokens": self._global.used_input_tokens,
                "used_output_tokens": self._global.used_output_tokens,
                "used_usd": self._global.used_usd,
                "reserved_tokens": self._global.reserved_tokens,
                "reserved_usd": self._global.reserved_usd,
                "reserve_usd": self.reserve_usd(),
                "reserve_committed_usd": self._committed_reserve_usd(),
                "budget_tokens": self.budget_tokens,
                "budget_usd": self.budget_usd,
            }
        }
        for agent, ctr in self._per_agent.items():
            out[agent] = {
                "used_tokens": ctr.used_tokens,
                "used_input_tokens": ctr.used_input_tokens,
                "used_output_tokens": ctr.used_output_tokens,
                "used_usd": ctr.used_usd,
                "reserved_tokens": ctr.reserved_tokens,
                "reserved_usd": ctr.reserved_usd,
                "share_usd": self.share_usd(agent),
                "reserve_used_usd": self._reserve_commitment_usd(agent, ctr),
            }
        return out
