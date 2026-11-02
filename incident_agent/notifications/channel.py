"""Simulated Slack channel that stores and displays posted messages."""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import IO, List, Optional
import sys


@dataclass
class ChannelMessage:
    """
    A single message posted to a simulated Slack channel.

    Fields
    ------
    channel   : Target channel name (e.g. '#incidents').
    text      : The message body.
    posted_at : When the message was created.
    author    : The posting user/bot name.
    blocks    : Optional list of rich-text block dicts.
    """

    channel: str
    text: str
    posted_at: datetime
    author: str = "incident-agent"
    blocks: List[dict] = field(default_factory=list)

    def to_dict(self) -> dict:
        return {
            "channel": self.channel,
            "text": self.text,
            "posted_at": self.posted_at.isoformat(),
            "author": self.author,
            "blocks": self.blocks,
        }

    def render(self) -> str:
        """Render a human-readable representation of this message."""
        ts = self.posted_at.strftime("%H:%M:%S")
        lines = [
            f"[{ts}] {self.channel} | @{self.author}",
            f"{self.text}",
        ]
        return "\n".join(lines)


class SlackChannel:
    """
    An in-process mock of a Slack channel.

    Messages posted via :meth:`post` are stored in-memory and optionally
    echoed to an output stream for visibility during CLI runs.

    Parameters
    ----------
    name          : Channel name (e.g. '#incidents').
    output_stream : Stream to echo messages to (None = no echo).
    """

    def __init__(
        self,
        name: str = "#incidents",
        output_stream: Optional[IO[str]] = None,
    ) -> None:
        self.name = name
        self._output = output_stream
        self._messages: List[ChannelMessage] = []

    # ------------------------------------------------------------------
    # Posting
    # ------------------------------------------------------------------

    def post(
        self,
        text: str,
        author: str = "incident-agent",
        blocks: Optional[List[dict]] = None,
    ) -> ChannelMessage:
        """
        Post a message to this channel.

        The message is stored and optionally echoed.  Returns the
        created :class:`ChannelMessage`.
        """
        msg = ChannelMessage(
            channel=self.name,
            text=text,
            posted_at=datetime.now(tz=timezone.utc),
            author=author,
            blocks=blocks or [],
        )
        self._messages.append(msg)
        if self._output is not None:
            self._output.write(
                f"\n[SLACK {self.name}] {msg.render()}\n"
            )
            try:
                self._output.flush()
            except Exception:  # pragma: no cover
                pass
        return msg

    # ------------------------------------------------------------------
    # Inspection
    # ------------------------------------------------------------------

    @property
    def messages(self) -> List[ChannelMessage]:
        """All messages posted to this channel since creation or last reset."""
        return list(self._messages)

    def messages_containing(self, substring: str) -> List[ChannelMessage]:
        """Return all messages whose text contains *substring*."""
        return [m for m in self._messages if substring in m.text]

    def clear(self) -> None:
        """Remove all stored messages."""
        self._messages.clear()

    def __len__(self) -> int:
        return len(self._messages)
