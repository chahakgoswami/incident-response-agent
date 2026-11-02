"""In-process event bus for Slack-style notification mocking."""

from __future__ import annotations

from datetime import datetime, timezone
from typing import Any, Callable, Dict, List, Optional


class EventBus:
    """
    A simple synchronous in-process event bus.

    Subscribers register a callable for a named event type.  When an event is
    published all registered handlers are called in registration order.

    This is intentionally simple — no threads, no external dependencies.
    """

    def __init__(self) -> None:
        self._handlers: Dict[str, List[Callable[[dict], None]]] = {}
        self._published: List[dict] = []

    # ------------------------------------------------------------------
    # Subscription
    # ------------------------------------------------------------------

    def subscribe(self, event_type: str, handler: Callable[[dict], None]) -> None:
        """Register *handler* for *event_type*."""
        self._handlers.setdefault(event_type, []).append(handler)

    def unsubscribe(self, event_type: str, handler: Callable[[dict], None]) -> None:
        """Remove *handler* from *event_type* (no-op if not registered)."""
        handlers = self._handlers.get(event_type, [])
        if handler in handlers:
            handlers.remove(handler)

    # ------------------------------------------------------------------
    # Publishing
    # ------------------------------------------------------------------

    def publish(self, event_type: str, payload: Optional[dict] = None) -> dict:
        """
        Publish an event with an optional payload dict.

        The event envelope is stored internally (accessible via
        :attr:`published`) and returned.  All registered handlers are
        called synchronously before this method returns.

        Returns the complete event envelope.
        """
        envelope = {
            "event_type": event_type,
            "published_at": datetime.now(tz=timezone.utc).isoformat(),
            "payload": payload or {},
        }
        self._published.append(envelope)
        for handler in self._handlers.get(event_type, []):
            try:
                handler(envelope)
            except Exception:  # pragma: no cover
                pass  # handlers must not crash the bus
        return envelope

    # ------------------------------------------------------------------
    # Inspection
    # ------------------------------------------------------------------

    @property
    def published(self) -> List[dict]:
        """All events published since the bus was created (or last reset)."""
        return list(self._published)

    def events_of_type(self, event_type: str) -> List[dict]:
        """Return all published envelopes matching *event_type*."""
        return [e for e in self._published if e["event_type"] == event_type]

    def reset(self) -> None:
        """Clear all published events (handlers are kept)."""
        self._published.clear()


# ---------------------------------------------------------------------------
# Module-level default bus
# ---------------------------------------------------------------------------

_default_bus: Optional[EventBus] = None


def get_default_bus() -> EventBus:
    """Return (and lazily create) the module-level default EventBus."""
    global _default_bus
    if _default_bus is None:
        _default_bus = EventBus()
    return _default_bus
