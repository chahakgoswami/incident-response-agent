"""Configuration loader: reads agent.toml (or defaults) for tuning thresholds and rollback mappings."""

from __future__ import annotations

import json
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Dict, List, Optional

# ---------------------------------------------------------------------------
# Default configuration values
# ---------------------------------------------------------------------------

_DEFAULTS: Dict[str, Any] = {
    "correlation": {
        "window_minutes": 5,
        "min_signals": 1,
        "latency_error_threshold_ms": 800.0,
    },
    "postmortem": {
        "model": "gpt-4o-mini",
        "force_mock": False,
        "max_signals_in_prompt": 10,
    },
    "rollback": {
        "top_n": 3,
        "auto_confirm": False,
        "extra_commands": [],
    },
    "notifications": {
        "enabled": True,
        "slack_channel": "#incidents",
    },
    "audit": {
        "log_path": "incident_audit.json",
    },
}


@dataclass
class CorrelationConfig:
    window_minutes: int = 5
    min_signals: int = 1
    latency_error_threshold_ms: float = 800.0


@dataclass
class PostMortemConfig:
    model: str = "gpt-4o-mini"
    force_mock: bool = False
    max_signals_in_prompt: int = 10


@dataclass
class ExtraRollbackCommand:
    """A user-defined extra rollback command loaded from config."""
    command_id: str
    description: str
    command: str
    pattern_tags: List[str] = field(default_factory=list)
    service_hint: Optional[str] = None
    risk_level: str = "low"


@dataclass
class RollbackConfig:
    top_n: int = 3
    auto_confirm: bool = False
    extra_commands: List[ExtraRollbackCommand] = field(default_factory=list)


@dataclass
class NotificationsConfig:
    enabled: bool = True
    slack_channel: str = "#incidents"


@dataclass
class AuditConfig:
    log_path: str = "incident_audit.json"


@dataclass
class AgentConfig:
    """Top-level configuration for the Incident Response Agent."""
    correlation: CorrelationConfig = field(default_factory=CorrelationConfig)
    postmortem: PostMortemConfig = field(default_factory=PostMortemConfig)
    rollback: RollbackConfig = field(default_factory=RollbackConfig)
    notifications: NotificationsConfig = field(default_factory=NotificationsConfig)
    audit: AuditConfig = field(default_factory=AuditConfig)

    def to_dict(self) -> dict:
        return {
            "correlation": {
                "window_minutes": self.correlation.window_minutes,
                "min_signals": self.correlation.min_signals,
                "latency_error_threshold_ms": self.correlation.latency_error_threshold_ms,
            },
            "postmortem": {
                "model": self.postmortem.model,
                "force_mock": self.postmortem.force_mock,
                "max_signals_in_prompt": self.postmortem.max_signals_in_prompt,
            },
            "rollback": {
                "top_n": self.rollback.top_n,
                "auto_confirm": self.rollback.auto_confirm,
                "extra_commands": [
                    {
                        "command_id": c.command_id,
                        "description": c.description,
                        "command": c.command,
                        "pattern_tags": c.pattern_tags,
                        "service_hint": c.service_hint,
                        "risk_level": c.risk_level,
                    }
                    for c in self.rollback.extra_commands
                ],
            },
            "notifications": {
                "enabled": self.notifications.enabled,
                "slack_channel": self.notifications.slack_channel,
            },
            "audit": {
                "log_path": self.audit.log_path,
            },
        }


# ---------------------------------------------------------------------------
# TOML parsing (stdlib tomllib in 3.11+, fallback to manual parser)
# ---------------------------------------------------------------------------

def _parse_toml(text: str) -> Dict[str, Any]:
    """Parse TOML text using stdlib tomllib (3.11+) or a simple fallback."""
    try:
        import tomllib  # Python 3.11+
        return tomllib.loads(text)
    except ImportError:
        pass
    try:
        import tomli  # optional third-party
        return tomli.loads(text)  # type: ignore[attr-defined]
    except ImportError:
        pass
    # Minimal fallback: parse flat key=value only (good enough for our config)
    return _simple_toml_parse(text)


def _simple_toml_parse(text: str) -> Dict[str, Any]:
    """
    Very small TOML parser that handles:
    - [section] headers
    - [[section.array]] headers (treated as append to list of dicts)
    - key = value lines (string, int, float, bool, inline arrays of strings)
    - # comments and blank lines
    """
    result: Dict[str, Any] = {}
    current_section: Dict[str, Any] = result
    current_path: List[str] = []
    array_section_path: Optional[List[str]] = None

    for raw_line in text.splitlines():
        line = raw_line.strip()
        if not line or line.startswith("#"):
            continue

        # Array-of-tables: [[section]]
        if line.startswith("[[") and line.endswith("]]"):
            path = [p.strip() for p in line[2:-2].split(".")]
            array_section_path = path
            # Navigate to parent
            parent = result
            for part in path[:-1]:
                parent = parent.setdefault(part, {})
            arr_key = path[-1]
            parent.setdefault(arr_key, [])
            new_item: Dict[str, Any] = {}
            parent[arr_key].append(new_item)
            current_section = new_item
            current_path = []
            continue

        # Regular section: [section]
        if line.startswith("[") and line.endswith("]"):
            array_section_path = None
            path = [p.strip() for p in line[1:-1].split(".")]
            current_path = path
            current_section = result
            for part in path:
                current_section = current_section.setdefault(part, {})
            continue

        # Key = value
        if "=" in line:
            key, _, raw_val = line.partition("=")
            key = key.strip()
            raw_val = raw_val.strip()
            # Strip inline comment
            if " #" in raw_val:
                raw_val = raw_val[: raw_val.index(" #")].strip()
            value = _parse_toml_value(raw_val)
            current_section[key] = value

    return result


