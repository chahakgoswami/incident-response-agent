"""Interactive CLI tying all components together for the Incident Response Agent."""

from __future__ import annotations

import json
import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import Optional

import click

from incident_agent.correlator import CorrelationEngine
from incident_agent.mock_data import generate_incident_scenario
from incident_agent.mock_data.scenario import ScenarioType
from incident_agent.postmortem import PostMortemDrafter
from incident_agent.rollback import ConfirmationGate, RollbackSuggester

# Default audit log file
DEFAULT_AUDIT_LOG = "incident_audit.json"


# ---------------------------------------------------------------------------
# Audit logging
# ---------------------------------------------------------------------------

def _load_audit_log(path: Path) -> list:
    """Load existing audit log entries from a JSON file, or return empty list."""
    if path.exists():
        try:
            data = json.loads(path.read_text())
            if isinstance(data, list):
                return data
        except (json.JSONDecodeError, OSError):
            pass
    return []


def _save_audit_log(path: Path, entries: list) -> None:
    """Persist audit log entries to a JSON file."""
    path.write_text(json.dumps(entries, indent=2))


def _append_audit_entry(path: Path, entry: dict) -> None:
    """Append a single entry to the audit log."""
    entries = _load_audit_log(path)
    entries.append(entry)
    _save_audit_log(path, entries)


# ---------------------------------------------------------------------------
# CLI group
# ---------------------------------------------------------------------------

@click.group()
@click.version_option(version="0.1.0", prog_name="incident-agent")
def cli():
    """Incident Response Agent — correlate alerts, draft post-mortems, and suggest rollbacks."""


# ---------------------------------------------------------------------------
# run command
# ---------------------------------------------------------------------------

