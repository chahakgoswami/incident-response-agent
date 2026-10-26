"""Simulated distributed trace generator for incident scenarios."""

from __future__ import annotations

import random
import uuid
from dataclasses import dataclass, field
from datetime import datetime, timedelta, timezone
from enum import Enum
from typing import List, Optional


class SpanStatus(str, Enum):
    OK = "ok"
    ERROR = "error"
    TIMEOUT = "timeout"


@dataclass
class Span:
    """A single span within a distributed trace."""

    span_id: str
    parent_span_id: Optional[str]
    operation: str
    service: str
    status: SpanStatus
    duration_ms: float
    start_time: datetime
    error_message: Optional[str] = None
    tags: dict = field(default_factory=dict)

    def to_dict(self) -> dict:
        return {
            "span_id": self.span_id,
            "parent_span_id": self.parent_span_id,
            "operation": self.operation,
            "service": self.service,
            "status": self.status.value,
            "duration_ms": self.duration_ms,
            "start_time": self.start_time.isoformat(),
            "error_message": self.error_message,
            "tags": self.tags,
        }


@dataclass
class Trace:
    """A complete distributed trace composed of multiple spans."""

    trace_id: str
    root_service: str
    spans: List[Span] = field(default_factory=list)
    start_time: datetime = field(default_factory=lambda: datetime.now(tz=timezone.utc))

    @property
    def total_duration_ms(self) -> float:
        if not self.spans:
            return 0.0
        return sum(s.duration_ms for s in self.spans)

    @property
    def has_errors(self) -> bool:
        return any(s.status in (SpanStatus.ERROR, SpanStatus.TIMEOUT) for s in self.spans)

    @property
    def affected_services(self) -> List[str]:
        return list({s.service for s in self.spans})

    def to_dict(self) -> dict:
        return {
            "trace_id": self.trace_id,
            "root_service": self.root_service,
            "start_time": self.start_time.isoformat(),
            "total_duration_ms": self.total_duration_ms,
            "has_errors": self.has_errors,
            "affected_services": self.affected_services,
            "spans": [s.to_dict() for s in self.spans],
        }


# ---------------------------------------------------------------------------
# Internal helpers
# ---------------------------------------------------------------------------

_OPERATIONS = [
    "HTTP GET /api/v1/users",
    "HTTP POST /api/v1/payments",
    "HTTP GET /api/v1/recommendations",
    "DB SELECT users",
    "DB UPDATE inventory",
    "Cache GET session",
    "gRPC AuthService/ValidateToken",
    "Queue publish order.created",
    "HTTP GET /health",
]

_ERROR_MESSAGES = [
    "connection refused: downstream service unavailable",
    "context deadline exceeded after 5000ms",
    "unexpected status 500: internal server error",
    "database connection pool exhausted",
    "redis NOAUTH Authentication required",
    "circuit breaker OPEN — too many failures",
    "OOM killed: container exceeded memory limit",
]

_SERVICES = [
    "api-gateway",
    "auth-service",
    "payment-service",
    "user-service",
    "recommendation-engine",
    "inventory-service",
]


