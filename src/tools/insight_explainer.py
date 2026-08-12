"""
LLMSQL ExplainInsightsTool

Purpose:
    Compute summary statistics from tabular query results and generate
    a natural-language executive summary. Identifies top values, totals,
    averages, percentage breakdowns, and notable patterns.

Parameters:
    columns (list[str]): Column names from query result.
    rows (list[dict]):   Row data from query result.
    query_intent (str):  Original natural language question.

Returns:
    ToolResult containing computed statistics and formatted explanation.
"""

from __future__ import annotations

from typing import Any

from src.tools.base import Tool, ToolResult


def _compute_statistics(columns: list[str], rows: list[dict]) -> dict[str, Any]:
    """Compute summary statistics across all numeric columns."""
    stats: dict[str, Any] = {
        "row_count": len(rows),
        "column_count": len(columns),
        "numeric_summaries": {},
        "top_values": {},
    }

    for col in columns:
        values = [row.get(col) for row in rows if row.get(col) is not None]
        if not values:
            continue

        # Check if numeric
        numeric_values = []
        for v in values:
            try:
                numeric_values.append(float(v))
            except (ValueError, TypeError):
                pass

        if numeric_values and len(numeric_values) == len(values):
            total = sum(numeric_values)
            avg = total / len(numeric_values)
            stats["numeric_summaries"][col] = {
                "total": round(total, 2),
                "average": round(avg, 2),
                "min": round(min(numeric_values), 2),
                "max": round(max(numeric_values), 2),
                "count": len(numeric_values),
            }

            # Find top and bottom entries
            if len(rows) > 1:
                # Try to find a label column
                label_col = None
                for c in columns:
                    if c != col:
                        label_col = c
                        break

                if label_col:
                    sorted_rows = sorted(
                        rows,
                        key=lambda r: float(r.get(col, 0) or 0),
                        reverse=True,
                    )
                    stats["top_values"][col] = {
                        "leader": {
                            "label": sorted_rows[0].get(label_col),
                            "value": sorted_rows[0].get(col),
                        },
                        "runner_up": {
                            "label": sorted_rows[1].get(label_col) if len(sorted_rows) > 1 else None,
                            "value": sorted_rows[1].get(col) if len(sorted_rows) > 1 else None,
                        },
                    }

                    # Percentage contribution of leader
                    if total > 0:
                        leader_val = float(sorted_rows[0].get(col, 0) or 0)
                        stats["top_values"][col]["leader_share_pct"] = round(
                            (leader_val / total) * 100, 1
                        )

    return stats


def _is_monetary_column(col_name: str) -> bool:
    """Determine if a column is monetary based on its name."""
    name_lower = col_name.lower()
    return any(kw in name_lower for kw in ["price", "revenue", "sales", "amount", "total", "value", "cost"])


def _format_explanation(
    stats: dict[str, Any],
    query_intent: str,
    columns: list[str],
    rows: list[dict],
) -> str:
    """Generate a plain-English executive summary from computed statistics, using Indian currency rules."""
    parts: list[str] = []

    row_count = stats["row_count"]
    parts.append(f"The query returned **{row_count} results**.")

    # Summarise each numeric column
    for col, summary in stats.get("numeric_summaries", {}).items():
        is_money = _is_monetary_column(col)
        prefix = "₹" if is_money else ""
        parts.append(
            f"For **{col}**: total = {prefix}{summary['total']:,.2f}, "
            f"average = {prefix}{summary['average']:,.2f}, "
            f"range = {prefix}{summary['min']:,.2f} – {prefix}{summary['max']:,.2f}."
        )

    # Top value insights
    for col, top_info in stats.get("top_values", {}).items():
        leader = top_info.get("leader", {})
        runner = top_info.get("runner_up", {})
        share = top_info.get("leader_share_pct")
        is_money = _is_monetary_column(col)
        prefix = "₹" if is_money else ""

        if leader.get("label"):
            try:
                leader_val = float(leader["value"])
                val_str = f"{prefix}{leader_val:,.2f}"
            except (ValueError, TypeError):
                val_str = str(leader["value"])

            insight = f"**{leader['label']}** leads in {col} with **{val_str}**"
            if share:
                insight += f" ({share}% of total)"
            insight += "."
            parts.append(insight)

        if runner.get("label") and leader.get("value") and runner.get("value"):
            try:
                diff = float(leader["value"]) - float(runner["value"])
                parts.append(
                    f"It is ahead of {runner['label']} by {prefix}{diff:,.2f}."
                )
            except (ValueError, TypeError):
                pass

    return "\n\n".join(parts)


class ExplainInsightsTool(Tool):
    """Generate natural-language executive summaries from query results."""

    @property
    def name(self) -> str:
        return "explain_data"

    @property
    def description(self) -> str:
        return (
            "Analyze tabular query results and produce a plain-English executive "
            "summary with key statistics, top values, percentage breakdowns, and "
            "notable patterns. Use after executing a query to give the user a "
            "human-readable explanation of the data."
        )

    @property
    def parameters_schema(self) -> dict[str, Any]:
        return {
            "type": "object",
            "properties": {
                "columns": {
                    "type": "array",
                    "items": {"type": "string"},
                    "description": "Column names from the query result.",
                },
                "rows": {
                    "type": "array",
                    "items": {"type": "object"},
                    "description": "Row data from query result.",
                },
                "query_intent": {
                    "type": "string",
                    "description": "The original natural language question.",
                },
            },
            "required": ["columns", "rows"],
        }

    def run(self, **kwargs: Any) -> ToolResult:
        columns: list[str] = kwargs.get("columns", [])
        rows: list[dict] = kwargs.get("rows", [])
        query_intent: str = kwargs.get("query_intent", "")

        if not columns or not rows:
            return ToolResult(
                success=False,
                error="No data provided for insight generation.",
            )

        try:
            stats = _compute_statistics(columns, rows)
            explanation = _format_explanation(stats, query_intent, columns, rows)

            return ToolResult(
                success=True,
                data={
                    "statistics": stats,
                    "explanation": explanation,
                },
                metadata={"insight_sections": len(explanation.split("\n\n"))},
            )
        except Exception as exc:
            return ToolResult(success=False, error=str(exc))
