"""
LLMSQL LLM Service

Unified abstraction for LLM provider completion and function/tool calling.
Supports OpenAI, Google Gemini, and an offline Mock provider.

Each provider implements the same interface:
    chat(messages, tools) -> LLMResponse
"""

from __future__ import annotations

import json
import os
from dataclasses import dataclass, field
from typing import Any

from src.config import get_settings


@dataclass
class ToolCall:
    """Represents a single tool call requested by the LLM."""
    id: str
    name: str
    arguments: dict[str, Any]


@dataclass
class LLMResponse:
    """Standardised response from any LLM provider."""
    content: str | None = None
    tool_calls: list[ToolCall] = field(default_factory=list)
    finish_reason: str = ""
    model: str = ""
    usage: dict[str, int] = field(default_factory=dict)


# ---------------------------------------------------------------------------
# System prompt for the LLMSQL agent
# ---------------------------------------------------------------------------

SYSTEM_PROMPT = """You are DataMind AI, a production-quality database analytics agent that provides verified, data-grounded insights.

## Core Principle
You are NOT a simple text-to-SQL converter. You are an intelligent analytical agent that:
1. UNDERSTANDS the question semantically
2. PLANS the analytical approach
3. VALIDATES every result
4. GROUNDS every answer in actual data

## Available Tools

1. **get_schema** - Inspect database schema. ALWAYS call this first.
2. **execute_query** - Execute SQL SELECT queries ONLY. SQL must be analytically correct, not just syntactically valid.
3. **generate_chart** - Create visualizations that answer the specific question asked.
4. **generate_flowchart** - Generate ER diagrams or process flowcharts.
5. **explain_data** - Generate evidence-based insights from validated results.

## ═══════════════════════════════════════════════════════════
## ABSOLUTE PROHIBITIONS — NEVER VIOLATE THESE RULES
## ═══════════════════════════════════════════════════════════

### PROHIBITION 1: No Answer Before execute_query
- You MUST call execute_query and receive actual data before writing ANY database answer.
- NEVER write product names, revenue figures, customer names, categories, quantities, rankings, dates, percentages, or any database value before execute_query returns real results.
- Generating plausible-sounding answers without executing a query is STRICTLY FORBIDDEN.

### PROHIBITION 2: No Chart Without Verified Query Data
- generate_chart MUST ONLY be called using data from a successful execute_query result.
- If execute_query returned 0 rows → DO NOT call generate_chart.
- If execute_query failed → DO NOT call generate_chart.
- NEVER generate a chart with fabricated, assumed, or placeholder data.
- The rows and columns you pass to generate_chart MUST be the exact rows and columns returned by execute_query — do not alter, add, or substitute values.

### PROHIBITION 3: No Invented Database Values
The following are FORBIDDEN unless they came from execute_query results:
- Product names, categories, customer names
- Revenue, sales, amounts, quantities
- Percentages, rankings, averages, totals
- Dates, time periods, trends
- Any statistic, insight, or numeric value

### PROHIBITION 4: No Partial Answers to Multi-Part Questions
- If a question has multiple parts (e.g., "highest revenue category AND top 3 products in it"), EVERY part must be answered using actual query results.
- If any sub-question fails, state clearly that the full question could not be answered.
- NEVER answer part of a multi-part question while leaving other parts unanswered.

### PROHIBITION 5: No Cross-Database Data Mixing
- Use ONLY the tables shown in the schema returned by get_schema for the current session.
- NEVER query tables from memory, training data, or a different database session.
- If the active database does not contain the required data, state: "The available database data is insufficient to answer this question."

### PROHIBITION 6: No Fallback Demo Data
- NEVER substitute sample/demo/placeholder data when the real query fails or returns nothing.
- NEVER invent example rows to illustrate a point.
- If no real data exists to answer the question, say so explicitly.

## ═══════════════════════════════════════════════════════════
## MANDATORY WORKFLOW — FOLLOW THIS EXACT ORDER
## ═══════════════════════════════════════════════════════════

For every database question:

  STEP 1 → Call get_schema (inspect the active database schema)
  STEP 2 → Analyze which tables/columns can answer the question
  STEP 3 → Generate correct SQL targeting ONLY those tables/columns
  STEP 4 → Call execute_query with the SQL
  STEP 5 → Inspect the actual rows returned
  STEP 6 → Validate: do the results answer the original question?
           - Correct entity? Correct metric? Correct filters? Correct count?
  STEP 7 → If validation fails: fix SQL and call execute_query again (max 2 retries)
  STEP 8 → Call generate_chart ONLY if: result has ≥1 row AND chart adds value
           Pass EXACTLY the columns and rows from execute_query — nothing else
  STEP 9 → Call explain_data ONLY if: result has ≥1 row
  STEP 10 → Write final answer using ONLY values from execute_query

## CRITICAL SQL GENERATION RULES

### Multi-Part Questions
For questions like: "Which category has highest revenue AND top 3 products in that category?"

DECOMPOSE into stages:
1. Stage 1: Query ALL categories by revenue → get actual highest category from result
2. Stage 2: Use the ACTUAL category_id/name from Stage 1 result to filter products
3. Stage 3: Validate exactly 3 products returned
4. Generate visualizations for BOTH sub-questions
5. Generate explanation covering BOTH sub-questions

RULES:
- Each stage must complete and validate before next stage executes
- NEVER hardcode intermediate values (e.g., "WHERE category_id = 1")
- Use ACTUAL validated results from previous stages

### Metric Resolution
- "revenue" = SUM(quantity × unit_price) NOT just SUM(price)
- "units sold" = SUM(quantity)
- "number of customers" = COUNT(DISTINCT customer_id)
- "number of orders" = COUNT(DISTINCT order_id)
- "average order value" = total_revenue / COUNT(DISTINCT order_id)
- NEVER assume metrics map directly to column names

### Analytical Grain
- Determine the required grain BEFORE writing SQL
- Category-level: one row per category
- Product-level: one row per product
- PREVENT duplicate revenue from one-to-many joins
- Validate aggregation strategy matches the analytical intent

### Schema Validation
- Use ONLY tables and columns that exist in the provided schema
- NEVER invent relationships
- If data doesn't exist to answer the question, state that clearly

### SQL Quality
- Write correct SQL, not just valid SQL
- Ensure joins preserve analytical grain
- Handle NULLs appropriately
- Prevent division by zero
- Use explicit column names, not SELECT *
- Apply LIMIT correctly after proper ORDER BY

## OUTPUT RULES

### Direct Answer First
- ALWAYS start with a direct answer to the question

### Field Filtering
- Display ONLY fields that answer the user's question
- NEVER display internal IDs unless specifically requested
- NEVER display irrelevant technical columns

### No Generic Statistics
- DO NOT automatically report: "average", "range", "total", "min", "max"
- Generate statistics ONLY if relevant to the question
- NEVER say "The query returned X results" unless result count matters

### Evidence-Based Only
- EVERY number in your answer MUST come from validated execute_query results
- NEVER estimate or invent values
- NEVER claim causation without evidence
- If data is insufficient: say "The available database data is insufficient to answer this question."

### Empty Result Handling
- If execute_query returns 0 rows → state clearly: "No matching data was found for this query."
- DO NOT generate a chart or insights for an empty result
- DO NOT fabricate data to fill an empty result

### Error Handling
- If SQL fails → correct the query and retry
- If the required table/column does not exist → explain clearly
- NEVER substitute with demo, sample, or imaginary data on error

### Format Semantically
- Currency: ₹2,25,122.08 (Indian Rupees)
- Percentage: 27.8%
- Quantity: 300 units
- NEVER format category IDs as insights

## Response Structure

[DIRECT ANSWER]
One sentence answering the question immediately

[RELEVANT DATA TABLE - if helpful]
Only fields that matter to the answer

[KEY INSIGHT - if meaningful]
Evidence-based insight from the data, derived only from execute_query results

DO NOT include:
- Generic summaries
- Irrelevant columns
- Process descriptions
- Debug information
- Any values not returned by execute_query

Remember: The database query result is the SINGLE SOURCE OF TRUTH. Never answer without it.
"""


