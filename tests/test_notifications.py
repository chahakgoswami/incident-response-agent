"""Tests for the Day-6 notification mock (event bus, channel, notifier)."""

from __future__ import annotations

import io
import uuid
from datetime import datetime, timezone
from typing import List

import pytest

from incident_agent.correlator.models import (
    CorrelatedSignal,
    IncidentSeverity,
    IncidentSummary,
    SignalType,
)
from incident_agent.notifications import (
    EventBus,
    SlackChannel,
    ChannelMessage,
    IncidentNotifier,
    get_default_bus,
)
from incident_agent.notifications.notifier import (
    EVENT_CORRELATION_SUMMARY,
    EVENT_POSTMORTEM_DRAFTED,
    EVENT_ROLLBACK_DECISION,
)
from incident_agent.postmortem.models import PostMortem, PostMortemSection
from incident_agent.rollback.models import (
    RollbackCommand,
    RollbackResult,
    RollbackStatus,
)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

BASE_TIME = datetime(2024, 1, 15, 12, 0, 0, tzinfo=timezone.utc)


def _make_summary(
    severity: IncidentSeverity = IncidentSeverity.HIGH,
    services: List[str] | None = None,
) -> IncidentSummary:
    services = services or ["api-gateway", "payment-service"]
    signal = CorrelatedSignal(
        signal_type=SignalType.ALERT,
        signal_id=str(uuid.uuid4()),
        service=services[0],
        timestamp=BASE_TIME,
        severity_hint=severity,
        description="Test signal description",
    )
    return IncidentSummary(
        incident_id=f"INC-{str(uuid.uuid4())[:8].upper()}",
        severity=severity,
        affected_services=services,
        contributing_signals=[signal],
        window_start=BASE_TIME,
        window_end=BASE_TIME,
        signal_counts={"alert": 1},
        score=10.0,
        summary_text="Test incident summary.",
    )


def _make_postmortem(incident_id: str | None = None) -> PostMortem:
    inc_id = incident_id or f"INC-{str(uuid.uuid4())[:8].upper()}"
    return PostMortem(
        incident_id=inc_id,
        title=f"Post-Mortem: HIGH Incident [{inc_id}]",
        generated_at=BASE_TIME,
        sections=[
            PostMortemSection(
                title="Executive Summary",
                content="A HIGH severity incident was detected affecting api-gateway.",
            ),
            PostMortemSection(
                title="Timeline",
                content="- 12:00:00 UTC — Alert fired\n- 12:05:00 UTC — Resolved",
            ),
            PostMortemSection(
                title="Root Cause Hypothesis",
                content="Bad deployment pushed to production.",
            ),
            PostMortemSection(
                title="Impact Estimate",
                content="~500 users affected for 5 minutes.",
            ),
            PostMortemSection(
                title="Action Items",
                content="1. Revert deployment.\n2. Add canary alerts.",
            ),
        ],
        raw_llm_output="{}",
        model_used="mock-stub",
    )


def _make_rollback_result(
    status: RollbackStatus = RollbackStatus.CONFIRMED,
    incident_id: str | None = None,
) -> RollbackResult:
    inc_id = incident_id or f"INC-{str(uuid.uuid4())[:8].upper()}"
    cmd = RollbackCommand(
        command_id="k8s-rollout-undo-api-gateway",
        description="Roll back api-gateway",
        command="kubectl rollout undo deployment/api-gateway -n production",
        pattern_tags=["error_surge"],
        service_hint="api-gateway",
        risk_level="low",
    )
    return RollbackResult(
        incident_id=inc_id,
        status=status,
        command=cmd if status != RollbackStatus.SKIPPED else None,
        decided_at=BASE_TIME,
        simulated_output="[SIMULATED] rolled back" if status == RollbackStatus.CONFIRMED else "",
    )


# ---------------------------------------------------------------------------
# EventBus tests
# ---------------------------------------------------------------------------


