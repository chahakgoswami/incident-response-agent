"""Rollback command suggester: maps IncidentSummary patterns to rollback commands."""

from __future__ import annotations

from typing import List, Optional

from incident_agent.correlator.models import IncidentSummary, IncidentSeverity, SignalType

from .library import get_library
from .models import RollbackCommand, RollbackResult, RollbackStatus


class RollbackSuggester:
    """
    Suggests one or more rollback commands for a given :class:`IncidentSummary`.

    Matching logic
    --------------
    1. Extract pattern tags from the incident:
       - Affected service names (e.g. "api-gateway").
       - Signal-count keys (e.g. "error_surge" if alert count is high,
         "cpu_spike" if metric suggests CPU, "latency_outlier" for traces).
       - Severity-derived tags.
    2. Score each library command by the number of matching tags.
    3. Return the top-N commands, ranked by match score then risk level.
    """

    _RISK_ORDER = {"low": 0, "medium": 1, "high": 2}

    def __init__(self, library: Optional[List[RollbackCommand]] = None) -> None:
        self._library = library if library is not None else get_library()

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    def suggest(self, summary: IncidentSummary, top_n: int = 3) -> List[RollbackCommand]:
        """
        Return up to *top_n* rollback commands that best match the incident.

        Returns an empty list if no command scores at least 1 matching tag.
        """
        tags = self._extract_tags(summary)
        scored: List[tuple[int, int, RollbackCommand]] = []

        for cmd in self._library:
            match_count = sum(1 for t in cmd.pattern_tags if t in tags)
            if match_count == 0:
                continue
            risk_score = self._RISK_ORDER.get(cmd.risk_level, 99)
            # Higher match_count is better; lower risk_score is better
            scored.append((match_count, risk_score, cmd))

        # Sort: descending match count, then ascending risk
        scored.sort(key=lambda x: (-x[0], x[1]))
        return [cmd for _, _, cmd in scored[:top_n]]

    # ------------------------------------------------------------------
    # Tag extraction
    # ------------------------------------------------------------------

    def _extract_tags(self, summary: IncidentSummary) -> set[str]:
        """Derive a set of pattern tags from an IncidentSummary."""
        tags: set[str] = set()

        # Service names
        for svc in summary.affected_services:
            tags.add(svc)

        # Signal-type-based tags
        alert_count = summary.signal_counts.get(SignalType.ALERT.value, 0)
        trace_count = summary.signal_counts.get(SignalType.TRACE.value, 0)
        log_count = summary.signal_counts.get(SignalType.LOG.value, 0)

        if alert_count > 0:
            tags.add("error_surge")
            tags.add("high_error_rate")

        if trace_count > 0:
            tags.add("latency_outlier")

        if log_count > 0:
            tags.add("error_surge")

        # Severity-based tags
        if summary.severity in (IncidentSeverity.CRITICAL, IncidentSeverity.HIGH):
            tags.add("high_load")

        # Metric-based tags derived from signal descriptions
        for signal in summary.contributing_signals:
            desc_lower = signal.description.lower()
            if "cpu" in desc_lower:
                tags.add("cpu_spike")
            if "latency" in desc_lower or "slow" in desc_lower or "timeout" in desc_lower:
                tags.add("latency_outlier")
            if "error" in desc_lower or "5xx" in desc_lower or "exception" in desc_lower:
                tags.add("error_surge")
                tags.add("high_error_rate")
            if "circuit" in desc_lower:
                tags.add("circuit_breaker")
            if "rate limit" in desc_lower or "rate_limit" in desc_lower:
                tags.add("rate_limit")
            if "database" in desc_lower or "db" in desc_lower or "connection pool" in desc_lower:
                tags.add("database")
            if "cache" in desc_lower or "redis" in desc_lower:
                tags.add("cache")

        return tags
