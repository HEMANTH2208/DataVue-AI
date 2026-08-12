"""
LLMSQL SchemaDiscoveryTool

Purpose:
    Inspects the active database to retrieve table names, column metadata,
    primary/foreign key relationships, row counts, and sample rows.
    Provides the LLM with the context it needs to write accurate SQL.

Parameters:
    table_name (str, optional): Specific table to inspect. If omitted,
                                returns the full database schema.

Returns:
    ToolResult with schema metadata dict.
"""

from __future__ import annotations

from typing import Any

from src.tools.base import Tool, ToolResult
from src.database.db_manager import DatabaseManager


class SchemaDiscoveryTool(Tool):
    """Discover database schema including tables, columns, keys, and sample data."""

    def __init__(self, db_manager: DatabaseManager) -> None:
        self._db = db_manager

    @property
    def name(self) -> str:
        return "get_schema"

    @property
    def description(self) -> str:
        return (
            "Inspect the database schema. Returns table names, column types, "
            "primary/foreign keys, row counts, and sample rows. Use this before "
            "writing any SQL query to understand the data structure."
        )

    @property
    def parameters_schema(self) -> dict[str, Any]:
        return {
            "type": "object",
            "properties": {
                "table_name": {
                    "type": "string",
                    "description": "Optional. Specific table name to inspect. "
                                   "Omit to get the full database schema.",
                },
            },
            "required": [],
        }

    def run(self, **kwargs: Any) -> ToolResult:
        table_name: str | None = kwargs.get("table_name")

        try:
            if table_name:
                # Single table inspection
                tables = self._db.get_tables()
                if table_name not in tables:
                    return ToolResult(
                        success=False,
                        error=f"Table '{table_name}' not found. Available tables: {tables}",
                    )
                schema = {
                    table_name: {
                        "columns": self._db.get_table_schema(table_name),
                        "foreign_keys": self._db.get_foreign_keys(table_name),
                        "sample_rows": self._db.get_sample_rows(table_name),
                    }
                }
            else:
                # Full database schema
                schema = self._db.get_full_schema()

            return ToolResult(
                success=True,
                data=schema,
                metadata={"table_count": len(schema)},
            )
        except Exception as exc:
            return ToolResult(success=False, error=str(exc))
