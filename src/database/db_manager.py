"""
LLMSQL Database Manager

Unified database connection manager providing schema introspection,
query execution, and connection lifecycle management.

Phase 1 (MVP): SQLite support only.
Phase 2 (Stretch): PostgreSQL and MongoDB read-only connectors.
"""

from __future__ import annotations

import sqlite3
from pathlib import Path
from typing import Any


class DatabaseManager:
    """Manages database connections and provides schema/query operations.

    Attributes:
        db_path: Absolute or relative path to the SQLite database file.
    """

    def __init__(self, db_path: str) -> None:
        self.db_path = db_path
        self._validate_path()

    # ------------------------------------------------------------------
    # Connection helpers
    # ------------------------------------------------------------------

    def _validate_path(self) -> None:
        """Ensure the database file exists."""
        if not Path(self.db_path).exists():
            raise FileNotFoundError(f"Database not found: {self.db_path}")

    def _connect(self) -> sqlite3.Connection:
        """Open a new SQLite connection with row_factory enabled."""
        conn = sqlite3.connect(self.db_path)
        conn.row_factory = sqlite3.Row
        return conn

    # ------------------------------------------------------------------
    # Schema introspection
    # ------------------------------------------------------------------

    def get_tables(self) -> list[str]:
        """Return a list of all user table names in the database."""
        conn = self._connect()
        try:
            cursor = conn.execute(
                "SELECT name FROM sqlite_master WHERE type='table' "
                "AND name NOT LIKE 'sqlite_%' ORDER BY name"
            )
            return [row["name"] for row in cursor.fetchall()]
        finally:
            conn.close()

    def get_table_schema(self, table_name: str) -> list[dict[str, Any]]:
        """Return column metadata for a specific table.

        Each entry contains: cid, name, type, notnull, default_value, pk.
        """
        conn = self._connect()
        try:
            cursor = conn.execute(f"PRAGMA table_info('{table_name}')")
            columns = []
            for row in cursor.fetchall():
                columns.append({
                    "column_id": row["cid"],
                    "name": row["name"],
                    "type": row["type"],
                    "not_null": bool(row["notnull"]),
                    "default_value": row["dflt_value"],
                    "is_primary_key": bool(row["pk"]),
                })
            return columns
        finally:
            conn.close()

    def get_foreign_keys(self, table_name: str) -> list[dict[str, str]]:
        """Return foreign key relationships for a table."""
        conn = self._connect()
        try:
            cursor = conn.execute(f"PRAGMA foreign_key_list('{table_name}')")
            fks = []
            for row in cursor.fetchall():
                fks.append({
                    "from_column": row["from"],
                    "to_table": row["table"],
                    "to_column": row["to"],
                })
            return fks
        finally:
            conn.close()

    def get_sample_rows(self, table_name: str, limit: int = 5) -> list[dict[str, Any]]:
        """Return a small sample of rows from a table for LLM context."""
        conn = self._connect()
        try:
            cursor = conn.execute(f"SELECT * FROM '{table_name}' LIMIT {limit}")
            columns = [desc[0] for desc in cursor.description]
            rows = []
            for row in cursor.fetchall():
                rows.append(dict(zip(columns, row)))
            return rows
        finally:
            conn.close()

    def get_full_schema(self) -> dict[str, Any]:
        """Return complete schema metadata for all tables.

        Returns a dict keyed by table name, each containing:
          columns, foreign_keys, sample_rows, row_count
        """
        schema: dict[str, Any] = {}
        tables = self.get_tables()

        conn = self._connect()
        try:
            for table in tables:
                row_count_cursor = conn.execute(f"SELECT COUNT(*) as cnt FROM '{table}'")
                row_count = row_count_cursor.fetchone()["cnt"]

                schema[table] = {
                    "columns": self.get_table_schema(table),
                    "foreign_keys": self.get_foreign_keys(table),
                    "sample_rows": self.get_sample_rows(table),
                    "row_count": row_count,
                }
        finally:
            conn.close()

        return schema

    # ------------------------------------------------------------------
    # Query execution
    # ------------------------------------------------------------------

    def execute_query(self, sql: str) -> dict[str, Any]:
        """Execute a read-only SQL query and return structured results.

        Assumes the query has already passed guardrails validation.

        Returns:
            dict with keys: columns, rows, row_count
        """
        conn = self._connect()
        try:
            cursor = conn.execute(sql)
            columns = [desc[0] for desc in cursor.description] if cursor.description else []
            raw_rows = cursor.fetchall()
            rows = [dict(zip(columns, row)) for row in raw_rows]
            return {
                "columns": columns,
                "rows": rows,
                "row_count": len(rows),
            }
        except Exception as exc:
            raise RuntimeError(f"Query execution failed: {exc}") from exc
        finally:
            conn.close()
