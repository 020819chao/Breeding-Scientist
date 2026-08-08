"""Pure pairwise-calibration math — no DB, no I/O."""

from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class PairwiseCalibrationUpdate:
    calibration_a_after: float
    calibration_b_after: float
    expected_a: float
    k: int


def calibration_k_factor(
    pairwise_calibrations_played: int,
    *,
    new_threshold: int = 5,
    k_new: int = 32,
    k_warm: int = 16,
) -> int:
    """Higher K for new entrants; lower K once a route has enough calibrations."""
    return k_new if pairwise_calibrations_played < new_threshold else k_warm


def expected_score(calibration_a: float, calibration_b: float) -> float:
    return 1.0 / (1.0 + 10 ** ((calibration_b - calibration_a) / 400.0))


def update_pairwise_calibration_score(
    calibration_a: float,
    calibration_b: float,
    winner: str,           # "a" | "b"
    pairwise_calibrations_min: int,
    *,
    k_new: int = 32,
    k_warm: int = 16,
) -> PairwiseCalibrationUpdate:
    """Standard pairwise update. K is decided by the less experienced route's count."""
    if winner not in ("a", "b"):
        raise ValueError(f"winner must be 'a' or 'b', got {winner!r}")
    k = calibration_k_factor(pairwise_calibrations_min, k_new=k_new, k_warm=k_warm)
    expected_a = expected_score(calibration_a, calibration_b)
    score_a = 1.0 if winner == "a" else 0.0
    delta = k * (score_a - expected_a)
    return PairwiseCalibrationUpdate(
        calibration_a_after=calibration_a + delta,
        calibration_b_after=calibration_b - delta,
        expected_a=expected_a,
        k=k,
    )


__all__ = [
    "PairwiseCalibrationUpdate",
    "calibration_k_factor",
    "expected_score",
    "update_pairwise_calibration_score",
]