# ---------------------------------------------------------------------------
# Provider implementations
# ---------------------------------------------------------------------------

class OpenAIProvider:
    """OpenAI GPT-4 provider using the openai SDK."""

    def __init__(self) -> None:
        settings = get_settings()
        import openai
        self._client = openai.OpenAI(api_key=settings.openai_api_key)
        self._model = settings.openai_model

    def chat(
        self,
        messages: list[dict[str, Any]],
        tools: list[dict[str, Any]] | None = None,
    ) -> LLMResponse:
        kwargs: dict[str, Any] = {
            "model": self._model,
            "messages": messages,
        }
        if tools:
            kwargs["tools"] = tools
            kwargs["tool_choice"] = "auto"

        response = self._client.chat.completions.create(**kwargs)
        choice = response.choices[0]
        msg = choice.message

        tool_calls: list[ToolCall] = []
        if msg.tool_calls:
            for tc in msg.tool_calls:
                try:
                    args = json.loads(tc.function.arguments)
                except (json.JSONDecodeError, TypeError):
                    args = {}
                tool_calls.append(ToolCall(
                    id=tc.id,
                    name=tc.function.name,
                    arguments=args,
                ))

        return LLMResponse(
            content=msg.content,
            tool_calls=tool_calls,
            finish_reason=choice.finish_reason or "",
            model=self._model,
            usage={
                "prompt_tokens": response.usage.prompt_tokens if response.usage else 0,
                "completion_tokens": response.usage.completion_tokens if response.usage else 0,
            },
        )


