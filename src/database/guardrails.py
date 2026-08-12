"""
LLMSQL SQL Guardrails Module

Provides token-based statement validation using sqlparse to enforce
read-only query execution. This is NOT an AST parser — sqlparse is a
tokenizer/formatter. We use it for statement-type detection and
multi-statement blocking, which is sufficient for our security model.

Blocked operations:
  INSERT, UPDATE, DELETE, DROP, TRUNCATE, ALTER, CREATE,
  ATTACH, DETACH, PRAGMA, GRANT, REVOKE, EXEC/EXECUTE

Also blocks:
  - Stacked multi-statements (queries containing ';' separators)
  - Empty or whitespace-only queries

Provides safe LIMIT injection that respects existing LIMIT clauses.
"""

from __future__ import annotations

import re
from dataclasses import dataclass

import sqlparse
from sqlparse.sql import Statement
from sqlparse.tokens import Keyword, DML, DDL


@dataclass
class GuardrailResult:
    """Result of a guardrail validation check.

    Attributes:
        is_safe:   True if the query passes all safety checks.
        query:     The (possibly modified) query string.
        violation: Human-readable reason for rejection (None if safe).
    """

    is_safe: bool
    query: str = ""
    violation: str | None = None


# Dangerous statement types that must never execute
_BLOCKED_KEYWORDS: set[str] = {
    "INSERT",
    "UPDATE",
    "DELETE",
    "DROP",
    "TRUNCATE",
    "ALTER",
    "CREATE",
    "ATTACH",
    "DETACH",
    "PRAGMA",
    "GRANT",
    "REVOKE",
    "EXEC",
    "EXECUTE",
    "REPLACE",
    "MERGE",
    "CALL",
}

# Maximum rows returned by any single query
DEFAULT_ROW_LIMIT = 1000


def validate_sql(raw_sql: str, max_rows: int = DEFAULT_ROW_LIMIT) -> GuardrailResult:
    """Validate a SQL string for safe, read-only execution.

    Steps:
        1. Reject empty / whitespace-only input.
        2. Parse with sqlparse; reject if multiple statements found.
        3. Tokenize the single statement; reject if any blocked keyword appears
           in a DML/DDL/Keyword position.
        4. Confirm the first meaningful keyword is SELECT (or WITH for CTEs).
        5. Inject or preserve a LIMIT clause capped at *max_rows*.

    Args:
        raw_sql:  The raw SQL string from the LLM.
        max_rows: Maximum number of rows to allow (default 1000).

    Returns:
        A GuardrailResult indicating safety and the sanitised query.
    """

    # --- 1. Empty check ---
    stripped = raw_sql.strip().rstrip(";").strip()
    if not stripped:
        return GuardrailResult(is_safe=False, violation="Empty query provided.")

    # --- 2. Multi-statement check ---
    parsed_statements = sqlparse.parse(stripped)
    real_statements = [
        s for s in parsed_statements if s.get_type() is not None or str(s).strip()
    ]
    if len(real_statements) > 1:
        return GuardrailResult(
            is_safe=False,
            violation="Multi-statement queries are not allowed (detected ';' stacking).",
        )

    if not real_statements:
        return GuardrailResult(is_safe=False, violation="Could not parse any SQL statement.")

    stmt: Statement = real_statements[0]

    # --- 3. Token-level blocked keyword scan ---
    for token in stmt.flatten():
        word = token.ttype
        value_upper = token.value.upper().strip()
        if word in (DML, DDL, Keyword) and value_upper in _BLOCKED_KEYWORDS:
            return GuardrailResult(
                is_safe=False,
                violation=f"Blocked operation detected: {value_upper}",
            )

    # --- 4. Confirm statement starts with SELECT or WITH ---
    stmt_type = stmt.get_type()
    if stmt_type and stmt_type.upper() not in ("SELECT", "UNKNOWN"):
        return GuardrailResult(
            is_safe=False,
            violation=f"Only SELECT queries are allowed. Detected: {stmt_type}",
        )

    # Extra safety: make sure the first keyword token is SELECT or WITH
    first_keyword = _first_keyword(stmt)
    if first_keyword not in ("SELECT", "WITH"):
        return GuardrailResult(
            is_safe=False,
            violation=f"Query must begin with SELECT or WITH. Found: {first_keyword}",
        )

    # --- 5. Safe LIMIT injection ---
    safe_query = _apply_limit(stripped, max_rows)

    return GuardrailResult(is_safe=True, query=safe_query)


# --------------------------------------------------------------------------
# Internal helpers
# --------------------------------------------------------------------------

def _first_keyword(stmt: Statement) -> str:
    """Return the first DML/DDL/Keyword token value (uppercased)."""
    for token in stmt.flatten():
        if token.ttype in (DML, DDL, Keyword) and token.value.strip():
            return token.value.upper().strip()
    return ""


def _apply_limit(sql: str, max_rows: int) -> str:
    """Ensure the query has a LIMIT clause ≤ max_rows.

    If a LIMIT already exists and its value is ≤ max_rows, keep it.
    If a LIMIT exists but exceeds max_rows, cap it.
    If no LIMIT exists, append one.
    """
    # Regex to find an existing LIMIT <number> clause (case-insensitive)
    limit_pattern = re.compile(
        r"\bLIMIT\s+(\d+)\b", re.IGNORECASE
    )
    match = limit_pattern.search(sql)

    if match:
        existing_limit = int(match.group(1))
        if existing_limit > max_rows:
            sql = limit_pattern.sub(f"LIMIT {max_rows}", sql, count=1)
    else:
        sql = f"{sql}\nLIMIT {max_rows}"

    return sql