@cli.command("run")
@click.option(
    "--scenario",
    "scenario_type",
    type=click.Choice([s.value for s in ScenarioType], case_sensitive=False),
    default=ScenarioType.MIXED.value,
    show_default=True,
    help="Type of simulated incident scenario to generate.",
)
@click.option(
    "--seed",
    type=int,
    default=None,
    help="Random seed for reproducible scenarios.",
)
@click.option(
    "--services",
    default=None,
    help="Comma-separated list of services to include (e.g. api-gateway,auth-service).",
)
@click.option(
    "--window",
    "window_minutes",
    type=int,
    default=5,
    show_default=True,
    help="Correlation window size in minutes.",
)
@click.option(
    "--top-n",
    type=int,
    default=3,
    show_default=True,
    help="Maximum rollback suggestions to show.",
)
@click.option(
    "--audit-log",
    "audit_log_path",
    type=click.Path(dir_okay=False, writable=True),
    default=DEFAULT_AUDIT_LOG,
    show_default=True,
    help="Path to the JSON audit log file.",
)
@click.option(
    "--force-mock",
    is_flag=True,
    default=False,
    help="Force the mock LLM stub even if OPENAI_API_KEY is set.",
)
@click.option(
    "--no-postmortem",
    is_flag=True,
    default=False,
    help="Skip post-mortem drafting.",
)
@click.option(
    "--no-rollback",
    is_flag=True,
    default=False,
    help="Skip rollback suggestion step.",
)
def run(
    scenario_type: str,
    seed: Optional[int],
    services: Optional[str],
    window_minutes: int,
    top_n: int,
    audit_log_path: str,
    force_mock: bool,
    no_postmortem: bool,
    no_rollback: bool,
) -> None:
    """Run a full simulated incident through the response pipeline."""
    audit_path = Path(audit_log_path)
    started_at = datetime.now(tz=timezone.utc).isoformat()

    # ---- Parse services ----
    service_list = None
    if services:
        service_list = [s.strip() for s in services.split(",") if s.strip()]

    # ---- Generate scenario ----
    stype = ScenarioType(scenario_type)
    click.echo(f"\n{'='*60}")
    click.echo(f"  Incident Response Agent")
    click.echo(f"{'='*60}")
    click.echo(f"\n[1/4] Generating {stype.value} incident scenario...")

    scenario = generate_incident_scenario(
        scenario_type=stype,
        services=service_list,
        seed=seed,
    )
    click.echo(scenario.summary())

    # ---- Correlate signals ----
    click.echo(f"\n[2/4] Correlating signals (window={window_minutes}min)...")
    engine = CorrelationEngine(window_minutes=window_minutes)
    summaries = engine.correlate_scenario(scenario)

    if not summaries:
        click.echo(click.style("  No correlated incidents found.", fg="yellow"))
        _append_audit_entry(
            audit_path,
            {
                "started_at": started_at,
                "scenario_id": scenario.scenario_id,
                "scenario_type": stype.value,
                "incidents": [],
                "note": "No correlated incidents",
            },
        )
        return

    click.echo(
        click.style(
            f"  Found {len(summaries)} correlated incident(s).", fg="green"
        )
    )

    # Process each summary
    audit_incidents = []

    for idx, summary in enumerate(summaries, 1):
        _print_separator(f"Incident {idx}/{len(summaries)}: {summary.incident_id}")
        _print_correlation_report(summary)

        incident_audit: dict = {
            "incident_id": summary.incident_id,
            "severity": summary.severity.value,
            "score": round(summary.score, 2),
            "affected_services": summary.affected_services,
            "signal_counts": summary.signal_counts,
            "postmortem": None,
            "rollback": None,
        }

        # ---- Post-mortem ----
        if not no_postmortem:
            click.echo(f"\n[3/4] Drafting post-mortem for {summary.incident_id}...")
            drafter = PostMortemDrafter(force_mock=force_mock)
            postmortem = drafter.draft(summary)
            _print_postmortem(postmortem)
            incident_audit["postmortem"] = {
                "title": postmortem.title,
                "model_used": postmortem.model_used,
                "generated_at": postmortem.generated_at.isoformat(),
                "sections": [s.title for s in postmortem.sections],
            }
        else:
            click.echo("\n[3/4] Post-mortem drafting skipped (--no-postmortem).")

        # ---- Rollback suggestion ----
        if not no_rollback:
            click.echo(f"\n[4/4] Suggesting rollback commands for {summary.incident_id}...")
            suggester = RollbackSuggester()
            suggestions = suggester.suggest(summary, top_n=top_n)

            gate = ConfirmationGate()

            if not suggestions:
                result = gate.ask_no_suggestion(summary.incident_id)
                incident_audit["rollback"] = result.to_dict()
            else:
                click.echo(
                    f"  Found {len(suggestions)} rollback suggestion(s). "
                    "Presenting top suggestion:"
                )
                # Present only the first/top suggestion
                result = gate.ask(summary.incident_id, suggestions[0])
                incident_audit["rollback"] = result.to_dict()

                # Show remaining suggestions as informational
                if len(suggestions) > 1:
                    click.echo("\n  Additional suggestions (not executed):")
                    for i, cmd in enumerate(suggestions[1:], 2):
                        click.echo(
                            f"    {i}. [{cmd.risk_level.upper()}] {cmd.description}\n"
                            f"       $ {cmd.command}"
                        )
        else:
            click.echo("\n[4/4] Rollback suggestion skipped (--no-rollback).")

        audit_incidents.append(incident_audit)

    # ---- Write audit log ----
    audit_entry = {
        "started_at": started_at,
        "finished_at": datetime.now(tz=timezone.utc).isoformat(),
        "scenario_id": scenario.scenario_id,
        "scenario_type": stype.value,
        "seed": seed,
        "window_minutes": window_minutes,
        "incidents": audit_incidents,
    }
    _append_audit_entry(audit_path, audit_entry)
    click.echo(
        click.style(
            f"\n[Audit] Entry written to {audit_path}", fg="cyan"
        )
    )
    click.echo(f"{'='*60}\n")


# ---------------------------------------------------------------------------
# list-scenarios command
# ---------------------------------------------------------------------------

@cli.command("list-scenarios")
def list_scenarios() -> None:
    """List available incident scenario types."""
    click.echo("\nAvailable scenario types:\n")
    descriptions = {
        ScenarioType.CPU_SPIKE: "Sudden CPU saturation across services",
        ScenarioType.ERROR_SURGE: "Elevated HTTP 5xx error rate",
        ScenarioType.LATENCY_OUTLIER: "P99 latency outliers",
        ScenarioType.MIXED: "Multi-signal: CPU, errors, and latency simultaneously",
    }
    for stype, desc in descriptions.items():
        click.echo(f"  {click.style(stype.value, fg='green', bold=True):30s}  {desc}")
    click.echo()


# ---------------------------------------------------------------------------
# show-audit command
# ---------------------------------------------------------------------------

