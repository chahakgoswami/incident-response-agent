"""Human confirmation gate for rollback command execution."""

from __future__ import annotations

from datetime import datetime, timezone
from typing import IO, Optional

from .models import RollbackCommand, RollbackResult, RollbackStatus

# ---------------------------------------------------------------------------
# Simulated execution output templates
# ---------------------------------------------------------------------------

_SIMULATED_OUTPUTS = {
    "kubectl rollout undo": (
        "deployment.apps/{service} rolled back\n"
        "Waiting for rollout to finish: 0 out of {replicas} new replicas have been updated...\n"
        "Waiting for deployment {service} rollout to finish: 1 out of {replicas} new replicas have been updated...\n"
        "deployment {service} successfully rolled out\n"
        "[SIMULATED — no real Kubernetes cluster was contacted]"
    ),
    "kubectl scale": (
        "deployment.apps/{service} scaled\n"
        "[SIMULATED — no real Kubernetes cluster was contacted]"
    ),
    "kubectl rollout restart": (
        "deployment.apps/{service} restarted\n"
        "[SIMULATED — no real Kubernetes cluster was contacted]"
    ),
    "feature-flags set": (
        "Feature flag updated successfully.\n"
        "Key   : {flag_key}\n"
        "Value : false\n"
        "Env   : production\n"
        "[SIMULATED — no real feature-flag service was contacted]"
    ),
    "curl -X POST": (
        "HTTP/1.1 200 OK\n"
        "Content-Type: application/json\n\n"
        '{"status": "ok", "message": "Circuit breaker reset"}\n'
        "[SIMULATED — no real HTTP request was made]"
    ),
    "curl -X DELETE": (
        "HTTP/1.1 204 No Content\n"
        "[SIMULATED — no real HTTP request was made]"
    ),
    "redis-cli": (
        "OK\n"
        "[SIMULATED — no real Redis instance was contacted]"
    ),
}

_DEFAULT_SIMULATED_OUTPUT = (
    "Command executed successfully.\n"
    "[SIMULATED — no real system was modified]"
)


class ConfirmationGate:
    """
    Presents a rollback command to the operator and waits for explicit y/n confirmation.

    Parameters
    ----------
    input_stream  : File-like object to read confirmation from (default: stdin).
    output_stream : File-like object to write prompts to (default: stdout).
    auto_confirm  : If True, automatically confirm (for testing only).
    auto_reject   : If True, automatically reject (for testing only).
    """

    def __init__(
        self,
        input_stream: Optional[IO[str]] = None,
        output_stream: Optional[IO[str]] = None,
        auto_confirm: bool = False,
        auto_reject: bool = False,
    ) -> None:
        import sys

        self._in = input_stream or sys.stdin
        self._out = output_stream or sys.stdout
        self.auto_confirm = auto_confirm
        self.auto_reject = auto_reject

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    def ask(self, incident_id: str, command: RollbackCommand) -> RollbackResult:
        """
        Display the suggested rollback command and prompt for y/n.

        Returns a :class:`RollbackResult` with CONFIRMED or REJECTED status.
        """
        self._print_suggestion(incident_id, command)

        if self.auto_confirm:
            answer = "y"
            self._write("[auto-confirm] y\n")
        elif self.auto_reject:
            answer = "n"
            self._write("[auto-reject] n\n")
        else:
            answer = self._prompt("Execute this rollback? [y/N]: ").strip().lower()

        decided_at = datetime.now(tz=timezone.utc)

        if answer == "y":
            simulated_output = self._simulate_execution(command)
            self._write("\n--- Simulated Execution Output ---\n")
            self._write(simulated_output)
            self._write("\n----------------------------------\n")
            return RollbackResult(
                incident_id=incident_id,
                status=RollbackStatus.CONFIRMED,
                command=command,
                decided_at=decided_at,
                simulated_output=simulated_output,
            )
        else:
            self._write("Rollback rejected. No action taken.\n")
            return RollbackResult(
                incident_id=incident_id,
                status=RollbackStatus.REJECTED,
                command=command,
                decided_at=decided_at,
                simulated_output="",
            )

    def ask_no_suggestion(
        self, incident_id: str
    ) -> RollbackResult:
        """Return a SKIPPED result when no rollback command matched the incident."""
        self._write(
            f"\n[Rollback Suggester] No matching rollback command found for incident {incident_id}.\n"
            "Manual investigation is required.\n"
        )
        return RollbackResult(
            incident_id=incident_id,
            status=RollbackStatus.SKIPPED,
            command=None,
            decided_at=datetime.now(tz=timezone.utc),
            simulated_output="",
        )

    # ------------------------------------------------------------------
    # Internal helpers
    # ------------------------------------------------------------------

    def _print_suggestion(self, incident_id: str, command: RollbackCommand) -> None:
        lines = [
            "",
            "=" * 60,
            f" ROLLBACK SUGGESTION for Incident {incident_id}",
            "=" * 60,
            f" ID          : {command.command_id}",
            f" Description : {command.description}",
            f" Risk Level  : {command.risk_level.upper()}",
            f" Command     : {command.command}",
            "=" * 60,
            "",
        ]
        self._write("\n".join(lines))

    def _prompt(self, message: str) -> str:
        self._write(message)
        try:
            return self._in.readline().rstrip("\n")
        except (EOFError, OSError):
            return ""

    def _write(self, text: str) -> None:
        self._out.write(text)
        try:
            self._out.flush()
        except Exception:  # pragma: no cover
            pass

    @staticmethod
    def _simulate_execution(command: RollbackCommand) -> str:
        """Produce fake terminal output for a confirmed rollback command."""
        cmd = command.command

        # Extract a plausible service name from the command string
        service = "service"
        parts = cmd.split()
        for part in parts:
            if "/" in part and not part.startswith("http"):
                service = part.split("/")[-1].split(" ")[0]
                break

        # Extract feature-flag key if relevant
        flag_key = "unknown_flag"
        if "feature-flags set" in cmd:
            for part in parts:
                if "=" in part:
                    flag_key = part.split("=")[0]
                    break

        # Match output template by command prefix
        for prefix, template in _SIMULATED_OUTPUTS.items():
            if prefix in cmd:
                return template.format(
                    service=service,
                    replicas=3,
                    flag_key=flag_key,
                )

        return _DEFAULT_SIMULATED_OUTPUT
