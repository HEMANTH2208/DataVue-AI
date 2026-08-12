"""
LLMSQL VisualizeDataTool

Purpose:
    Analyze tabular query results and generate an appropriate interactive
    chart specification using Plotly JSON format. The chart type is
    selected automatically based on data shape and query intent.

Chart Selection Logic (select_chart_type):
    - Categorical comparison ("top N", "by category") → Bar chart
    - Time-series / trend (date/time column detected)  → Line chart
    - Proportional / share-of-whole ("distribution", "%") → Pie chart
    - Two numeric columns, correlation intent → Scatter plot

Parameters:
    columns (list[str]): Column names from query result.
    rows (list[dict]):   Row data from query result.
    query_intent (str):  Original natural language question for context.

Returns:
    ToolResult containing Plotly chart JSON specification.
"""

from __future__ import annotations

import re
from typing import Any

from src.tools.base import Tool, ToolResult


# ---------------------------------------------------------------------------
# Date detection helpers
# ---------------------------------------------------------------------------

_DATE_COLUMN_PATTERNS = re.compile(
    r"(date|time|month|year|week|day|quarter|period|created|updated|joined|timestamp)",
    re.IGNORECASE,
)

_DATE_VALUE_PATTERN = re.compile(
    r"^\d{4}[-/]\d{1,2}([-/]\d{1,2})?",  # e.g. 2025-01-15, 2025/7
)


def _is_numeric(value: Any) -> bool:
    """Check if a value is numeric (int or float)."""
    if isinstance(value, (int, float)):
        return True
    if isinstance(value, str):
        try:
            float(value)
            return True
        except (ValueError, TypeError):
            return False
    return False


def _is_date_column(col_name: str, sample_values: list[Any]) -> bool:
    """Heuristic: is this column likely a date/time column?"""
    if _DATE_COLUMN_PATTERNS.search(col_name):
        return True
    # Check sample values
    for val in sample_values[:5]:
        if isinstance(val, str) and _DATE_VALUE_PATTERN.match(val):
            return True
    return False


def _classify_columns(
    columns: list[str], rows: list[dict]
) -> dict[str, list[str]]:
    """Classify columns into categories: date, numeric, categorical."""
    classification: dict[str, list[str]] = {
        "date": [],
        "numeric": [],
        "categorical": [],
    }

    for col in columns:
        sample_values = [row.get(col) for row in rows[:20] if row.get(col) is not None]
        if not sample_values:
            classification["categorical"].append(col)
            continue

        if _is_date_column(col, sample_values):
            classification["date"].append(col)
        elif all(_is_numeric(v) for v in sample_values):
            classification["numeric"].append(col)
        else:
            classification["categorical"].append(col)

    return classification


# ---------------------------------------------------------------------------
# Intent detection keywords
# ---------------------------------------------------------------------------

_TREND_KEYWORDS = {"trend", "over time", "monthly", "weekly", "daily", "yearly", "growth", "timeline", "history"}
_PROPORTION_KEYWORDS = {"distribution", "proportion", "percentage", "share", "breakdown", "pie", "% of", "ratio"}
_COMPARISON_KEYWORDS = {"top", "best", "worst", "highest", "lowest", "compare", "ranking", "most", "least"}
_CORRELATION_KEYWORDS = {"correlation", "relationship", "scatter", "vs", "versus", "against"}


def select_chart_type(
    columns: list[str],
    rows: list[dict],
    query_intent: str = "",
) -> str:
    """Determine the best chart type based on data shape and query intent.

    Returns one of: 'bar', 'line', 'pie', 'scatter', 'horizontal_bar', 'table'
    """
    intent_lower = query_intent.lower()
    classification = _classify_columns(columns, rows)

    has_dates = len(classification["date"]) > 0
    has_numeric = len(classification["numeric"]) > 0
    has_categorical = len(classification["categorical"]) > 0
    num_numeric = len(classification["numeric"])

    # Rule 1: Explicit intent keywords override data shape
    if any(kw in intent_lower for kw in _TREND_KEYWORDS) and has_dates:
        return "line"
    if any(kw in intent_lower for kw in _PROPORTION_KEYWORDS):
        return "pie"
    if any(kw in intent_lower for kw in _CORRELATION_KEYWORDS) and num_numeric >= 2:
        return "scatter"

    # Rule 2: Data-shape driven selection
    if has_dates and has_numeric:
        return "line"
    if has_categorical and has_numeric and len(rows) <= 15:
        return "bar"
    if has_categorical and has_numeric and len(rows) > 15:
        return "horizontal_bar"
    if num_numeric >= 2 and not has_categorical and not has_dates:
        return "scatter"

    # Rule 3: Small categorical dataset with single numeric → pie
    if has_categorical and has_numeric and len(rows) <= 8:
        return "pie"

    # Fallback
    if has_categorical and has_numeric:
        return "bar"

    return "table"


