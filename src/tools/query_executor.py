"""
LLMSQL ExecuteQueryTool

Purpose:
    Execute a validated SQL query against the active database and return
    structured tabular results. All queries pass through sqlparse
    token-based guardrails before execution.

Parameters:
    sql (str): The SQL query string to execute.

Returns:
    ToolResult containing columns, rows (list of dicts), and row_count.
"""

from __future__ import annotations

from typing import Any

from src.tools.base import Tool, ToolResult
from src.database.db_manager import DatabaseManager
from src.database.guardrails import validate_sql


class ExecuteQueryTool(Tool):
    """Execute a read-only SQL query with token-based safety guardrails."""

    def __init__(self, db_manager: DatabaseManager) -> None:
        self._db = db_manager

    @property
    def name(self) -> str:
        return "execute_query"

    @property
    def description(self) -> str:
        return (
            "Execute a SQL SELECT query against the database. The query is "
            "validated through security guardrails before execution. Returns "
            "structured tabular results with columns and rows. Only SELECT "
            "queries are allowed."
        )

    @property
    def parameters_schema(self) -> dict[str, Any]:
        return {
            "type": "object",
            "properties": {
                "sql": {
                    "type": "string",
                    "description": "The SQL SELECT query to execute.",
                },
            },
            "required": ["sql"],
        }

    def run(self, **kwargs: Any) -> ToolResult:
        raw_sql: str = kwargs.get("sql", "")

        if not raw_sql.strip():
            return ToolResult(success=False, error="No SQL query provided.")

        # --- Guardrail validation ---
        guard_result = validate_sql(raw_sql)
        if not guard_result.is_safe:
            return ToolResult(
                success=False,
                error=f"Query blocked by guardrails: {guard_result.violation}",
                metadata={"original_sql": raw_sql},
            )

        safe_sql = guard_result.query

        # --- Execute against database ---
        try:
            result = self._db.execute_query(safe_sql)
            return ToolResult(
                success=True,
                data=result,
                metadata={
                    "executed_sql": safe_sql,
                    "row_count": result["row_count"],
                    "column_count": len(result["columns"]),
                },
            )
        except Exception as exc:
            return ToolResult(
                success=False,
                error=str(exc),
                metadata={"executed_sql": safe_sql},
            )