class GeminiProvider:
    """Google Gemini provider using the google-genai SDK."""

    def __init__(self) -> None:
        settings = get_settings()
        from google import genai
        self._client = genai.Client(api_key=settings.gemini_api_key)
        self._model = settings.gemini_model

    def chat(
        self,
        messages: list[dict[str, Any]],
        tools: list[dict[str, Any]] | None = None,
    ) -> LLMResponse:
        from google.genai import types

        # Convert OpenAI-style messages to Gemini contents
        contents = []
        system_instruction = None

        # Build mapping from tool_call_id to function name
        tool_id_to_name = {}
        for msg in messages:
            if msg.get("role") == "assistant" and msg.get("tool_calls"):
                for tc in msg["tool_calls"]:
                    if isinstance(tc, dict):
                        tc_id = tc.get("id")
                        func = tc.get("function")
                        tc_name = func.get("name") if isinstance(func, dict) else None
                        if tc_id and tc_name:
                            tool_id_to_name[tc_id] = tc_name

        for msg in messages:
            role = msg.get("role", "user")
            content = msg.get("content", "")
            if role == "system":
                system_instruction = content
                continue

            parts = []
            if role == "assistant":
                role = "model"
                if content:
                    parts.append(types.Part.from_text(text=content))
                if msg.get("tool_calls"):
                    for tc in msg["tool_calls"]:
                        tc_id = tc.get("id", "")
                        thought_sig = None
                        if tc_id and "|" in tc_id:
                            parts_split = tc_id.split("|")
                            if len(parts_split) > 1:
                                try:
                                    thought_sig = bytes.fromhex(parts_split[1])
                                except ValueError:
                                    pass

                        parts.append(types.Part(
                            function_call=types.FunctionCall(
                                name=tc["function"]["name"],
                                args=json.loads(tc["function"]["arguments"]) if isinstance(tc["function"]["arguments"], str) else tc["function"]["arguments"]
                            ),
                            thought_signature=thought_sig
                        ))
                if not parts:
                    parts.append(types.Part.from_text(text=""))
            elif role == "tool":
                role = "tool"
                tool_call_id = msg.get("tool_call_id")
                name = tool_id_to_name.get(tool_call_id, "unknown")
                try:
                    res_val = json.loads(content)
                except Exception:
                    res_val = {"output": content}

                parts.append(types.Part.from_function_response(
                    name=name,
                    response=res_val if isinstance(res_val, dict) else {"result": res_val}
                ))
            else:
                parts.append(types.Part.from_text(text=content if content else ""))

            contents.append(types.Content(
                role=role,
                parts=parts
            ))

        # Convert tools to Gemini function declarations
        gemini_tools = None
        if tools:
            function_declarations = []
            for tool in tools:
                func = tool.get("function", {})
                params = func.get("parameters", {})
                # Clean the schema for Gemini compatibility
                clean_params = _clean_schema_for_gemini(params)
                function_declarations.append(types.FunctionDeclaration(
                    name=func.get("name", ""),
                    description=func.get("description", ""),
                    parameters=clean_params,
                ))
            gemini_tools = [types.Tool(function_declarations=function_declarations)]

        config = types.GenerateContentConfig(
            system_instruction=system_instruction,
            tools=gemini_tools,
        )

        response = self._client.models.generate_content(
            model=self._model,
            contents=contents,
            config=config,
        )

        # Parse response
        tool_calls: list[ToolCall] = []
        content_text = ""

        if response.candidates:
            candidate = response.candidates[0]
            for part in candidate.content.parts:
                if part.text:
                    content_text += part.text
                if part.function_call:
                    fc = part.function_call
                    # Extract thought signature if present
                    ts = getattr(part, "thought_signature", None)
                    tc_id = f"call_{fc.name}"
                    if ts:
                        tc_id += f"|{ts.hex()}"

                    tool_calls.append(ToolCall(
                        id=tc_id,
                        name=fc.name,
                        arguments=dict(fc.args) if fc.args else {},
                    ))

        return LLMResponse(
            content=content_text or None,
            tool_calls=tool_calls,
            finish_reason="stop" if not tool_calls else "tool_calls",
            model=self._model,
        )


