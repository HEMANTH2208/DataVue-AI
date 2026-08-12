"""
LLMSQL SystemDiagramTool

Purpose:
    Generate Mermaid.js markup for ER diagrams (database structure) or
    process flowcharts (workflow logic) based on user questions about
    system architecture, data relationships, or business processes.

Parameters:
    diagram_type (str):  "er" for ER diagram, "flowchart" for process flow.
    schema (dict):       Database schema metadata (for ER diagrams).
    description (str):   Natural language description (for flowcharts).

Returns:
    ToolResult containing Mermaid.js markup string.
"""

from __future__ import annotations

from typing import Any

from src.tools.base import Tool, ToolResult


def _build_er_diagram(schema: dict[str, Any]) -> str:
    """Build a Mermaid erDiagram from database schema metadata."""
    lines = ["erDiagram"]

    # Collect all foreign key relationships
    relationships: list[str] = []
    for table_name, table_info in schema.items():
        fks = table_info.get("foreign_keys", [])
        for fk in fks:
            from_col = fk.get("from_column", "")
            to_table = fk.get("to_table", "")
            to_col = fk.get("to_column", "")
            relationships.append(
                f'    {to_table} ||--o{{ {table_name} : "{from_col} -> {to_col}"'
            )

    # Add relationships
    for rel in relationships:
        lines.append(rel)

    # Add entity definitions with column details
    for table_name, table_info in schema.items():
        lines.append(f"    {table_name} {{")
        columns = table_info.get("columns", [])
        for col in columns:
            col_type = col.get("type", "TEXT").replace(" ", "_")
            col_name = col.get("name", "unknown")
            pk_marker = " PK" if col.get("is_primary_key") else ""
            lines.append(f"        {col_type} {col_name}{pk_marker}")
        lines.append("    }")

    return "\n".join(lines)


def _build_flowchart_dynamically(description: str) -> str:
    """Use active LLM to dynamically generate Mermaid flowchart markup from a description."""
    if not description:
        return _build_flowchart("") # Fallback to default
        
    from src.services.llm_service import create_llm_service
    try:
        llm = create_llm_service()
        # Prevent infinite recursion if the service is mock and would trigger diagrammer
        if llm.__class__.__name__ == "MockProvider":
            return _build_flowchart(description)

        messages = [
            {
                "role": "system",
                "content": (
                    "You are an expert systems diagram designer. Generate Mermaid.js flowchart markup "
                    "based on the user's description. Use 'graph TD' or 'graph LR' or 'graph TB' appropriately. "
                    "Return ONLY the raw Mermaid markup starting with 'graph' or 'flowchart'. Do not wrap it in "
                    "markdown code blocks or add any additional explanation. Keep node labels short and concise."
                ),
            },
            {"role": "user", "content": f"Create a flowchart for: {description}"},
        ]
        response = llm.chat(messages)
        markup = response.content.strip()
        # Clean up code block wrappers if any
        if markup.startswith("```"):
            lines = markup.split("\n")
            if lines[0].startswith("```"):
                lines = lines[1:]
            if lines[-1].startswith("```"):
                lines = lines[:-1]
            markup = "\n".join(lines).strip()
        return markup
    except Exception as e:
        print(f"[Diagrammer Error] Failed to generate dynamic flowchart: {e}")
        return _build_flowchart(description) # Fallback to default


def _build_flowchart(description: str) -> str:
    """Build a Mermaid flowchart from a process description.

    For the LLMSQL agent, this generates the default agent workflow diagram.
    """
    # Default: DataMind AI agent workflow
    return """graph TD
    A[User Natural Language Question] --> B[DataMind AI Agent Controller]
    B --> C{Classify Intent}
    C -->|Schema Question| D[SchemaDiscoveryTool]
    C -->|Data Query| E[LLM Generates SQL]
    C -->|Architecture Query| F[SystemDiagramTool]
    
    D --> G[Return Schema Metadata]
    E --> H[ExecuteQueryTool]
    H --> I{Query Results}
    I --> J[VisualizeDataTool]
    I --> K[ExplainInsightsTool]
    F --> L[Generate Mermaid Diagram]
    
    J --> M[Interactive Chart]
    K --> N[Executive Summary]
    L --> O[ER/Flowchart Diagram]
    G --> P[Schema Display]
    
    M --> Q[Complete Agent Response]
    N --> Q
    O --> Q
    P --> Q
    
    style A fill:#6366f1,color:#fff
    style Q fill:#22c55e,color:#fff
    style B fill:#8b5cf6,color:#fff"""


class SystemDiagramTool(Tool):
    """Generate Mermaid.js ER diagrams or workflow flowcharts."""

    def __init__(self, db_manager: Any = None) -> None:
        self._db = db_manager

    @property
    def name(self) -> str:
        return "generate_flowchart"

    @property
    def description(self) -> str:
        return (
            "Generate a Mermaid.js diagram. Use diagram_type='er' with database "
            "schema to create an Entity-Relationship diagram showing tables and "
            "their relationships. Use diagram_type='flowchart' to generate a "
            "process flow diagram."
        )

    @property
    def parameters_schema(self) -> dict[str, Any]:
        return {
            "type": "object",
            "properties": {
                "diagram_type": {
                    "type": "string",
                    "enum": ["er", "flowchart"],
                    "description": "'er' for ER diagram, 'flowchart' for process flow.",
                },
                "schema": {
                    "type": "object",
                    "description": "Database schema metadata (for ER diagrams).",
                },
                "description": {
                    "type": "string",
                    "description": "Process description (for flowcharts).",
                },
            },
            "required": ["diagram_type"],
        }

    def run(self, **kwargs: Any) -> ToolResult:
        diagram_type: str = kwargs.get("diagram_type", "er")
        schema: dict | None = kwargs.get("schema")
        description: str = kwargs.get("description", "")

        try:
            if diagram_type == "er":
                # If no schema provided, fetch from database manager
                if not schema and self._db:
                    schema = self._db.get_full_schema()
                if not schema:
                    return ToolResult(
                        success=False,
                        error="No schema data available for ER diagram generation.",
                    )
                mermaid_markup = _build_er_diagram(schema)
            elif diagram_type == "flowchart":
                mermaid_markup = _build_flowchart_dynamically(description)
            else:
                return ToolResult(
                    success=False,
                    error=f"Unknown diagram type: {diagram_type}. Use 'er' or 'flowchart'.",
                )

            return ToolResult(
                success=True,
                data={
                    "diagram_type": diagram_type,
                    "mermaid_markup": mermaid_markup,
                },
                metadata={"diagram_type": diagram_type},
            )
        except Exception as exc:
            return ToolResult(success=False, error=str(exc))