class TraceGenerator:
    """Generates realistic in-memory distributed traces for simulated incidents."""

    def __init__(self, seed: Optional[int] = None) -> None:
        self._rng = random.Random(seed)

    # ------------------------------------------------------------------
    # Internal builders
    # ------------------------------------------------------------------

    def _make_span(
        self,
        service: str,
        operation: str,
        start_time: datetime,
        parent_span_id: Optional[str] = None,
        status: SpanStatus = SpanStatus.OK,
        duration_ms: Optional[float] = None,
        error_message: Optional[str] = None,
    ) -> Span:
        if duration_ms is None:
            duration_ms = self._rng.uniform(5.0, 200.0)
        return Span(
            span_id=str(uuid.uuid4()),
            parent_span_id=parent_span_id,
            operation=operation,
            service=service,
            status=status,
            duration_ms=round(duration_ms, 2),
            start_time=start_time,
            error_message=error_message,
            tags={"env": "production"},
        )

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    def generate_normal_traces(
        self,
        count: int = 5,
        base_time: Optional[datetime] = None,
        services: Optional[List[str]] = None,
    ) -> List[Trace]:
        """Generate traces that represent healthy baseline traffic."""
        base_time = base_time or datetime.now(tz=timezone.utc)
        services = services or _SERVICES
        traces: List[Trace] = []
        for i in range(count):
            root_svc = self._rng.choice(services)
            trace_start = base_time + timedelta(milliseconds=i * 200)
            trace = Trace(
                trace_id=str(uuid.uuid4()),
                root_service=root_svc,
                start_time=trace_start,
            )
            root_span = self._make_span(
                service=root_svc,
                operation=self._rng.choice(_OPERATIONS),
                start_time=trace_start,
                duration_ms=self._rng.uniform(30.0, 180.0),
            )
            trace.spans.append(root_span)
            # Add 1-3 child spans
            for _ in range(self._rng.randint(1, 3)):
                child_svc = self._rng.choice(services)
                child_start = trace_start + timedelta(milliseconds=self._rng.uniform(5, 50))
                trace.spans.append(
                    self._make_span(
                        service=child_svc,
                        operation=self._rng.choice(_OPERATIONS),
                        start_time=child_start,
                        parent_span_id=root_span.span_id,
                        duration_ms=self._rng.uniform(5.0, 80.0),
                    )
                )
            traces.append(trace)
        return traces

    def generate_high_latency_traces(
        self,
        services: Optional[List[str]] = None,
        base_time: Optional[datetime] = None,
        count: int = 5,
    ) -> List[Trace]:
        """Generate traces with latency outliers (slow spans)."""
        base_time = base_time or datetime.now(tz=timezone.utc)
        services = services or self._rng.sample(_SERVICES, k=min(3, len(_SERVICES)))
        traces: List[Trace] = []
        for i in range(count):
            root_svc = self._rng.choice(services)
            trace_start = base_time + timedelta(seconds=i * 2)
            trace = Trace(
                trace_id=str(uuid.uuid4()),
                root_service=root_svc,
                start_time=trace_start,
            )
            # Root span is slow
            root_span = self._make_span(
                service=root_svc,
                operation=self._rng.choice(_OPERATIONS),
                start_time=trace_start,
                duration_ms=self._rng.uniform(1200.0, 8000.0),
            )
            trace.spans.append(root_span)
            # Child spans — at least one is also slow
            for j in range(self._rng.randint(2, 4)):
                child_svc = self._rng.choice(services)
                child_start = trace_start + timedelta(milliseconds=50 * j)
                child_duration = (
                    self._rng.uniform(800.0, 3000.0)
                    if j == 0
                    else self._rng.uniform(10.0, 100.0)
                )
                trace.spans.append(
                    self._make_span(
                        service=child_svc,
                        operation=self._rng.choice(_OPERATIONS),
                        start_time=child_start,
                        parent_span_id=root_span.span_id,
                        duration_ms=child_duration,
                    )
                )
            traces.append(trace)
        return traces

    def generate_error_traces(
        self,
        services: Optional[List[str]] = None,
        base_time: Optional[datetime] = None,
        count: int = 5,
    ) -> List[Trace]:
        """Generate traces where spans are failing with errors/timeouts."""
        base_time = base_time or datetime.now(tz=timezone.utc)
        services = services or self._rng.sample(_SERVICES, k=min(3, len(_SERVICES)))
        traces: List[Trace] = []
        for i in range(count):
            root_svc = self._rng.choice(services)
            trace_start = base_time + timedelta(seconds=i * 1)
            trace = Trace(
                trace_id=str(uuid.uuid4()),
                root_service=root_svc,
                start_time=trace_start,
            )
            error_status = self._rng.choice([SpanStatus.ERROR, SpanStatus.TIMEOUT])
            root_span = self._make_span(
                service=root_svc,
                operation=self._rng.choice(_OPERATIONS),
                start_time=trace_start,
                status=error_status,
                duration_ms=self._rng.uniform(100.0, 5000.0),
                error_message=self._rng.choice(_ERROR_MESSAGES),
            )
            trace.spans.append(root_span)
            for j in range(self._rng.randint(1, 3)):
                child_svc = self._rng.choice(services)
                child_start = trace_start + timedelta(milliseconds=20 * j)
                child_status = (
                    self._rng.choice([SpanStatus.ERROR, SpanStatus.TIMEOUT])
                    if self._rng.random() > 0.5
                    else SpanStatus.OK
                )
                trace.spans.append(
                    self._make_span(
                        service=child_svc,
                        operation=self._rng.choice(_OPERATIONS),
                        start_time=child_start,
                        parent_span_id=root_span.span_id,
                        status=child_status,
                        duration_ms=self._rng.uniform(50.0, 2000.0),
                        error_message=(
                            self._rng.choice(_ERROR_MESSAGES)
                            if child_status != SpanStatus.OK
                            else None
                        ),
                    )
                )
            traces.append(trace)
        return traces

    def generate_mixed_incident_traces(
        self,
        services: Optional[List[str]] = None,
        base_time: Optional[datetime] = None,
    ) -> List[Trace]:
        """Generate a realistic mixed trace stream for an incident window."""
        base_time = base_time or datetime.now(tz=timezone.utc)
        services = services or self._rng.sample(_SERVICES, k=3)
        return (
            self.generate_normal_traces(count=3, base_time=base_time, services=services)
            + self.generate_high_latency_traces(services=services, base_time=base_time, count=4)
            + self.generate_error_traces(services=services, base_time=base_time, count=4)
        )
