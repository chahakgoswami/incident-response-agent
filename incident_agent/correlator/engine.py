"""Correlation engine: ingests mock signals, groups them, and produces IncidentSummary objects."""

from __future__ import annotations

import uuid
from collections import defaultdict
from datetime import datetime, timedelta, timezone
from typing import Dict, List, Optional, Tuple

from incident_agent.mock_data.alerts import Alert, AlertSeverity
from incident_agent.mock_data.logs import LogEntry, LogLevel
from incident_agent.mock_data.scenario import IncidentScenario
from incident_agent.mock_data.traces import Span, SpanStatus, Trace

from .models import CorrelatedSignal, IncidentSeverity, IncidentSummary, SignalType

# ---------------------------------------------------------------------------
# Severity mappings
# ---------------------------------------------------------------------------

_ALERT_SEV_MAP: Dict[AlertSeverity, IncidentSeverity] = {
    AlertSeverity.CRITICAL: IncidentSeverity.CRITICAL,
    AlertSeverity.HIGH: IncidentSeverity.HIGH,
    AlertSeverity.MEDIUM: IncidentSeverity.MEDIUM,
    AlertSeverity.LOW: IncidentSeverity.LOW,
}

_LOG_SEV_MAP: Dict[LogLevel, IncidentSeverity] = {
    LogLevel.CRITICAL: IncidentSeverity.CRITICAL,
    LogLevel.ERROR: IncidentSeverity.HIGH,
    LogLevel.WARNING: IncidentSeverity.MEDIUM,
    LogLevel.INFO: IncidentSeverity.LOW,
    LogLevel.DEBUG: IncidentSeverity.LOW,
}

# Score weights per signal contribution
_SEV_SCORE: Dict[IncidentSeverity, float] = {
    IncidentSeverity.CRITICAL: 10.0,
    IncidentSeverity.HIGH: 5.0,
    IncidentSeverity.MEDIUM: 2.0,
    IncidentSeverity.LOW: 0.5,
    IncidentSeverity.UNKNOWN: 0.1,
}


