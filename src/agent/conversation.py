"""
LLMSQL Conversation Manager

Manages multi-turn conversation state with session-based context retention.
Tracks conversation history, past SQL queries, schema context, and tool
execution results to enable follow-up questions like "now show the trend
for these products."

Each session stores:
    - messages: Full conversation message history
    - schema_context: Cached schema metadata
    - last_query_result: Most recent query output for follow-up reference
    - last_sql: Most recent executed SQL
    - entities: Named entities extracted from past turns
"""

from __future__ import annotations

import uuid
from dataclasses import dataclass, field
from typing import Any


@dataclass
class ConversationSession:
    """A single conversation session with full state."""

    session_id: str = field(default_factory=lambda: str(uuid.uuid4()))
    messages: list[dict[str, Any]] = field(default_factory=list)
    schema_context: dict[str, Any] | None = None
    last_query_result: dict[str, Any] | None = None
    last_sql: str | None = None
    last_chart_type: str | None = None
    entities: list[str] = field(default_factory=list)
    tool_trace: list[dict[str, Any]] = field(default_factory=list)

    def add_message(self, role: str, content: str, **kwargs: Any) -> None:
        """Append a message to the conversation history."""
        msg: dict[str, Any] = {"role": role, "content": content}
        msg.update(kwargs)
        self.messages.append(msg)

    def add_tool_result(self, tool_name: str, tool_call_id: str, result: str) -> None:
        """Append a tool result message to history."""
        self.messages.append({
            "role": "tool",
            "tool_call_id": tool_call_id,
            "name": tool_name,
            "content": result,
        })

    def add_assistant_tool_calls(self, tool_calls_raw: list[dict[str, Any]]) -> None:
        """Append an assistant message containing tool calls."""
        self.messages.append({
            "role": "assistant",
            "content": None,
            "tool_calls": tool_calls_raw,
        })

    def record_tool_execution(self, tool_name: str, result: dict[str, Any]) -> None:
        """Record a tool execution in the trace log."""
        self.tool_trace.append({
            "tool": tool_name,
            "success": result.get("success", False),
            "execution_time_ms": result.get("metadata", {}).get("execution_time_ms"),
        })

    def get_context_summary(self) -> str:
        """Build a context summary string for the LLM to understand prior state."""
        parts: list[str] = []
        if self.last_sql:
            parts.append(f"Previous SQL query: {self.last_sql}")
        if self.last_query_result:
            cols = self.last_query_result.get("columns", [])
            row_count = self.last_query_result.get("row_count", 0)
            parts.append(f"Previous result had {row_count} rows with columns: {cols}")
        if self.entities:
            parts.append(f"Referenced entities: {', '.join(self.entities)}")
        return "\n".join(parts)


class ConversationManager:
    """Manages multiple conversation sessions keyed by session_id."""

    def __init__(self) -> None:
        self._sessions: dict[str, ConversationSession] = {}

    def get_or_create_session(self, session_id: str | None = None) -> ConversationSession:
        """Get an existing session or create a new one."""
        if session_id and session_id in self._sessions:
            return self._sessions[session_id]
        session = ConversationSession(session_id=session_id or str(uuid.uuid4()))
        self._sessions[session.session_id] = session
        return session

    def get_session(self, session_id: str) -> ConversationSession | None:
        """Retrieve an existing session by ID."""
        return self._sessions.get(session_id)

    def list_sessions(self) -> list[str]:
        """Return all active session IDs."""
        return list(self._sessions.keys())
