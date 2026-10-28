"""Data models for post-mortem documents."""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import List, Optional


@dataclass
class PostMortemSection:
    """A single labelled section within a post-mortem document."""

    title: str
    content: str

    def to_dict(self) -> dict:
        return {"title": self.title, "content": self.content}


@dataclass
class PostMortem:
    """
    A structured post-mortem document produced from an IncidentSummary.

    Fields
    ------
    incident_id     : The correlated incident this post-mortem covers.
    title           : Short title for the document.
    generated_at    : When the document was generated.
    sections        : Ordered list of PostMortemSection objects.
    raw_llm_output  : The verbatim text returned by the LLM (or mock).
    model_used      : Identifier of the model / fallback strategy used.
    """

    incident_id: str
    title: str
    generated_at: datetime
    sections: List[PostMortemSection] = field(default_factory=list)
    raw_llm_output: str = ""
    model_used: str = "unknown"

    # Convenience accessors -----------------------------------------------

    def get_section(self, title: str) -> Optional[PostMortemSection]:
        """Return the first section whose title matches (case-insensitive)."""
        needle = title.lower()
        for sec in self.sections:
            if sec.title.lower() == needle:
                return sec
        return None

    def to_dict(self) -> dict:
        return {
            "incident_id": self.incident_id,
            "title": self.title,
            "generated_at": self.generated_at.isoformat(),
            "model_used": self.model_used,
            "sections": [s.to_dict() for s in self.sections],
            "raw_llm_output": self.raw_llm_output,
        }

    def render_markdown(self) -> str:
        """Render the post-mortem as a Markdown document."""
        lines: List[str] = []
        lines.append(f"# {self.title}")
        lines.append(f"\n**Incident ID:** {self.incident_id}")
        lines.append(f"**Generated at:** {self.generated_at.strftime('%Y-%m-%d %H:%M:%S UTC')}")
        lines.append(f"**Model:** {self.model_used}\n")
        for sec in self.sections:
            lines.append(f"## {sec.title}")
            lines.append(sec.content)
            lines.append("")
        return "\n".join(lines)
