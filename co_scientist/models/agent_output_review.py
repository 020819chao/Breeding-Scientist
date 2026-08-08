"""Mentor review records for structured six-agent outputs."""

from __future__ import annotations

from datetime import datetime
from typing import Literal

from pydantic import BaseModel

AgentOutputReviewStatus = Literal["approved", "needs_revision", "rejected"]


class AgentOutputReview(BaseModel):
    id: str
    session_id: str
    created_at: datetime
    agent: str
    output_key: str
    output_path: str | None = None
    target_id: str | None = None
    status: AgentOutputReviewStatus
    reviewer: str
    note: str = ""
