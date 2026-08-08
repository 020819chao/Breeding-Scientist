"""Pairwise calibration domain models.

This module is the public import path for the breeding-scientist pairwise
calibration layer.
"""

from __future__ import annotations

from datetime import datetime
from typing import Literal

from pydantic import BaseModel

PairwiseCalibrationMode = Literal["pairwise", "debate", "batch", "invalid"]
PairwisePreference = Literal["a", "b"]


class PairwiseCalibrationMatch(BaseModel):
    id: str
    session_id: str
    created_at: datetime
    hyp_a: str
    hyp_b: str
    mode: PairwiseCalibrationMode
    winner: PairwisePreference | None
    calibration_a_before: float
    calibration_b_before: float
    calibration_a_after: float | None = None
    calibration_b_after: float | None = None
    rationale: str | None = None
    transcript_id: str | None = None
    similarity: float | None = None


class PairwiseCalibrationJournalEntry(BaseModel):
    """Append-only ledger entry for idempotent calibration updates."""

    update_id: str
    match_id: str
    hyp_a: str
    hyp_b: str
    winner: PairwisePreference
    calibration_a_before: float
    calibration_b_before: float
    calibration_a_after: float
    calibration_b_after: float
    applied_at: int
