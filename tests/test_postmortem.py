"""Tests for the Day-3 post-mortem drafter."""

from __future__ import annotations

import json
import uuid
from datetime import datetime, timezone

import pytest

from incident_agent.correlator.models import (
    CorrelatedSignal,
    IncidentSeverity,
    IncidentSummary,
    SignalType,
)
from incident_agent.postmortem import PostMortemDrafter
from incident_agent.postmortem.models import PostMortem, PostMortemSection


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

BASE_TIME = datetime(2024, 1, 15, 12, 0, 0, tzinfo=timezone.utc)


def _make_signal(
    signal_type: SignalType,
    service: str = "api-gateway",
    severity: IncidentSeverity = IncidentSeverity.HIGH,
    description: str = "Test signal",
    offset_seconds: int = 0,
) -> CorrelatedSignal:
    from datetime import timedelta

    return CorrelatedSignal(
        signal_type=signal_type,
        signal_id=str(uuid.uuid4()),
        service=service,
        timestamp=BASE_TIME + timedelta(seconds=offset_seconds),
        severity_hint=severity,
        description=description,
    )


def _make_summary(
    severity: IncidentSeverity = IncidentSeverity.HIGH,
    services: list[str] | None = None,
    num_signals: int = 3,
) -> IncidentSummary:
    services = services or ["api-gateway", "payment-service"]
    signals = [
        _make_signal(SignalType.ALERT, service=services[0], offset_seconds=i * 10)
        for i in range(num_signals)
    ]
    return IncidentSummary(
        incident_id=f"INC-{str(uuid.uuid4())[:8].upper()}",
        severity=severity,
        affected_services=services,
        contributing_signals=signals,
        window_start=BASE_TIME,
        window_end=signals[-1].timestamp,
        signal_counts={"alert": num_signals},
        score=float(num_signals * 5),
        summary_text=f"Test incident on {services[0]}: {severity.value} severity.",
    )


# ---------------------------------------------------------------------------
# PostMortemDrafter (force_mock=True)
# ---------------------------------------------------------------------------


class TestPostMortemDrafterMock:
    def setup_method(self):
        self.drafter = PostMortemDrafter(force_mock=True)

    def test_draft_returns_postmortem_instance(self):
        summary = _make_summary()
        pm = self.drafter.draft(summary)
        assert isinstance(pm, PostMortem)

    def test_draft_incident_id_matches(self):
        summary = _make_summary()
        pm = self.drafter.draft(summary)
        assert pm.incident_id == summary.incident_id

    def test_draft_model_used_is_mock_stub(self):
        summary = _make_summary()
        pm = self.drafter.draft(summary)
        assert "mock" in pm.model_used.lower()

    def test_draft_has_five_sections(self):
        summary = _make_summary()
        pm = self.drafter.draft(summary)
        assert len(pm.sections) == 5

    def test_draft_has_executive_summary_section(self):
        summary = _make_summary()
        pm = self.drafter.draft(summary)
        sec = pm.get_section("Executive Summary")
        assert sec is not None
        assert len(sec.content) > 0

    def test_draft_has_timeline_section(self):
        summary = _make_summary()
        pm = self.drafter.draft(summary)
        sec = pm.get_section("Timeline")
        assert sec is not None
        assert len(sec.content) > 0

    def test_draft_has_root_cause_section(self):
        summary = _make_summary()
        pm = self.drafter.draft(summary)
        sec = pm.get_section("Root Cause Hypothesis")
        assert sec is not None
        assert len(sec.content) > 0

    def test_draft_has_impact_estimate_section(self):
        summary = _make_summary()
        pm = self.drafter.draft(summary)
        sec = pm.get_section("Impact Estimate")
        assert sec is not None
        assert len(sec.content) > 0

    def test_draft_has_action_items_section(self):
        summary = _make_summary()
        pm = self.drafter.draft(summary)
        sec = pm.get_section("Action Items")
        assert sec is not None
        assert len(sec.content) > 0

    def test_draft_title_contains_incident_id(self):
        summary = _make_summary()
        pm = self.drafter.draft(summary)
        assert summary.incident_id in pm.title

    def test_draft_generated_at_is_recent(self):
        from datetime import timedelta

        summary = _make_summary()
        pm = self.drafter.draft(summary)
        now = datetime.now(tz=timezone.utc)
        assert abs((now - pm.generated_at).total_seconds()) < 10

    def test_raw_llm_output_is_valid_json(self):
        summary = _make_summary()
        pm = self.drafter.draft(summary)
        data = json.loads(pm.raw_llm_output)
        assert "title" in data
        assert "sections" in data

    def test_critical_severity_mentioned_in_summary(self):
        summary = _make_summary(severity=IncidentSeverity.CRITICAL)
        pm = self.drafter.draft(summary)
        exec_summary = pm.get_section("Executive Summary")
        assert exec_summary is not None
        assert "CRITICAL" in exec_summary.content

    def test_affected_services_mentioned(self):
        services = ["payment-service", "auth-service"]
        summary = _make_summary(services=services)
        pm = self.drafter.draft(summary)
        exec_summary = pm.get_section("Executive Summary")
        assert exec_summary is not None
        # At least one service should be mentioned
        assert any(svc in exec_summary.content for svc in services)

    def test_timeline_has_bullet_points(self):
        summary = _make_summary(num_signals=3)
        pm = self.drafter.draft(summary)
        timeline = pm.get_section("Timeline")
        assert timeline is not None
        assert "-" in timeline.content

    def test_action_items_has_multiple_items(self):
        summary = _make_summary()
        pm = self.drafter.draft(summary)
        actions = pm.get_section("Action Items")
        assert actions is not None
        # Expect numbered list items
        assert "1." in actions.content
        assert "2." in actions.content