class TestEventBus:
    def test_new_bus_has_no_published_events(self):
        bus = EventBus()
        assert bus.published == []

    def test_publish_returns_envelope(self):
        bus = EventBus()
        env = bus.publish("test.event", {"key": "value"})
        assert env["event_type"] == "test.event"
        assert env["payload"] == {"key": "value"}
        assert "published_at" in env

    def test_published_list_grows(self):
        bus = EventBus()
        bus.publish("a")
        bus.publish("b")
        assert len(bus.published) == 2

    def test_events_of_type_filters_correctly(self):
        bus = EventBus()
        bus.publish("type.a", {"x": 1})
        bus.publish("type.b", {"x": 2})
        bus.publish("type.a", {"x": 3})
        result = bus.events_of_type("type.a")
        assert len(result) == 2
        assert all(e["event_type"] == "type.a" for e in result)

    def test_events_of_type_empty_for_unknown(self):
        bus = EventBus()
        bus.publish("some.event")
        assert bus.events_of_type("other.event") == []

    def test_subscribe_and_receive(self):
        bus = EventBus()
        received = []
        bus.subscribe("my.event", lambda e: received.append(e))
        bus.publish("my.event", {"val": 42})
        assert len(received) == 1
        assert received[0]["payload"]["val"] == 42

    def test_multiple_subscribers_all_notified(self):
        bus = EventBus()
        calls: list = []
        bus.subscribe("ev", lambda e: calls.append("h1"))
        bus.subscribe("ev", lambda e: calls.append("h2"))
        bus.publish("ev")
        assert calls == ["h1", "h2"]

    def test_unsubscribe_removes_handler(self):
        bus = EventBus()
        calls: list = []
        handler = lambda e: calls.append(1)  # noqa: E731
        bus.subscribe("ev", handler)
        bus.unsubscribe("ev", handler)
        bus.publish("ev")
        assert calls == []

    def test_unsubscribe_nonexistent_is_noop(self):
        bus = EventBus()
        # Should not raise
        bus.unsubscribe("nonexistent", lambda e: None)

    def test_subscribe_different_event_types(self):
        bus = EventBus()
        a_calls: list = []
        b_calls: list = []
        bus.subscribe("ev.a", lambda e: a_calls.append(1))
        bus.subscribe("ev.b", lambda e: b_calls.append(1))
        bus.publish("ev.a")
        assert a_calls == [1]
        assert b_calls == []

    def test_reset_clears_published_events(self):
        bus = EventBus()
        bus.publish("x")
        bus.publish("y")
        bus.reset()
        assert bus.published == []

    def test_reset_keeps_handlers(self):
        bus = EventBus()
        calls: list = []
        bus.subscribe("ev", lambda e: calls.append(1))
        bus.reset()
        bus.publish("ev")
        assert calls == [1]

    def test_publish_with_no_payload_uses_empty_dict(self):
        bus = EventBus()
        env = bus.publish("bare.event")
        assert env["payload"] == {}

    def test_published_returns_copy(self):
        bus = EventBus()
        bus.publish("ev")
        first = bus.published
        bus.publish("ev")
        second = bus.published
        # Should be independent copies
        assert len(first) == 1
        assert len(second) == 2

    def test_get_default_bus_returns_same_instance(self):
        b1 = get_default_bus()
        b2 = get_default_bus()
        assert b1 is b2

    def test_envelope_published_at_is_iso_string(self):
        bus = EventBus()
        env = bus.publish("ev")
        # Should be parseable as ISO datetime
        dt = datetime.fromisoformat(env["published_at"])
        assert dt.tzinfo is not None


# ---------------------------------------------------------------------------
# SlackChannel tests
# ---------------------------------------------------------------------------


