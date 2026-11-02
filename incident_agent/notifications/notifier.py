"""High-level notifier that publishes incident events to a SlackChannel via the EventBus."""

from __future__ import annotations

from typing import Optional

from incident_agent.correlator.models import IncidentSummary
from incident_agent.postmortem.models import PostMortem
from incident_agent.rollback.models import RollbackResult

from .bus import EventBus, get_default_bus
from .channel import SlackChannel

# ---------------------------------------------------------------------------
# Event type constants
# ---------------------------------------------------------------------------

EVENT_CORRELATION_SUMMARY = "correlation_summary"
EVENT_POSTMORTEM_DRAFTED = "postmortem_drafted"
EVENT_ROLLBACK_DECISION = "rollback_decision"


class IncidentNotifier:
    """
    Posts structured incident notifications to a :class:`SlackChannel` and
    publishes corresponding events on the :class:`EventBus`.

    Parameters
    ----------
    channel : SlackChannel to post messages to.
    bus     : EventBus to publish events to.  Defaults to the module-level
              default bus if not provided.
    """

    def __init__(
        self,
        channel: SlackChannel,
        bus: Optional[EventBus] = None,
    ) -> None:
        self.channel = channel
        self.bus = bus if bus is not None else get_default_bus()

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    def notify_correlation(self, summary: IncidentSummary) -> None:
        """
        Post a correlation summary to the channel and publish an event.

        The Slack message is formatted to mimic a real alert notification.
        """
        sev = summary.severity.value.upper()
        services = ", ".join(summary.affected_services[:3])
        counts = ", ".join(
            f"{v} {k}(s)" for k, v in sorted(summary.signal_counts.items())
        )
        text = (
            f":rotating_light: *INCIDENT {summary.incident_id}* — Severity: *{sev}*\n"
            f"> Services: {services}\n"
            f"> Signals : {counts}\n"
            f"> Window  : {summary.window_start.strftime('%H:%M:%S')} — "
            f"{summary.window_end.strftime('%H:%M:%S')} UTC\n"
            f"> {summary.summary_text}"
        )
        self.channel.post(text, author="correlation-engine")
        self.bus.publish(
            EVENT_CORRELATION_SUMMARY,
            {
                "incident_id": summary.incident_id,
                "severity": summary.severity.value,
                "affected_services": summary.affected_services,
                "signal_counts": summary.signal_counts,
                "score": round(summary.score, 2),
                "summary_text": summary.summary_text,
            },
        )

    def notify_postmortem(self, postmortem: PostMortem) -> None:
        """
        Post a post-mortem draft link/summary to the channel and publish an event.
        """
        section_titles = [s.title for s in postmortem.sections]
        exec_summary_sec = postmortem.get_section("Executive Summary")
        excerpt = ""
        if exec_summary_sec:
            # First 200 chars of the executive summary
            excerpt = exec_summary_sec.content[:200].replace("\n", " ")

        text = (
            f":memo: *Post-Mortem Draft Ready* — {postmortem.incident_id}\n"
            f"> Title   : {postmortem.title}\n"
            f"> Model   : {postmortem.model_used}\n"
            f"> Sections: {', '.join(section_titles)}\n"
        )
        if excerpt:
            text += f"> Summary : {excerpt}..."

        self.channel.post(text, author="postmortem-bot")
        self.bus.publish(
            EVENT_POSTMORTEM_DRAFTED,
            {
                "incident_id": postmortem.incident_id,
                "title": postmortem.title,
                "model_used": postmortem.model_used,
                "section_titles": section_titles,
            },
        )

    def notify_rollback(self, result: RollbackResult) -> None:
        """
        Post a rollback decision notification to the channel and publish an event.
        """
        status = result.status.value.upper()
        status_emoji = {
            "CONFIRMED": ":white_check_mark:",
            "REJECTED": ":x:",
            "SKIPPED": ":skip_forward:",
            "PENDING": ":hourglass:",
        }.get(status, ":question:")

        cmd_text = ""
        if result.command:
            cmd_text = (
                f"> Command : `{result.command.command}`\n"
                f"> Risk    : {result.command.risk_level.upper()}\n"
            )

        text = (
            f"{status_emoji} *Rollback {status}* for incident {result.incident_id}\n"
            f"{cmd_text}"
        )
        if result.status.value == "confirmed" and result.simulated_output:
            text += f"> Output  : (simulated) \u2714 executed"

        self.channel.post(text, author="rollback-bot")
        self.bus.publish(
            EVENT_ROLLBACK_DECISION,
            {
                "incident_id": result.incident_id,
                "status": result.status.value,
                "command_id": result.command.command_id if result.command else None,
                "decided_at": result.decided_at.isoformat() if result.decided_at else None,
            },
        )