@cli.command("show-audit")
@click.option(
    "--audit-log",
    "audit_log_path",
    type=click.Path(dir_okay=False, readable=True),
    default=DEFAULT_AUDIT_LOG,
    show_default=True,
    help="Path to the JSON audit log file.",
)
@click.option(
    "--last",
    type=int,
    default=5,
    show_default=True,
    help="Show last N audit entries.",
)
def show_audit(audit_log_path: str, last: int) -> None:
    """Display recent entries from the audit log."""
    path = Path(audit_log_path)
    entries = _load_audit_log(path)

    if not entries:
        click.echo(click.style(f"No audit entries found in {path}.", fg="yellow"))
        return

    recent = entries[-last:]
    click.echo(f"\nShowing last {len(recent)} of {len(entries)} audit entries from {path}:\n")

    for i, entry in enumerate(recent, 1):
        click.echo(f"{'─'*60}")
        click.echo(
            f"  [{i}] Scenario : {entry.get('scenario_id', 'N/A')} "
            f"({entry.get('scenario_type', 'N/A')})"
        )
        click.echo(f"       Started  : {entry.get('started_at', 'N/A')}")
        click.echo(f"       Finished : {entry.get('finished_at', 'N/A')}")
        incidents = entry.get("incidents", [])
        click.echo(f"       Incidents: {len(incidents)}")
        for inc in incidents:
            sev = inc.get("severity", "?")
            inc_id = inc.get("incident_id", "?")
            svcs = ", ".join(inc.get("affected_services", []))
            rollback = inc.get("rollback") or {}
            rb_status = rollback.get("status", "none")
            click.echo(
                f"         • {inc_id} [{sev.upper()}] services={svcs} rollback={rb_status}"
            )
    click.echo(f"{'─'*60}\n")


# ---------------------------------------------------------------------------
# clear-audit command
# ---------------------------------------------------------------------------

@cli.command("clear-audit")
@click.option(
    "--audit-log",
    "audit_log_path",
    type=click.Path(dir_okay=False, writable=True),
    default=DEFAULT_AUDIT_LOG,
    show_default=True,
    help="Path to the JSON audit log file.",
)
@click.confirmation_option(
    prompt="Are you sure you want to clear the audit log?"
)
def clear_audit(audit_log_path: str) -> None:
    """Clear all entries from the audit log (requires confirmation)."""
    path = Path(audit_log_path)
    _save_audit_log(path, [])
    click.echo(click.style(f"Audit log cleared: {path}", fg="green"))


# ---------------------------------------------------------------------------
# Print helpers
# ---------------------------------------------------------------------------

def _print_separator(title: str = "") -> None:
    if title:
        click.echo(f"\n{'─'*60}")
        click.echo(f"  {title}")
        click.echo(f"{'─'*60}")
    else:
        click.echo(f"{'─'*60}")


def _print_correlation_report(summary) -> None:
    """Pretty-print a correlation report for an IncidentSummary."""
    sev_colors = {
        "critical": "red",
        "high": "yellow",
        "medium": "cyan",
        "low": "green",
        "unknown": "white",
    }
    sev_color = sev_colors.get(summary.severity.value, "white")

    click.echo(f"\n  Correlation Report")
    click.echo(f"  {'─'*40}")
    click.echo(f"  Incident ID   : {click.style(summary.incident_id, bold=True)}")
    click.echo(
        f"  Severity      : "
        + click.style(summary.severity.value.upper(), fg=sev_color, bold=True)
    )
    click.echo(f"  Score         : {summary.score:.1f}")
    click.echo(f"  Services      : {', '.join(summary.affected_services)}")
    click.echo(
        f"  Window        : {summary.window_start.strftime('%H:%M:%S')} — "
        f"{summary.window_end.strftime('%H:%M:%S')} UTC"
    )
    counts_str = ", ".join(
        f"{v} {k}(s)" for k, v in sorted(summary.signal_counts.items())
    )
    click.echo(f"  Signals       : {counts_str}")
    click.echo(f"\n  Summary: {summary.summary_text}")

    # Show top 5 signals
    top_signals = summary.contributing_signals[:5]
    if top_signals:
        click.echo(f"\n  Top {len(top_signals)} contributing signal(s):")
        for sig in top_signals:
            ts = sig.timestamp.strftime("%H:%M:%S")
            hint = sig.severity_hint.value.upper() if sig.severity_hint else "UNKNOWN"
            desc = sig.description[:80]
            click.echo(f"    [{ts}] {sig.signal_type.value.upper()} [{hint}] {desc}")


def _print_postmortem(postmortem) -> None:
    """Pretty-print a post-mortem document."""
    click.echo(f"\n  {'─'*40}")
    click.echo(f"  Post-Mortem Draft")
    click.echo(f"  {'─'*40}")
    click.echo(f"  Model   : {postmortem.model_used}")
    click.echo(f"  Title   : {postmortem.title}\n")

    md = postmortem.render_markdown()
    # Print with a small indent for readability
    for line in md.splitlines():
        if line.startswith("# "):
            click.echo(click.style(line, bold=True, fg="blue"))
        elif line.startswith("## "):
            click.echo(click.style(line, bold=True, fg="cyan"))
        elif line.startswith("**"):
            click.echo(click.style(line, fg="white"))
        else:
            click.echo(f"  {line}")