class TestSlackChannel:
    def test_new_channel_has_no_messages(self):
        ch = SlackChannel("#test")
        assert len(ch.messages) == 0

    def test_post_returns_channel_message(self):
        ch = SlackChannel("#test")
        msg = ch.post("Hello world")
        assert isinstance(msg, ChannelMessage)

    def test_post_stores_message(self):
        ch = SlackChannel("#test")
        ch.post("Hello")
        assert len(ch.messages) == 1

    def test_post_stores_multiple_messages(self):
        ch = SlackChannel("#test")
        ch.post("msg1")
        ch.post("msg2")
        ch.post("msg3")
        assert len(ch) == 3

    def test_post_message_text_preserved(self):
        ch = SlackChannel("#test")
        msg = ch.post("Hello world")
        assert msg.text == "Hello world"

    def test_post_message_channel_matches(self):
        ch = SlackChannel("#incidents")
        msg = ch.post("Test")
        assert msg.channel == "#incidents"

    def test_post_message_author_default(self):
        ch = SlackChannel("#test")
        msg = ch.post("Test")
        assert msg.author == "incident-agent"

    def test_post_message_custom_author(self):
        ch = SlackChannel("#test")
        msg = ch.post("Test", author="rollback-bot")
        assert msg.author == "rollback-bot"

    def test_post_message_has_posted_at(self):
        ch = SlackChannel("#test")
        msg = ch.post("Test")
        assert isinstance(msg.posted_at, datetime)
        assert msg.posted_at.tzinfo is not None

    def test_post_echoes_to_output_stream(self):
        out = io.StringIO()
        ch = SlackChannel("#test", output_stream=out)
        ch.post("Hello")
        output = out.getvalue()
        assert "Hello" in output
        assert "#test" in output

    def test_post_no_echo_when_no_stream(self):
        # Should not raise
        ch = SlackChannel("#test", output_stream=None)
        msg = ch.post("Silent message")
        assert msg.text == "Silent message"

    def test_messages_containing_found(self):
        ch = SlackChannel("#test")
        ch.post("incident INC-12345 detected")
        ch.post("all systems nominal")
        results = ch.messages_containing("INC-12345")
        assert len(results) == 1

    def test_messages_containing_not_found(self):
        ch = SlackChannel("#test")
        ch.post("all systems nominal")
        results = ch.messages_containing("INC-XXXXX")
        assert results == []

    def test_clear_removes_all_messages(self):
        ch = SlackChannel("#test")
        ch.post("a")
        ch.post("b")
        ch.clear()
        assert len(ch.messages) == 0

    def test_messages_returns_copy(self):
        ch = SlackChannel("#test")
        ch.post("a")
        first = ch.messages
        ch.post("b")
        second = ch.messages
        assert len(first) == 1
        assert len(second) == 2

    def test_post_with_blocks(self):
        ch = SlackChannel("#test")
        blocks = [{"type": "section", "text": {"type": "mrkdwn", "text": "Hello"}}]
        msg = ch.post("Hello", blocks=blocks)
        assert msg.blocks == blocks

    def test_channel_message_render_contains_text(self):
        ch = SlackChannel("#test")
        msg = ch.post("Important alert")
        rendered = msg.render()
        assert "Important alert" in rendered

    def test_channel_message_render_contains_channel(self):
        ch = SlackChannel("#oncall")
        msg = ch.post("Test")
        rendered = msg.render()
        assert "#oncall" in rendered

    def test_channel_message_to_dict_keys(self):
        ch = SlackChannel("#test")
        msg = ch.post("Test message")
        d = msg.to_dict()
        for key in ("channel", "text", "posted_at", "author", "blocks"):
            assert key in d

    def test_channel_message_to_dict_channel_correct(self):
        ch = SlackChannel("#my-channel")
        msg = ch.post("Hi")
        assert msg.to_dict()["channel"] == "#my-channel"


# ---------------------------------------------------------------------------
# IncidentNotifier tests
# ---------------------------------------------------------------------------