class CorrelationEngine:
    """
    Groups observability signals by time window and service tag, then produces
    a ranked list of :class:`IncidentSummary` objects.

    Parameters
    ----------
    window_minutes : int
        Width of the sliding correlation window (default 5 minutes).
    min_signals : int
        Minimum number of signals required to form an incident group (default 1).
    latency_error_threshold_ms : float
        Span duration above which a span is treated as a latency signal (default 800 ms).
    """

    def __init__(
        self,
        window_minutes: int = 5,
        min_signals: int = 1,
        latency_error_threshold_ms: float = 800.0,
    ) -> None:
        self.window_minutes = window_minutes
        self.min_signals = min_signals
        self.latency_error_threshold_ms = latency_error_threshold_ms

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    def correlate(
        self,
        alerts: Optional[List[Alert]] = None,
        traces: Optional[List[Trace]] = None,
        logs: Optional[List[LogEntry]] = None,
    ) -> List[IncidentSummary]:
        """
        Ingest raw signals, group them into time windows, and return a ranked
        list of IncidentSummary (most severe first).
        """
        alerts = alerts or []
        traces = traces or []
        logs = logs or []

        # Convert everything to CorrelatedSignal
        signals: List[CorrelatedSignal] = []
        signals.extend(self._signals_from_alerts(alerts))
        signals.extend(self._signals_from_traces(traces))
        signals.extend(self._signals_from_logs(logs))

        if not signals:
            return []

        # Group signals into time windows keyed by (window_bucket, service)
        groups = self._group_signals(signals)

        # Build one IncidentSummary per group
        summaries: List[IncidentSummary] = []
        for (window_bucket, service), group_signals in groups.items():
            if len(group_signals) < self.min_signals:
                continue
            summary = self._build_summary(group_signals)
            summaries.append(summary)

        # Rank by score descending
        summaries.sort(key=lambda s: s.score, reverse=True)
        return summaries

    def correlate_scenario(self, scenario: IncidentScenario) -> List[IncidentSummary]:
        """Convenience wrapper that accepts an :class:`IncidentScenario`."""
        return self.correlate(
            alerts=scenario.alerts,
            traces=scenario.traces,
            logs=scenario.logs,
        )

    # ------------------------------------------------------------------
    # Signal conversion helpers
    # ------------------------------------------------------------------

    def _signals_from_alerts(self, alerts: List[Alert]) -> List[CorrelatedSignal]:
        out: List[CorrelatedSignal] = []
        for alert in alerts:
            sev = _ALERT_SEV_MAP.get(alert.severity, IncidentSeverity.UNKNOWN)
            out.append(
                CorrelatedSignal(
                    signal_type=SignalType.ALERT,
                    signal_id=alert.alert_id,
                    service=alert.service,
                    timestamp=alert.timestamp,
                    severity_hint=sev,
                    description=(
                        f"[ALERT] {alert.name} on {alert.service}: "
                        f"{alert.metric}={alert.value} (threshold={alert.threshold})"
                    ),
                    raw=alert.to_dict(),
                )
            )
        return out

    def _signals_from_traces(self, traces: List[Trace]) -> List[CorrelatedSignal]:
        out: List[CorrelatedSignal] = []
        for trace in traces:
            for span in trace.spans:
                sev, desc = self._classify_span(span)
                if sev is None:
                    continue  # skip healthy, low-value spans
                out.append(
                    CorrelatedSignal(
                        signal_type=SignalType.TRACE,
                        signal_id=span.span_id,
                        service=span.service,
                        timestamp=span.start_time,
                        severity_hint=sev,
                        description=desc,
                        raw=span.to_dict(),
                    )
                )
        return out

    def _classify_span(self, span: Span) -> Tuple[Optional[IncidentSeverity], str]:
        """Return (severity, description) for a span, or (None, '') if healthy."""
        if span.status == SpanStatus.ERROR:
            return (
                IncidentSeverity.HIGH,
                f"[TRACE] Error span in {span.service}: {span.operation} — "
                f"{span.error_message or 'unknown error'}",
            )
        if span.status == SpanStatus.TIMEOUT:
            return (
                IncidentSeverity.HIGH,
                f"[TRACE] Timeout span in {span.service}: {span.operation} "
                f"after {span.duration_ms:.0f}ms",
            )
        if span.duration_ms >= self.latency_error_threshold_ms:
            return (
                IncidentSeverity.MEDIUM,
                f"[TRACE] Slow span in {span.service}: {span.operation} "
                f"took {span.duration_ms:.0f}ms",
            )
        return None, ""

    def _signals_from_logs(self, logs: List[LogEntry]) -> List[CorrelatedSignal]:
        out: List[CorrelatedSignal] = []
        _relevant = {LogLevel.WARNING, LogLevel.ERROR, LogLevel.CRITICAL}
        for entry in logs:
            if entry.level not in _relevant:
                continue
            sev = _LOG_SEV_MAP.get(entry.level, IncidentSeverity.UNKNOWN)
            out.append(
                CorrelatedSignal(
                    signal_type=SignalType.LOG,
                    signal_id=entry.log_id,
                    service=entry.service,
                    timestamp=entry.timestamp,
                    severity_hint=sev,
                    description=f"[LOG] {entry.level.value} on {entry.service}: {entry.message}",
                    raw=entry.to_dict(),
                )
            )
        return out

    # ------------------------------------------------------------------
    # Grouping
    # ------------------------------------------------------------------

    def _window_bucket(self, ts: datetime) -> datetime:
        """Truncate a timestamp to the nearest window boundary."""
        window_seconds = self.window_minutes * 60
        epoch = datetime(1970, 1, 1, tzinfo=timezone.utc)
        delta = (ts - epoch).total_seconds()
        bucket_epoch = (delta // window_seconds) * window_seconds
        return epoch + timedelta(seconds=bucket_epoch)

    def _group_signals(
        self, signals: List[CorrelatedSignal]
    ) -> Dict[Tuple[datetime, str], List[CorrelatedSignal]]:
        """Group signals by (time_window_bucket, service)."""
        groups: Dict[Tuple[datetime, str], List[CorrelatedSignal]] = defaultdict(list)
        for signal in signals:
            bucket = self._window_bucket(signal.timestamp)
            groups[(bucket, signal.service)].append(signal)
        return dict(groups)

    # ------------------------------------------------------------------
    # Summary builder
    # ------------------------------------------------------------------

    def _build_summary(
        self, signals: List[CorrelatedSignal]
    ) -> IncidentSummary:
        """Construct an IncidentSummary from a group of correlated signals."""
        # Compute time window
        timestamps = [s.timestamp for s in signals]
        window_start = min(timestamps)
        window_end = max(timestamps)

        # Collect unique services ordered by signal count (most signals first)
        service_counts: Dict[str, int] = defaultdict(int)
        for s in signals:
            service_counts[s.service] += 1
        affected_services = sorted(
            service_counts.keys(), key=lambda svc: service_counts[svc], reverse=True
        )

        # Compute overall severity and score
        score = 0.0
        max_sev = IncidentSeverity.UNKNOWN
        for signal in signals:
            hint = signal.severity_hint or IncidentSeverity.UNKNOWN
            score += _SEV_SCORE.get(hint, 0.0)
            if IncidentSeverity.rank(hint) > IncidentSeverity.rank(max_sev):
                max_sev = hint

        # Signal type breakdown
        signal_counts: Dict[str, int] = defaultdict(int)
        for s in signals:
            signal_counts[s.signal_type.value] += 1

        # Determine dominant signal types for summary text
        type_parts = ", ".join(
            f"{count} {stype}(s)"
            for stype, count in sorted(signal_counts.items())
        )
        summary_text = (
            f"Incident on {', '.join(affected_services[:3])}: "
            f"{max_sev.value.upper()} severity — {type_parts} "
            f"between {window_start.strftime('%H:%M:%S')} "
            f"and {window_end.strftime('%H:%M:%S')} UTC"
        )

        return IncidentSummary(
            incident_id=f"INC-{str(uuid.uuid4())[:8].upper()}",
            severity=max_sev,
            affected_services=affected_services,
            contributing_signals=sorted(signals, key=lambda s: s.timestamp),
            window_start=window_start,
            window_end=window_end,
            signal_counts=dict(signal_counts),
            score=score,
            summary_text=summary_text,
        )
