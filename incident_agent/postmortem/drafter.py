"""LLM-backed post-mortem drafter with a local stub fallback."""

from __future__ import annotations

import json
import os
import re
from datetime import datetime, timezone
from typing import List, Optional

from incident_agent.correlator.models import IncidentSummary, IncidentSeverity

from .models import PostMortem, PostMortemSection

# ---------------------------------------------------------------------------
# Prompt template
# ---------------------------------------------------------------------------

_SYSTEM_PROMPT = """\
You are an expert site-reliability engineer writing a structured post-mortem document.
Respond ONLY with valid JSON matching this exact schema (no markdown fences, no extra keys):

{
  "title": "<short incident title>",
  "sections": [
    {"title": "Executive Summary",      "content": "..."},
    {"title": "Timeline",               "content": "..."},
    {"title": "Root Cause Hypothesis",  "content": "..."},
    {"title": "Impact Estimate",        "content": "..."},
    {"title": "Action Items",           "content": "..."}
  ]
}

Guidelines:
- Timeline: bullet-point chronology derived from the signal timestamps.
- Root Cause Hypothesis: plausible technical explanation based on signal patterns.
- Impact Estimate: affected users / services / SLOs; quantify where possible.
- Action Items: 3-5 concrete remediation tasks.
- Be concise but specific. Use the signal data provided.
"""

_USER_PROMPT_TEMPLATE = """\
Please draft a post-mortem for the following correlated incident.

Incident ID : {incident_id}
Severity    : {severity}
Services    : {services}
Window      : {window_start} — {window_end} UTC
Signal counts: {signal_counts}

Top contributing signals (up to 10):
{signals_block}

Summary: {summary_text}
"""