def _clean_schema_for_gemini(schema: dict) -> dict:
    """Clean JSON schema for Gemini compatibility (removes unsupported keys)."""
    cleaned = {}
    for key, value in schema.items():
        if key in ("additionalProperties",):
            continue
        if isinstance(value, dict):
            cleaned[key] = _clean_schema_for_gemini(value)
        else:
            cleaned[key] = value
    return cleaned


class MockProvider:
    """
    Offline schema-driven mock provider for use when no real AI API is configured.

    ALL SQL is generated dynamically from the actual database schema returned by get_schema.
    There are NO keyword-to-SQL mappings, NO predefined query templates, and NO hardcoded
    table or column names in this class.

    Pipeline:
        1. Detect diagram requests  → generate_flowchart
        2. All other questions      → get_schema (ALWAYS first)
                                    → _generate_schema_driven_sql() from actual schema
                                    → execute_query
                                    → chart + insights (only when rows > 0)
                                    → final answer from real data
    """

    def _generate_schema_driven_sql(self, user_query: str, schema_data: dict) -> str:
        """
        Generate a SQL query purely from the schema structure.

        No keyword matching. No predefined templates. No hardcoded table/column names.
        Reads the actual table metadata (column names, types, row counts) returned by
        get_schema to produce an analytically meaningful, immediately executable query.

        Strategy:
          - Prefer tables with the most rows (likely the fact table)
          - Numeric columns  = potential metrics
          - Text columns     = potential dimensions
          - Date columns     = potential time axis
          - numeric + text   -> GROUP BY aggregate query
          - date  + numeric  -> time-series aggregate
          - numeric only     -> descriptive totals
          - text only        -> sample rows
        """
        if not isinstance(schema_data, dict) or not schema_data:
            return "SELECT name FROM sqlite_master WHERE type='table'"

        NUMERIC_TYPES = {"INTEGER", "REAL", "NUMERIC", "FLOAT", "DOUBLE", "DECIMAL", "INT", "BIGINT"}
        TEXT_TYPES = {"TEXT", "VARCHAR", "CHAR", "STRING", "NVARCHAR", "CLOB"}
        DATE_TYPES = {"DATE", "DATETIME", "TIMESTAMP"}

        def _row_count(tbl_info: dict) -> int:
            return tbl_info.get("row_count", 0) if isinstance(tbl_info, dict) else 0

        # Sort tables by descending row count so fact tables surface first
        scored_tables = sorted(
            schema_data.items(), key=lambda kv: _row_count(kv[1]), reverse=True
        )

        for table_name, table_info in scored_tables:
            if not isinstance(table_info, dict):
                continue
            cols = table_info.get("columns", [])
            if not cols:
                continue

            numeric_cols, text_cols, date_cols = [], [], []
            for col in cols:
                col_name = col.get("name", "")
                col_type = col.get("type", "").upper().split("(")[0].strip()
                if not col_name:
                    continue
                if col_type in NUMERIC_TYPES:
                    numeric_cols.append(col_name)
                elif col_type in DATE_TYPES:
                    date_cols.append(col_name)
                else:
                    text_cols.append(col_name)

            q = lambda c: f'"{c}"'

            if text_cols and numeric_cols:
                # Aggregated GROUP BY: dimension x metric
                dim, metric = text_cols[0], numeric_cols[0]
                return (
                    f'SELECT {q(dim)}, SUM({q(metric)}) AS total_{metric} '
                    f'FROM {q(table_name)} '
                    f'GROUP BY {q(dim)} '
                    f'ORDER BY total_{metric} DESC '
                    f'LIMIT 10'
                )

            if date_cols and numeric_cols:
                # Time-series: date x metric
                date_col, metric = date_cols[0], numeric_cols[0]
                return (
                    f'SELECT {q(date_col)}, SUM({q(metric)}) AS total_{metric} '
                    f'FROM {q(table_name)} '
                    f'GROUP BY {q(date_col)} '
                    f'ORDER BY {q(date_col)}'
                )

            if numeric_cols:
                # Descriptive totals across available numeric columns
                col_exprs = ", ".join(
                    [f'SUM({q(c)}) AS total_{c}' for c in numeric_cols[:3]]
                )
                return f'SELECT {col_exprs} FROM {q(table_name)}'

            # Sample rows (text-only or unknown types)
            selected = [q(c) for c in (text_cols + date_cols + numeric_cols)[:6]]
            return f'SELECT {chr(44).join(selected)} FROM {q(table_name)} LIMIT 10'

        return "SELECT name FROM sqlite_master WHERE type='table'"

    def chat(
        self,
        messages: list[dict[str, Any]],
        tools: list[dict[str, Any]] | None = None,
    ) -> LLMResponse:
        # 1. Identify the latest user message
        user_query = ""
        for msg in reversed(messages):
            if msg.get("role") == "user":
                user_query = msg.get("content", "")
                break

        user_query_lower = user_query.lower()

        # Normalise multilingual diagram/data query terms to English
        if any(kw in user_query_lower for kw in ["शीर्ष", "शिखर", "उत्पाद", "राजस्व",
                                                    "வருவாய்", "தயாரிப்புகள்", "தயாரிப்பு", "விற்பனை"]):
            user_query_lower = "explore the database data"
        elif any(kw in user_query_lower for kw in ["ईआर", "आरेख", "ஈஆர்", "வரைபடம்", "இஆர்"]):
            user_query_lower = "show me the er diagram of the database"
        elif any(kw in user_query_lower for kw in ["फ्लोचार्ट", "कार्यप्रवाह", "பணிப்பாய்வு", "ஃப்ளோசார்ட்"]):
            user_query_lower = "show me the datamind ai agent workflow diagram"

        # 2. Collect tool results already present in conversation history
        tool_results: dict = {}
        for msg in messages:
            if msg.get("role") == "tool":
                content_str = msg.get("content", "")
                try:
                    res_dict = json.loads(content_str)
                    if isinstance(res_dict, dict):
                        meta = res_dict.get("metadata")
                        tool_name = meta.get("tool_name") if isinstance(meta, dict) else None
                        if tool_name:
                            tool_results[tool_name] = res_dict
                except Exception:
                    pass

        # 3. Diagram requests
        is_er = any(kw in user_query_lower for kw in ["er diagram", "entity", "relationship"])
        is_workflow = any(kw in user_query_lower for kw in [
            "agent workflow", "flowchart", "agent flowchart", "workflow diagram", "flow", "diagram"
        ])

        if is_er:
            if "generate_flowchart" not in tool_results:
                return LLMResponse(
                    tool_calls=[ToolCall(id="mock_er", name="generate_flowchart",
                                         arguments={"diagram_type": "er"})],
                    finish_reason="tool_calls",
                    model="mock",
                )
            return LLMResponse(
                content="Here is the Entity-Relationship (ER) diagram of the database, showing all tables and their relationships.",
                finish_reason="stop",
                model="mock",
            )

        if is_workflow:
            if "generate_flowchart" not in tool_results:
                return LLMResponse(
                    tool_calls=[ToolCall(id="mock_flow", name="generate_flowchart",
                                         arguments={"diagram_type": "flowchart",
                                                    "description": user_query})],
                    finish_reason="tool_calls",
                    model="mock",
                )
            return LLMResponse(
                content="Here is the process flowchart illustrating the agentic tool-calling loop of DataMind AI.",
                finish_reason="stop",
                model="mock",
            )

        # 4. Conversational greetings / meta questions
        if any(kw in user_query_lower for kw in ["hello", "hi", "hey"]):
            return LLMResponse(
                content=(
                    "Hello! I am DataMind AI. I inspect your database schema and generate SQL dynamically "
                    "from your question. Ask me anything about your data."
                ),
                finish_reason="stop",
                model="mock",
            )
        if any(kw in user_query_lower for kw in ["who are you", "what is this", "what can you do"]):
            return LLMResponse(
                content=(
                    "I am **DataMind AI**, an agentic database assistant. I inspect your database schema, "
                    "generate SQL dynamically from your question, execute it, and explain the results. "
                    "I never use predefined queries — every SQL is generated fresh from your schema and question."
                ),
                finish_reason="stop",
                model="mock",
            )
        if "help" in user_query_lower:
            return LLMResponse(
                content=(
                    "You can ask any question about your data in plain English. Examples:\n"
                    "- *'Show me the top entries by revenue'*\n"
                    "- *'What is the distribution of records by category?'*\n"
                    "- *'Show the ER diagram of the database'*\n\n"
                    "I will inspect the schema, generate SQL, execute it, and explain the results."
                ),
                finish_reason="stop",
                model="mock",
            )

        # 5. Database query pipeline ─────────────────────────────────────────────────
        #
        # PIPELINE: get_schema → _generate_schema_driven_sql() → execute_query
        #           → chart + insights (only rows > 0) → final answer from real data
        #
        # There are NO keyword→SQL mappings here. SQL is derived entirely from the
        # actual schema structure returned by get_schema.

        # Step A: Retrieve schema from the ACTIVE database — always first
        if "get_schema" not in tool_results:
            return LLMResponse(
                tool_calls=[ToolCall(id="mock_schema", name="get_schema", arguments={})],
                finish_reason="tool_calls",
                model="mock",
            )

        # Step B: Generate SQL from actual schema (no keywords, no templates)
        if "execute_query" not in tool_results:
            schema_result = tool_results.get("get_schema", {})
            schema_data = schema_result.get("data") or {}
            sql = self._generate_schema_driven_sql(user_query, schema_data)
            return LLMResponse(
                tool_calls=[ToolCall(id="mock_query", name="execute_query",
                                     arguments={"sql": sql})],
                finish_reason="tool_calls",
                model="mock",
            )

        # Step C: Chart + insights — ONLY when real rows exist
        query_result = tool_results["execute_query"]
        data_payload = query_result.get("data") or {}
        columns = data_payload.get("columns") or []
        rows = data_payload.get("rows") or []
        query_succeeded = query_result.get("success", False)
        has_real_data = query_succeeded and len(rows) > 0

        if has_real_data and (
            "generate_chart" not in tool_results or "explain_data" not in tool_results
        ):
            tool_calls = []
            if "generate_chart" not in tool_results:
                tool_calls.append(ToolCall(
                    id="mock_chart", name="generate_chart",
                    arguments={"columns": columns, "rows": rows, "query_intent": user_query},
                ))
            if "explain_data" not in tool_results:
                tool_calls.append(ToolCall(
                    id="mock_explain", name="explain_data",
                    arguments={"columns": columns, "rows": rows, "query_intent": user_query},
                ))
            return LLMResponse(tool_calls=tool_calls, finish_reason="tool_calls", model="mock")

        # Step D: Final answer
        if not has_real_data:
            return LLMResponse(
                content=(
                    "No matching data was found in the active database. "
                    "The schema was inspected, SQL was generated and executed, but returned 0 rows."
                ),
                finish_reason="stop",
                model="mock",
            )

        explain_res = tool_results.get("explain_data", {})
        explain_payload = explain_res.get("data") or {}
        explanation = (
            explain_payload.get("explanation", "")
            if isinstance(explain_payload, dict) else ""
        )
        return LLMResponse(
            content=(
                f"Based on the actual database query results for your question: **{user_query}**\n\n"
                f"{explanation}"
            ).strip(),
            finish_reason="stop",
            model="mock",
        )