class TestIncidentNotifier:
    def setup_method(self):
        self.bus = EventBus()
        self.channel = SlackChannel("#incidents", output_stream=io.StringIO())
        self.notifier = IncidentNotifier(channel=self.channel, bus=self.bus)

    # -- notify_correlation --

    def test_notify_correlation_posts_to_channel(self):
        summary = _make_summary()
        self.notifier.notify_correlation(summary)
        assert len(self.channel.messages) == 1

    def test_notify_correlation_message_contains_incident_id(self):
        summary = _make_summary()
        self.notifier.notify_correlation(summary)
        msg = self.channel.messages[0]
        assert summary.incident_id in msg.text

    def test_notify_correlation_message_contains_severity(self):
        summary = _make_summary(severity=IncidentSeverity.CRITICAL)
        self.notifier.notify_correlation(summary)
        assert self.channel.messages[0].text.find("CRITICAL") != -1

    def test_notify_correlation_message_contains_service(self):
        summary = _make_summary(services=["payment-service"])
        self.notifier.notify_correlation(summary)
        assert "payment-service" in self.channel.messages[0].text

    def test_notify_correlation_publishes_event(self):
        summary = _make_summary()
        self.notifier.notify_correlation(summary)
        events = self.bus.events_of_type(EVENT_CORRELATION_SUMMARY)
        assert len(events) == 1

    def test_notify_correlation_event_payload_has_incident_id(self):
        summary = _make_summary()
        self.notifier.notify_correlation(summary)
        event = self.bus.events_of_type(EVENT_CORRELATION_SUMMARY)[0]
        assert event["payload"]["incident_id"] == summary.incident_id

    def test_notify_correlation_event_payload_has_severity(self):
        summary = _make_summary(severity=IncidentSeverity.HIGH)
        self.notifier.notify_correlation(summary)
        event = self.bus.events_of_type(EVENT_CORRELATION_SUMMARY)[0]
        assert event["payload"]["severity"] == "high"

    def test_notify_correlation_event_payload_has_score(self):
        summary = _make_summary()
        self.notifier.notify_correlation(summary)
        event = self.bus.events_of_type(EVENT_CORRELATION_SUMMARY)[0]
        assert "score" in event["payload"]

    def test_notify_correlation_event_payload_has_signal_counts(self):
        summary = _make_summary()
        self.notifier.notify_correlation(summary)
        event = self.bus.events_of_type(EVENT_CORRELATION_SUMMARY)[0]
        assert "signal_counts" in event["payload"]

    def test_notify_correlation_author_is_correlation_engine(self):
        summary = _make_summary()
        self.notifier.notify_correlation(summary)
        assert self.channel.messages[0].author == "correlation-engine"

    # -- notify_postmortem --

    def test_notify_postmortem_posts_to_channel(self):
        pm = _make_postmortem()
        self.notifier.notify_postmortem(pm)
        assert len(self.channel.messages) == 1

    def test_notify_postmortem_message_contains_incident_id(self):
        pm = _make_postmortem("INC-TESTPOST")
        self.notifier.notify_postmortem(pm)
        assert "INC-TESTPOST" in self.channel.messages[0].text

    def test_notify_postmortem_message_contains_model_used(self):
        pm = _make_postmortem()
        self.notifier.notify_postmortem(pm)
        assert "mock-stub" in self.channel.messages[0].text

    def test_notify_postmortem_message_contains_section_titles(self):
        pm = _make_postmortem()
        self.notifier.notify_postmortem(pm)
        text = self.channel.messages[0].text
        assert "Executive Summary" in text

    def test_notify_postmortem_publishes_event(self):
        pm = _make_postmortem()
        self.notifier.notify_postmortem(pm)
        events = self.bus.events_of_type(EVENT_POSTMORTEM_DRAFTED)
        assert len(events) == 1

    def test_notify_postmortem_event_payload_has_incident_id(self):
        pm = _make_postmortem("INC-PMTEST")
        self.notifier.notify_postmortem(pm)
        event = self.bus.events_of_type(EVENT_POSTMORTEM_DRAFTED)[0]
        assert event["payload"]["incident_id"] == "INC-PMTEST"

    def test_notify_postmortem_event_payload_has_section_titles(self):
        pm = _make_postmortem()
        self.notifier.notify_postmortem(pm)
        event = self.bus.events_of_type(EVENT_POSTMORTEM_DRAFTED)[0]
        assert "section_titles" in event["payload"]
        assert isinstance(event["payload"]["section_titles"], list)
        assert "Executive Summary" in event["payload"]["section_titles"]

    def test_notify_postmortem_author_is_postmortem_bot(self):
        pm = _make_postmortem()
        self.notifier.notify_postmortem(pm)
        assert self.channel.messages[0].author == "postmortem-bot"

    def test_notify_postmortem_message_contains_excerpt(self):
        pm = _make_postmortem()
        self.notifier.notify_postmortem(pm)
        # The executive summary content should be partially included
        text = self.channel.messages[0].text
        assert "HIGH severity incident" in text or "api-gateway" in text

    # -- notify_rollback --

    def test_notify_rollback_confirmed_posts_to_channel(self):
        result = _make_rollback_result(RollbackStatus.CONFIRMED)
        self.notifier.notify_rollback(result)
        assert len(self.channel.messages) == 1

    def test_notify_rollback_confirmed_message_contains_status(self):
        result = _make_rollback_result(RollbackStatus.CONFIRMED)
        self.notifier.notify_rollback(result)
        assert "CONFIRMED" in self.channel.messages[0].text

    def test_notify_rollback_rejected_message_contains_status(self):
        result = _make_rollback_result(RollbackStatus.REJECTED)
        self.notifier.notify_rollback(result)
        assert "REJECTED" in self.channel.messages[0].text

    def test_notify_rollback_skipped_message_contains_status(self):
        result = _make_rollback_result(RollbackStatus.SKIPPED)
        self.notifier.notify_rollback(result)
        assert "SKIPPED" in self.channel.messages[0].text

    def test_notify_rollback_publishes_event(self):
        result = _make_rollback_result(RollbackStatus.CONFIRMED)
        self.notifier.notify_rollback(result)
        events = self.bus.events_of_type(EVENT_ROLLBACK_DECISION)
        assert len(events) == 1

    def test_notify_rollback_event_payload_has_status(self):
        result = _make_rollback_result(RollbackStatus.CONFIRMED)
        self.notifier.notify_rollback(result)
        event = self.bus.events_of_type(EVENT_ROLLBACK_DECISION)[0]
        assert event["payload"]["status"] == "confirmed"

    def test_notify_rollback_event_payload_has_incident_id(self):
        result = _make_rollback_result(RollbackStatus.CONFIRMED, incident_id="INC-RB001")
        self.notifier.notify_rollback(result)
        event = self.bus.events_of_type(EVENT_ROLLBACK_DECISION)[0]
        assert event["payload"]["incident_id"] == "INC-RB001"

    def test_notify_rollback_event_payload_has_command_id(self):
        result = _make_rollback_result(RollbackStatus.CONFIRMED)
        self.notifier.notify_rollback(result)
        event = self.bus.events_of_type(EVENT_ROLLBACK_DECISION)[0]
        assert event["payload"]["command_id"] == "k8s-rollout-undo-api-gateway"

    def test_notify_rollback_skipped_command_id_is_none(self):
        result = _make_rollback_result(RollbackStatus.SKIPPED)
        self.notifier.notify_rollback(result)
        event = self.bus.events_of_type(EVENT_ROLLBACK_DECISION)[0]
        assert event["payload"]["command_id"] is None

    def test_notify_rollback_author_is_rollback_bot(self):
        result = _make_rollback_result(RollbackStatus.CONFIRMED)
        self.notifier.notify_rollback(result)
        assert self.channel.messages[0].author == "rollback-bot"

    def test_notify_rollback_message_contains_command(self):
        result = _make_rollback_result(RollbackStatus.CONFIRMED)
        self.notifier.notify_rollback(result)
        assert "kubectl rollout undo" in self.channel.messages[0].text

    # -- full pipeline --

    def test_full_pipeline_posts_three_messages(self):
        summary = _make_summary()
        pm = _make_postmortem(summary.incident_id)
        result = _make_rollback_result(RollbackStatus.CONFIRMED, summary.incident_id)

        self.notifier.notify_correlation(summary)
        self.notifier.notify_postmortem(pm)
        self.notifier.notify_rollback(result)

        assert len(self.channel.messages) == 3

    def test_full_pipeline_publishes_three_events(self):
        summary = _make_summary()
        pm = _make_postmortem(summary.incident_id)
        result = _make_rollback_result(RollbackStatus.CONFIRMED, summary.incident_id)

        self.notifier.notify_correlation(summary)
        self.notifier.notify_postmortem(pm)
        self.notifier.notify_rollback(result)

        assert len(self.bus.published) == 3

    def test_full_pipeline_event_types_correct(self):
        summary = _make_summary()
        pm = _make_postmortem(summary.incident_id)
        result = _make_rollback_result(RollbackStatus.CONFIRMED, summary.incident_id)

        self.notifier.notify_correlation(summary)
        self.notifier.notify_postmortem(pm)
        self.notifier.notify_rollback(result)

        event_types = [e["event_type"] for e in self.bus.published]
        assert EVENT_CORRELATION_SUMMARY in event_types
        assert EVENT_POSTMORTEM_DRAFTED in event_types
        assert EVENT_ROLLBACK_DECISION in event_types