# ---------------------------------------------------------------------------
# PostMortem model tests
# ---------------------------------------------------------------------------


class TestPostMortemModel:
    def _make_postmortem(self) -> PostMortem:
        sections = [
            PostMortemSection(title="Executive Summary", content="Overview text."),
            PostMortemSection(title="Timeline", content="- 12:00 Event A\n- 12:05 Event B"),
        ]
        return PostMortem(
            incident_id="INC-ABCD1234",
            title="Test Post-Mortem",
            generated_at=BASE_TIME,
            sections=sections,
            raw_llm_output="{}",
            model_used="mock-stub",
        )

    def test_get_section_found(self):
        pm = self._make_postmortem()
        sec = pm.get_section("Executive Summary")
        assert sec is not None
        assert sec.content == "Overview text."

    def test_get_section_case_insensitive(self):
        pm = self._make_postmortem()
        sec = pm.get_section("executive summary")
        assert sec is not None

    def test_get_section_not_found(self):
        pm = self._make_postmortem()
        assert pm.get_section("Nonexistent") is None

    def test_to_dict_contains_required_keys(self):
        pm = self._make_postmortem()
        d = pm.to_dict()
        for key in ("incident_id", "title", "generated_at", "model_used", "sections"):
            assert key in d

    def test_to_dict_sections_is_list(self):
        pm = self._make_postmortem()
        assert isinstance(pm.to_dict()["sections"], list)

    def test_render_markdown_contains_title(self):
        pm = self._make_postmortem()
        md = pm.render_markdown()
        assert "# Test Post-Mortem" in md

    def test_render_markdown_contains_incident_id(self):
        pm = self._make_postmortem()
        md = pm.render_markdown()
        assert "INC-ABCD1234" in md

    def test_render_markdown_contains_section_headings(self):
        pm = self._make_postmortem()
        md = pm.render_markdown()
        assert "## Executive Summary" in md
        assert "## Timeline" in md


# ---------------------------------------------------------------------------
# Parse-error fallback
# ---------------------------------------------------------------------------


class TestPostMortemParseErrorFallback:
    def test_invalid_json_produces_fallback_section(self):
        drafter = PostMortemDrafter(force_mock=True)
        summary = _make_summary()
        # Monkey-patch the mock to return garbage
        drafter._call_mock = lambda s: "this is not json {{{{"  # type: ignore[method-assign]
        pm = drafter.draft(summary)
        assert len(pm.sections) == 1
        assert pm.sections[0].title == "Raw LLM Output"

    def test_missing_sections_key_produces_fallback(self):
        drafter = PostMortemDrafter(force_mock=True)
        summary = _make_summary()
        drafter._call_mock = lambda s: json.dumps({"title": "T", "sections": []})  # type: ignore[method-assign]
        pm = drafter.draft(summary)
        # Empty sections list → fallback
        assert pm.sections[0].title == "Raw LLM Output"


# ---------------------------------------------------------------------------
# Integration: correlator → drafter
# ---------------------------------------------------------------------------


class TestPostMortemIntegration:
    def test_full_pipeline_cpu_spike(self):
        from incident_agent.correlator import CorrelationEngine
        from incident_agent.mock_data import generate_incident_scenario
        from incident_agent.mock_data.scenario import ScenarioType

        scenario = generate_incident_scenario(scenario_type=ScenarioType.CPU_SPIKE, seed=42)
        engine = CorrelationEngine()
        summaries = engine.correlate_scenario(scenario)
        assert len(summaries) >= 1

        drafter = PostMortemDrafter(force_mock=True)
        pm = drafter.draft(summaries[0])
        assert pm.incident_id == summaries[0].incident_id
        assert len(pm.sections) >= 1
        assert pm.render_markdown().startswith("#")

    def test_full_pipeline_error_surge(self):
        from incident_agent.correlator import CorrelationEngine
        from incident_agent.mock_data import generate_incident_scenario
        from incident_agent.mock_data.scenario import ScenarioType

        scenario = generate_incident_scenario(scenario_type=ScenarioType.ERROR_SURGE, seed=7)
        engine = CorrelationEngine()
        summaries = engine.correlate_scenario(scenario)
        drafter = PostMortemDrafter(force_mock=True)
        pm = drafter.draft(summaries[0])
        md = pm.render_markdown()
        assert "Root Cause Hypothesis" in md
        assert "Action Items" in md

    def test_to_dict_is_json_serializable(self):
        import json

        from incident_agent.correlator import CorrelationEngine
        from incident_agent.mock_data import generate_incident_scenario
        from incident_agent.mock_data.scenario import ScenarioType

        scenario = generate_incident_scenario(scenario_type=ScenarioType.MIXED, seed=99)
        engine = CorrelationEngine()
        summaries = engine.correlate_scenario(scenario)
        drafter = PostMortemDrafter(force_mock=True)
        pm = drafter.draft(summaries[0])
        serialized = json.dumps(pm.to_dict())
        assert len(serialized) > 0