def _parse_toml_value(raw: str) -> Any:
    """Parse a TOML scalar or simple inline array."""
    if raw.startswith('"') and raw.endswith('"'):
        return raw[1:-1]
    if raw.startswith("'") and raw.endswith("'"):
        return raw[1:-1]
    if raw.lower() == "true":
        return True
    if raw.lower() == "false":
        return False
    if raw.startswith("[") and raw.endswith("]"):
        inner = raw[1:-1].strip()
        if not inner:
            return []
        items = [i.strip().strip('"').strip("'") for i in inner.split(",")]
        return [i for i in items if i]
    try:
        if "." in raw:
            return float(raw)
        return int(raw)
    except ValueError:
        return raw


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------

def get_default_config() -> AgentConfig:
    """Return an AgentConfig populated entirely from built-in defaults."""
    return AgentConfig()


def load_config(path: Optional[Path] = None) -> AgentConfig:
    """
    Load configuration from a TOML file, merging with defaults.

    If *path* is None, looks for ``agent.toml`` in the current working directory.
    If the file does not exist, returns the default configuration.

    Parameters
    ----------
    path : Path, optional
        Explicit path to a ``.toml`` config file.

    Returns
    -------
    AgentConfig
        Fully populated configuration dataclass.
    """
    if path is None:
        path = Path.cwd() / "agent.toml"

    if not path.exists():
        return get_default_config()

    try:
        text = path.read_text(encoding="utf-8")
        raw = _parse_toml(text)
    except Exception:
        # If parsing fails for any reason, fall back to defaults
        return get_default_config()

    return _build_config(raw)


def _build_config(raw: Dict[str, Any]) -> AgentConfig:
    """Build an AgentConfig from a parsed TOML dict, filling in defaults."""
    corr_raw = raw.get("correlation", {})
    correlation = CorrelationConfig(
        window_minutes=int(corr_raw.get("window_minutes", _DEFAULTS["correlation"]["window_minutes"])),
        min_signals=int(corr_raw.get("min_signals", _DEFAULTS["correlation"]["min_signals"])),
        latency_error_threshold_ms=float(
            corr_raw.get("latency_error_threshold_ms", _DEFAULTS["correlation"]["latency_error_threshold_ms"])
        ),
    )

    pm_raw = raw.get("postmortem", {})
    postmortem = PostMortemConfig(
        model=str(pm_raw.get("model", _DEFAULTS["postmortem"]["model"])),
        force_mock=bool(pm_raw.get("force_mock", _DEFAULTS["postmortem"]["force_mock"])),
        max_signals_in_prompt=int(
            pm_raw.get("max_signals_in_prompt", _DEFAULTS["postmortem"]["max_signals_in_prompt"])
        ),
    )

    rb_raw = raw.get("rollback", {})
    extra_cmds: List[ExtraRollbackCommand] = []
    for item in rb_raw.get("extra_commands", []):
        if isinstance(item, dict) and "command_id" in item and "command" in item:
            extra_cmds.append(
                ExtraRollbackCommand(
                    command_id=str(item["command_id"]),
                    description=str(item.get("description", "")),
                    command=str(item["command"]),
                    pattern_tags=list(item.get("pattern_tags", [])),
                    service_hint=item.get("service_hint"),
                    risk_level=str(item.get("risk_level", "low")),
                )
            )
    rollback = RollbackConfig(
        top_n=int(rb_raw.get("top_n", _DEFAULTS["rollback"]["top_n"])),
        auto_confirm=bool(rb_raw.get("auto_confirm", _DEFAULTS["rollback"]["auto_confirm"])),
        extra_commands=extra_cmds,
    )

    notif_raw = raw.get("notifications", {})
    notifications = NotificationsConfig(
        enabled=bool(notif_raw.get("enabled", _DEFAULTS["notifications"]["enabled"])),
        slack_channel=str(notif_raw.get("slack_channel", _DEFAULTS["notifications"]["slack_channel"])),
    )

    audit_raw = raw.get("audit", {})
    audit = AuditConfig(
        log_path=str(audit_raw.get("log_path", _DEFAULTS["audit"]["log_path"])),
    )

    return AgentConfig(
        correlation=correlation,
        postmortem=postmortem,
        rollback=rollback,
        notifications=notifications,
        audit=audit,
    )