class PostMortemDrafter:
    """
    Drafts a structured post-mortem document from an :class:`IncidentSummary`.

    Resolution order for the LLM backend:
    1. Real OpenAI-compatible API if ``OPENAI_API_KEY`` is set in the environment.
    2. Local mock/stub that produces a realistic deterministic document.

    Parameters
    ----------
    model        : OpenAI model name (default ``gpt-4o-mini``).
    api_base_url : Override the OpenAI base URL (e.g. for local proxies).
    force_mock   : Skip the real API even if a key is present (useful in tests).
    """

    def __init__(
        self,
        model: str = "gpt-4o-mini",
        api_base_url: Optional[str] = None,
        force_mock: bool = False,
    ) -> None:
        self.model = model
        self.api_base_url = api_base_url or "https://api.openai.com/v1"
        self.force_mock = force_mock
        self._api_key: Optional[str] = os.environ.get("OPENAI_API_KEY")

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    def draft(self, summary: IncidentSummary) -> PostMortem:
        """
        Generate a post-mortem for the given incident summary.

        Returns a :class:`PostMortem` built from either the real LLM response
        or the local mock stub.
        """
        user_prompt = self._build_user_prompt(summary)

        if not self.force_mock and self._api_key:
            try:
                raw_output, model_id = self._call_openai(user_prompt)
            except Exception as exc:  # pragma: no cover
                # Fall back to mock on any API error
                raw_output, model_id = self._call_mock(summary), "mock-fallback"
        else:
            raw_output, model_id = self._call_mock(summary), "mock-stub"

        sections, title = self._parse_llm_output(raw_output, summary)

        return PostMortem(
            incident_id=summary.incident_id,
            title=title,
            generated_at=datetime.now(tz=timezone.utc),
            sections=sections,
            raw_llm_output=raw_output,
            model_used=model_id,
        )

    # ------------------------------------------------------------------
    # Prompt construction
    # ------------------------------------------------------------------

    @staticmethod
    def _build_user_prompt(summary: IncidentSummary) -> str:
        top_signals = summary.contributing_signals[:10]
        signals_block = "\n".join(
            f"  [{i+1}] {s.signal_type.value.upper()} | {s.service} | "
            f"{s.timestamp.strftime('%H:%M:%S')} | {s.description[:120]}"
            for i, s in enumerate(top_signals)
        )
        return _USER_PROMPT_TEMPLATE.format(
            incident_id=summary.incident_id,
            severity=summary.severity.value.upper(),
            services=", ".join(summary.affected_services),
            window_start=summary.window_start.strftime("%Y-%m-%d %H:%M:%S"),
            window_end=summary.window_end.strftime("%Y-%m-%d %H:%M:%S"),
            signal_counts=json.dumps(summary.signal_counts),
            signals_block=signals_block,
            summary_text=summary.summary_text,
        )

    # ------------------------------------------------------------------
    # LLM call
    # ------------------------------------------------------------------

    def _call_openai(self, user_prompt: str) -> tuple[str, str]:
        """Make a real OpenAI-compatible chat completion request."""
        # Import lazily so the package works without openai installed
        try:
            import openai  # type: ignore
        except ImportError as exc:
            raise RuntimeError(
                "openai package not installed. Run: pip install openai"
            ) from exc

        client = openai.OpenAI(
            api_key=self._api_key,
            base_url=self.api_base_url,
        )
        response = client.chat.completions.create(
            model=self.model,
            messages=[
                {"role": "system", "content": _SYSTEM_PROMPT},
                {"role": "user", "content": user_prompt},
            ],
            temperature=0.3,
            max_tokens=1200,
        )
        raw = response.choices[0].message.content or ""
        return raw, response.model

    # ------------------------------------------------------------------
    # Mock / stub
    # ------------------------------------------------------------------

    def _call_mock(self, summary: IncidentSummary) -> str:
        """
        Produce a deterministic mock LLM response as a JSON string.

        The stub generates a realistic post-mortem by inspecting the
        IncidentSummary fields directly — no network call required.
        """
        services = ", ".join(summary.affected_services[:3])
        sev = summary.severity.value.upper()
        window_s = summary.window_start.strftime("%H:%M:%S")
        window_e = summary.window_end.strftime("%H:%M:%S")
        incident_id = summary.incident_id

        # Build a timeline from the first 8 signals
        timeline_items = []
        for sig in summary.contributing_signals[:8]:
            ts = sig.timestamp.strftime("%H:%M:%S")
            timeline_items.append(
                f"- {ts} UTC — {sig.signal_type.value.upper()} on {sig.service}: "
                f"{sig.description[:100]}"
            )
        timeline = "\n".join(timeline_items) if timeline_items else "- No signals recorded."

        # Root-cause hypothesis based on dominant signal types
        alert_count = summary.signal_counts.get("alert", 0)
        trace_count = summary.signal_counts.get("trace", 0)
        log_count = summary.signal_counts.get("log", 0)

        if alert_count >= trace_count and alert_count >= log_count:
            root_cause = (
                f"Monitoring alerts on {services} fired simultaneously, suggesting a "
                "sudden traffic surge or a runaway process that saturated compute "
                "resources. The correlated alert pattern indicates a systemic issue "
                "rather than an isolated blip."
            )
        elif trace_count >= log_count:
            root_cause = (
                f"Distributed traces reveal cascading failures originating in {services}. "
                "Error and timeout spans propagated upstream, consistent with a "
                "downstream dependency failure or a database connection pool exhaustion."
            )
        else:
            root_cause = (
                f"Log analysis on {services} shows elevated error and warning rates "
                "throughout the window. The pattern is consistent with a bad deployment "
                "introducing a regression, or an external dependency becoming unavailable."
            )

        # Impact estimate
        total_signals = len(summary.contributing_signals)
        impact = (
            f"Severity: {sev}. Approximately {total_signals} observability signals "
            f"were triggered across {len(summary.affected_services)} service(s) "
            f"({services}) between {window_s} and {window_e} UTC. "
            "Assuming p99 latency SLO of 500 ms and error-rate SLO of 1%, both SLOs "
            "were likely breached during this window. User-facing impact is estimated "
            "as partial service degradation; complete outage scope requires manual review."
        )

        # Action items
        actions = (
            "1. Identify and revert the most recent deployment to the affected services.\n"
            "2. Examine database connection pool settings and increase pool size if exhausted.\n"
            "3. Review auto-scaling policies to ensure capacity responds faster to traffic spikes.\n"
            "4. Add canary alerting rules that trigger before SLOs are fully breached.\n"
            "5. Schedule a blameless post-mortem review within 48 hours with all on-call engineers."
        )

        doc = {
            "title": f"Post-Mortem: {sev} Incident on {services} [{incident_id}]",
            "sections": [
                {
                    "title": "Executive Summary",
                    "content": (
                        f"A {sev} severity incident ({incident_id}) was detected affecting "
                        f"{services}. Correlated signals ({alert_count} alert(s), "
                        f"{trace_count} trace span(s), {log_count} log entry(ies)) were "
                        f"observed between {window_s} and {window_e} UTC. "
                        "This document captures the timeline, probable root cause, estimated "
                        "impact, and remediation action items."
                    ),
                },
                {"title": "Timeline", "content": timeline},
                {"title": "Root Cause Hypothesis", "content": root_cause},
                {"title": "Impact Estimate", "content": impact},
                {"title": "Action Items", "content": actions},
            ],
        }
        return json.dumps(doc)

    # ------------------------------------------------------------------
    # Output parsing
    # ------------------------------------------------------------------

    @staticmethod
    def _parse_llm_output(
        raw: str, summary: IncidentSummary
    ) -> tuple[List[PostMortemSection], str]:
        """
        Parse the JSON output from the LLM (or mock) into sections and title.

        Falls back to a single-section document if parsing fails.
        """
        # Strip markdown fences that some models emit despite instructions
        cleaned = re.sub(r"^```[a-zA-Z]*\n?", "", raw.strip())
        cleaned = re.sub(r"```$", "", cleaned.strip())

        try:
            data = json.loads(cleaned)
        except json.JSONDecodeError:
            # Graceful degradation: wrap raw output in a single section
            fallback_section = PostMortemSection(
                title="Raw LLM Output",
                content=raw,
            )
            title = f"Post-Mortem: Incident {summary.incident_id} (parse error)"
            return [fallback_section], title

        title = data.get(
            "title",
            f"Post-Mortem: {summary.severity.value.upper()} Incident [{summary.incident_id}]",
        )
        raw_sections = data.get("sections", [])
        sections: List[PostMortemSection] = []
        for sec in raw_sections:
            if isinstance(sec, dict) and "title" in sec and "content" in sec:
                sections.append(
                    PostMortemSection(title=sec["title"], content=sec["content"])
                )

        if not sections:
            sections = [
                PostMortemSection(title="Raw LLM Output", content=raw)
            ]

        return sections, title
