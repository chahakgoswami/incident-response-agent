"""Data models for the correlation engine output."""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime
from enum import Enum
from typing import Any, Dict, List, Optional


class IncidentSeverity(str, Enum):
    """Ranked severity for a correlated incident."""

    CRITICAL = "critical"
    HIGH = "high"
    MEDIUM = "medium"
    LOW = "low"
    UNKNOWN = "unknown"

    @classmethod
    def rank(cls, severity: "IncidentSeverity") -> int:
        """Return a numeric rank (higher == more severe)."""
        _ranks = {
            cls.CRITICAL: 4,
            cls.HIGH: 3,
            cls.MEDIUM: 2,
            cls.LOW: 1,
            cls.UNKNOWN: 0,
        }
        return _ranks.get(severity, 0)


class SignalType(str, Enum):
    """The kind of observability signal that contributed to an incident."""

    ALERT = "alert"
    TRACE = "trace"
    LOG = "log"


@dataclass
class CorrelatedSignal:
    """A single signal (alert, trace span, or log entry) that contributed to an incident."""

    signal_type: SignalType
    signal_id: str
    service: str
    timestamp: datetime
    severity_hint: Optional[IncidentSeverity]
    description: str
    raw: Dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> dict:
        return {
            "signal_type": self.signal_type.value,
            "signal_id": self.signal_id,
            "service": self.service,
            "timestamp": self.timestamp.isoformat(),
            "severity_hint": self.severity_hint.value if self.severity_hint else None,
            "description": self.description,
        }


@dataclass
class IncidentSummary:
    """
    A ranked, correlated summary of an incident produced by the correlation engine.

    Fields
    ------
    incident_id     : Unique identifier for this correlated incident.
    severity        : Overall severity computed from contributing signals.
    affected_services: Ordered list of services involved (most impacted first).
    contributing_signals: All signals that were grouped into this incident.
    window_start    : Earliest signal timestamp in the correlation window.
    window_end      : Latest signal timestamp in the correlation window.
    signal_counts   : Breakdown of signals by type.
    score           : Numeric severity score used for ranking (higher == worse).
    summary_text    : Human-readable one-line description.
    """

    incident_id: str
    severity: IncidentSeverity
    affected_services: List[str]
    contributing_signals: List[CorrelatedSignal]
    window_start: datetime
    window_end: datetime
    signal_counts: Dict[str, int] = field(default_factory=dict)
    score: float = 0.0
    summary_text: str = ""

    def to_dict(self) -> dict:
        return {
            "incident_id": self.incident_id,
            "severity": self.severity.value,
            "score": round(self.score, 2),
            "affected_services": self.affected_services,
            "window_start": self.window_start.isoformat(),
            "window_end": self.window_end.isoformat(),
            "signal_counts": self.signal_counts,
            "summary_text": self.summary_text,
            "contributing_signals": [s.to_dict() for s in self.contributing_signals],
        }

    def __repr__(self) -> str:  # pragma: no cover
        return (
            f"IncidentSummary(id={self.incident_id!r}, "
            f"severity={self.severity.value}, "
            f"score={self.score:.1f}, "
            f"services={self.affected_services})"
        )
