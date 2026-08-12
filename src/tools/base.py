"""
LLMSQL Tool Base Module

Defines the abstract Tool interface and ToolResult dataclass that every
custom LLMSQL tool must implement. This enforces a consistent contract:

Every Tool subclass MUST provide:
  - name:              Short identifier (e.g. "get_schema")
  - description:       One-line purpose statement
  - parameters_schema: JSON-Schema dict describing expected input
  - run(**kwargs):     Execute the tool and return a ToolResult

ToolResult wraps every tool's output with:
  - success:  bool
  - data:     Any structured payload (dict, list, str)
  - error:    Optional error message string
  - metadata: Optional dict for execution stats (timing, row counts, etc.)
"""

from __future__ import annotations

import time
from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from typing import Any


@dataclass
class ToolResult:
    """Standardised wrapper for every tool execution output.

    Attributes:
        success:  Whether the tool executed without error.
        data:     The structured payload returned by the tool.
        error:    Human-readable error message (None on success).
        metadata: Auxiliary info such as execution_time_ms, row_count, etc.
    """

    success: bool
    data: Any = None
    error: str | None = None
    metadata: dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        """Serialise to a JSON-safe dictionary."""
        return {
            "success": self.success,
            "data": self.data,
            "error": self.error,
            "metadata": self.metadata,
        }


class Tool(ABC):
    """Abstract base class for all LLMSQL agent tools.

    Subclasses must implement:
        name              – tool identifier string
        description       – one-line purpose
        parameters_schema – JSON Schema dict for input validation
        run(**kwargs)      – core execution logic returning ToolResult

    The execute() wrapper automatically captures timing metadata.
    """

    @property
    @abstractmethod
    def name(self) -> str:
        """Short unique identifier for this tool (e.g. 'get_schema')."""
        ...

    @property
    @abstractmethod
    def description(self) -> str:
        """One-line description of what this tool does."""
        ...

    @property
    @abstractmethod
    def parameters_schema(self) -> dict[str, Any]:
        """JSON Schema dict describing expected keyword arguments."""
        ...

    @abstractmethod
    def run(self, **kwargs: Any) -> ToolResult:
        """Core execution logic. Must return a ToolResult."""
        ...

    # ------------------------------------------------------------------
    # Public API — call execute(), not run() directly
    # ------------------------------------------------------------------

    def execute(self, **kwargs: Any) -> ToolResult:
        """Run the tool with automatic timing and error handling."""
        start = time.perf_counter()
        try:
            result = self.run(**kwargs)
        except Exception as exc:
            result = ToolResult(success=False, error=str(exc))
        elapsed_ms = round((time.perf_counter() - start) * 1000, 2)
        result.metadata["execution_time_ms"] = elapsed_ms
        result.metadata["tool_name"] = self.name
        return result

    def get_tool_spec(self) -> dict[str, Any]:
        """Return a function-calling specification for this tool."""
        return {
            "type": "function",
            "function": {
                "name": self.name,
                "description": self.description,
                "parameters": self.parameters_schema,
            },
        }
