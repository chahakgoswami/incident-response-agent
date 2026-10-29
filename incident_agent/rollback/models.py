"""Data models for rollback commands and execution results."""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, timezone
from enum import Enum
from typing import List, Optional


class RollbackStatus(str, Enum):
    """Outcome of a rollback suggestion."""

    PENDING = "pending"       # Suggested but not yet confirmed
    CONFIRMED = "confirmed"   # Human approved — simulated execution ran
    REJECTED = "rejected"     # Human declined
    SKIPPED = "skipped"       # No suitable command found


@dataclass
class RollbackCommand:
    """
    A single predefined rollback action.

    Fields
    ------
    command_id   : Unique identifier for this command template.
    description  : Human-readable explanation of what the command does.
    command      : The shell command string (safe — only printed/simulated).
    pattern_tags : Incident pattern tags this command matches (e.g. "cpu_spike").
    service_hint : Optional service name the command targets.
    risk_level   : 'low' | 'medium' | 'high'  — informational only.
    """

    command_id: str
    description: str
    command: str
    pattern_tags: List[str] = field(default_factory=list)
    service_hint: Optional[str] = None
    risk_level: str = "low"

    def to_dict(self) -> dict:
        return {
            "command_id": self.command_id,
            "description": self.description,
            "command": self.command,
            "pattern_tags": self.pattern_tags,
            "service_hint": self.service_hint,
            "risk_level": self.risk_level,
        }


@dataclass
class RollbackResult:
    """
    The outcome of presenting a rollback suggestion to the operator.

    Fields
    ------
    incident_id    : The incident this rollback was suggested for.
    command        : The RollbackCommand that was suggested (None if skipped).
    status         : CONFIRMED / REJECTED / SKIPPED / PENDING.
    decided_at     : When the human made their decision.
    simulated_output: Fake terminal output shown after a CONFIRMED execution.
    """

    incident_id: str
    status: RollbackStatus
    command: Optional[RollbackCommand] = None
    decided_at: Optional[datetime] = None
    simulated_output: str = ""

    def to_dict(self) -> dict:
        return {
            "incident_id": self.incident_id,
            "status": self.status.value,
            "command": self.command.to_dict() if self.command else None,
            "decided_at": self.decided_at.isoformat() if self.decided_at else None,
            "simulated_output": self.simulated_output,
        }