class GroqProvider:
    """Groq Llama 3.1 provider using the openai SDK client compatible mode."""

    def __init__(self) -> None:
        settings = get_settings()
        import openai
        self._client = openai.OpenAI(
            api_key=settings.groq_api_key,
            base_url="https://api.groq.com/openai/v1"
        )
        self._model = settings.groq_model

    def chat(
        self,
        messages: list[dict[str, Any]],
        tools: list[dict[str, Any]] | None = None,
    ) -> LLMResponse:
        kwargs: dict[str, Any] = {
            "model": self._model,
            "messages": messages,
        }
        if tools:
            kwargs["tools"] = tools
            kwargs["tool_choice"] = "auto"

        response = self._client.chat.completions.create(**kwargs)
        choice = response.choices[0]
        msg = choice.message

        tool_calls: list[ToolCall] = []
        if msg.tool_calls:
            for tc in msg.tool_calls:
                try:
                    args = json.loads(tc.function.arguments)
                except (json.JSONDecodeError, TypeError):
                    args = {}
                tool_calls.append(ToolCall(
                    id=tc.id,
                    name=tc.function.name,
                    arguments=args,
                ))

        return LLMResponse(
            content=msg.content,
            tool_calls=tool_calls,
            finish_reason=choice.finish_reason or "",
            model=self._model,
            usage={
                "prompt_tokens": response.usage.prompt_tokens if response.usage else 0,
                "completion_tokens": response.usage.completion_tokens if response.usage else 0,
            },
        )


# ---------------------------------------------------------------------------
# Factory
# ---------------------------------------------------------------------------

def create_llm_service(provider: str | None = None) -> OpenAIProvider | GeminiProvider | GroqProvider | MockProvider:
    """Create an LLM provider instance based on configuration.

    Args:
        provider: Override the configured provider ('openai', 'gemini', 'groq', 'mock').

    Returns:
        An LLM provider instance.
    """
    settings = get_settings()
    provider_name = (provider or settings.llm_provider).lower()

    if provider_name == "openai":
        if not settings.openai_api_key:
            print("[Warning] No OpenAI API key found. Falling back to mock provider.")
            return MockProvider()
        return OpenAIProvider()
    elif provider_name == "gemini":
        if not settings.gemini_api_key:
            print("[Warning] No Gemini API key found. Falling back to mock provider.")
            return MockProvider()
        return GeminiProvider()
    elif provider_name == "groq":
        if not settings.groq_api_key:
            print("[Warning] No Groq API key found. Falling back to mock provider.")
            return MockProvider()
        return GroqProvider()
    elif provider_name == "mock":
        return MockProvider()
    else:
        print(f"[Warning] Unknown provider '{provider_name}'. Using mock provider.")
        return MockProvider()