def _build_plotly_spec(
    chart_type: str,
    columns: list[str],
    rows: list[dict],
    classification: dict[str, list[str]],
    query_intent: str,
) -> dict[str, Any]:
    """Build a Plotly JSON chart specification."""

    # Determine x and y axes based on classification
    date_cols = classification["date"]
    numeric_cols = classification["numeric"]
    cat_cols = classification["categorical"]

    x_col = date_cols[0] if date_cols else (cat_cols[0] if cat_cols else columns[0])
    y_col = numeric_cols[0] if numeric_cols else columns[-1]

    x_values = [row.get(x_col) for row in rows]
    y_values = [row.get(y_col) for row in rows]

    # Additional y columns for multi-series
    extra_y_cols = [c for c in numeric_cols if c != y_col]

    spec: dict[str, Any] = {"data": [], "layout": {}}

    if chart_type == "bar":
        spec["data"].append({
            "type": "bar",
            "x": x_values,
            "y": y_values,
            "name": y_col,
            "marker": {"color": "#6366f1", "cornerradius": 6},
        })
        for extra_col in extra_y_cols[:2]:
            spec["data"].append({
                "type": "bar",
                "x": x_values,
                "y": [row.get(extra_col) for row in rows],
                "name": extra_col,
            })
        spec["layout"] = {
            "title": {"text": query_intent or f"{y_col} by {x_col}"},
            "xaxis": {"title": {"text": x_col}},
            "yaxis": {"title": {"text": y_col}},
            "template": "plotly_dark",
            "paper_bgcolor": "rgba(0,0,0,0)",
            "plot_bgcolor": "rgba(0,0,0,0)",
            "barmode": "group" if extra_y_cols else "relative",
        }

    elif chart_type == "horizontal_bar":
        spec["data"].append({
            "type": "bar",
            "y": x_values,
            "x": y_values,
            "name": y_col,
            "orientation": "h",
            "marker": {"color": "#6366f1", "cornerradius": 6},
        })
        spec["layout"] = {
            "title": {"text": query_intent or f"{y_col} by {x_col}"},
            "xaxis": {"title": {"text": y_col}},
            "yaxis": {"title": {"text": x_col}, "autorange": "reversed"},
            "template": "plotly_dark",
            "paper_bgcolor": "rgba(0,0,0,0)",
            "plot_bgcolor": "rgba(0,0,0,0)",
        }

    elif chart_type == "line":
        spec["data"].append({
            "type": "scatter",
            "mode": "lines+markers",
            "x": x_values,
            "y": y_values,
            "name": y_col,
            "line": {"color": "#6366f1", "width": 3},
            "marker": {"size": 6},
        })
        for extra_col in extra_y_cols[:3]:
            spec["data"].append({
                "type": "scatter",
                "mode": "lines+markers",
                "x": x_values,
                "y": [row.get(extra_col) for row in rows],
                "name": extra_col,
            })
        spec["layout"] = {
            "title": {"text": query_intent or f"{y_col} over {x_col}"},
            "xaxis": {"title": {"text": x_col}},
            "yaxis": {"title": {"text": y_col}},
            "template": "plotly_dark",
            "paper_bgcolor": "rgba(0,0,0,0)",
            "plot_bgcolor": "rgba(0,0,0,0)",
        }

    elif chart_type == "pie":
        spec["data"].append({
            "type": "pie",
            "labels": x_values,
            "values": y_values,
            "hole": 0.4,
            "marker": {
                "colors": [
                    "#6366f1", "#8b5cf6", "#a78bfa", "#c4b5fd",
                    "#ddd6fe", "#ede9fe", "#f5f3ff", "#4f46e5",
                ]
            },
            "textinfo": "label+percent",
        })
        spec["layout"] = {
            "title": {"text": query_intent or f"Distribution of {y_col}"},
            "template": "plotly_dark",
            "paper_bgcolor": "rgba(0,0,0,0)",
            "plot_bgcolor": "rgba(0,0,0,0)",
        }

    elif chart_type == "scatter":
        x_col_s = numeric_cols[0] if len(numeric_cols) >= 2 else columns[0]
        y_col_s = numeric_cols[1] if len(numeric_cols) >= 2 else columns[-1]
        spec["data"].append({
            "type": "scatter",
            "mode": "markers",
            "x": [row.get(x_col_s) for row in rows],
            "y": [row.get(y_col_s) for row in rows],
            "marker": {"color": "#6366f1", "size": 8, "opacity": 0.7},
        })
        spec["layout"] = {
            "title": {"text": query_intent or f"{y_col_s} vs {x_col_s}"},
            "xaxis": {"title": {"text": x_col_s}},
            "yaxis": {"title": {"text": y_col_s}},
            "template": "plotly_dark",
            "paper_bgcolor": "rgba(0,0,0,0)",
            "plot_bgcolor": "rgba(0,0,0,0)",
        }

    else:
        # Table fallback — return raw data
        spec = {"chart_type": "table", "columns": columns, "rows": rows}

    return spec


class VisualizeDataTool(Tool):
    """Generate interactive Plotly chart specifications from query results."""

    @property
    def name(self) -> str:
        return "generate_chart"

    @property
    def description(self) -> str:
        return (
            "Generate an interactive chart from tabular query results. "
            "Automatically selects the best chart type (bar, line, pie, scatter) "
            "based on data shape and query intent. Returns a Plotly JSON spec "
            "for frontend rendering."
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
                    "description": "Row data as list of dicts from query result.",
                },
                "query_intent": {
                    "type": "string",
                    "description": "The original natural language question for context.",
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
                error="No data provided for visualization.",
            )

        try:
            chart_type = select_chart_type(columns, rows, query_intent)
            classification = _classify_columns(columns, rows)
            plotly_spec = _build_plotly_spec(
                chart_type, columns, rows, classification, query_intent
            )

            return ToolResult(
                success=True,
                data={
                    "chart_type": chart_type,
                    "plotly_spec": plotly_spec,
                },
                metadata={
                    "selected_chart_type": chart_type,
                    "data_points": len(rows),
                    "column_classification": {k: v for k, v in classification.items() if v},
                },
            )
        except Exception as exc:
            return ToolResult(success=False, error=str(exc))