# ---------------------------------------------------------------------------
# Integration with real correlator + postmortem
# ---------------------------------------------------------------------------


class TestNotifierIntegration:
    def test_notify_real_correlation_summary(self):
        from incident_agent.correlator import CorrelationEngine
        from incident_agent.mock_data import generate_incident_scenario
        from incident_agent.mock_data.scenario import ScenarioType

        bus = EventBus()
        channel = SlackChannel("#incidents", output_stream=io.StringIO())
        notifier = IncidentNotifier(channel=channel, bus=bus)

        scenario = generate_incident_scenario(scenario_type=ScenarioType.ERROR_SURGE, seed=42)
        engine = CorrelationEngine()
        summaries = engine.correlate_scenario(scenario)
        assert len(summaries) >= 1

        notifier.notify_correlation(summaries[0])
        assert len(channel.messages) >= 1
        assert len(bus.events_of_type(EVENT_CORRELATION_SUMMARY)) == 1

    def test_notify_real_postmortem(self):
        from incident_agent.correlator import CorrelationEngine
        from incident_agent.mock_data import generate_incident_scenario
        from incident_agent.mock_data.scenario import ScenarioType
        from incident_agent.postmortem import PostMortemDrafter

        bus = EventBus()
        channel = SlackChannel("#incidents", output_stream=io.StringIO())
        notifier = IncidentNotifier(channel=channel, bus=bus)

        scenario = generate_incident_scenario(scenario_type=ScenarioType.CPU_SPIKE, seed=7)
        engine = CorrelationEngine()
        summaries = engine.correlate_scenario(scenario)

        drafter = PostMortemDrafter(force_mock=True)
        pm = drafter.draft(summaries[0])

        notifier.notify_postmortem(pm)
        assert len(channel.messages) == 1
        assert len(bus.events_of_type(EVENT_POSTMORTEM_DRAFTED)) == 1

    def test_subscriber_receives_correlation_event(self):
        from incident_agent.correlator import CorrelationEngine
        from incident_agent.mock_data import generate_incident_scenario
        from incident_agent.mock_data.scenario import ScenarioType

        bus = EventBus()
        channel = SlackChannel("#incidents")
        notifier = IncidentNotifier(channel=channel, bus=bus)

        received_events: list = []
        bus.subscribe(EVENT_CORRELATION_SUMMARY, lambda e: received_events.append(e))

        scenario = generate_incident_scenario(scenario_type=ScenarioType.MIXED, seed=99)
        engine = CorrelationEngine()
        summaries = engine.correlate_scenario(scenario)

        for summary in summaries:
            notifier.notify_correlation(summary)

        assert len(received_events) == len(summaries)
        assert all(
            e["event_type"] == EVENT_CORRELATION_SUMMARY for e in received_events
        )

    def test_channel_messages_containing_incident_id(self):
        bus = EventBus()
        channel = SlackChannel("#incidents")
        notifier = IncidentNotifier(channel=channel, bus=bus)

        summary = _make_summary()
        notifier.notify_correlation(summary)

        found = channel.messages_containing(summary.incident_id)
        assert len(found) == 1
