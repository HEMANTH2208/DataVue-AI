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

SYSTEM_PROMPT = """You are DataMind AI, an AI database assistant that helps users query and visualize data using natural language.

You have access to the following tools:

1. **get_schema** - Inspect database tables, columns, types, keys, and sample data. Always call this first if you don't know the database structure.
2. **execute_query** - Execute a SQL SELECT query. You write the SQL based on the schema context. Only SELECT queries are allowed.
3. **generate_chart** - Generate an interactive chart from query results. Pass the columns, rows, and original question.
4. **generate_flowchart** - Generate Mermaid.js diagrams. Use diagram_type='er' for ER diagrams, 'flowchart' for process flows.
5. **explain_data** - Generate a plain-English summary of query results with statistics and key takeaways.

## Guidelines:
- Always inspect the schema first before writing SQL queries.
- Write precise, efficient SQL that matches the user's intent.
- After getting query results, generate BOTH a visualization AND an explanation.
- For questions about database structure, generate an ER diagram.
- For questions about processes or workflows, generate a flowchart.
- Provide clear, executive-level explanations — don't just dump numbers.
- Reference specific values, percentages, and comparisons in your explanations.
- When following up on previous queries, use context from the conversation history.
- **CRITICAL**: All prices, sales, and revenue values MUST be formatted in Indian Rupees (₹) instead of Dollars ($). For example, write '₹50,000' instead of '$50,000'. Never use the dollar symbol ($) in tables, explanations, or labels.
"""


# ---------------------------------------------------------------------------
# Provider implementations
# ---------------------------------------------------------------------------

class OpenAIProvider:
    """OpenAI GPT-4o provider using the openai SDK."""

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
                    tc_id = tc.get("id")
                    tc_name = tc.get("function", {}).get("name")
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
    """Offline mock provider for testing without API access."""

    def chat(
        self,
        messages: list[dict[str, Any]],
        tools: list[dict[str, Any]] | None = None,
    ) -> LLMResponse:
        # 1. Find the latest user query in conversation history
        user_query = ""
        for msg in reversed(messages):
            if msg.get("role") == "user":
                user_query = msg.get("content", "")
                break
        
        user_query_lower = user_query.lower()

        # Map Hindi/Tamil query terms for MockProvider robustness
        if any(kw in user_query_lower for kw in ["शीर्ष", "शिखर", "उत्पाद", "राजस्व", "வருவாய்", "தயாரிப்புகள்", "தயாரிப்பு", "விற்பனை"]):
            user_query_lower = "what are the top 5 best-selling products by revenue?"
        elif any(kw in user_query_lower for kw in ["ईआर", "आरेख", "ஈஆர்", "வரைபடம்", "இஆர்"]):
            user_query_lower = "show me the er diagram of the database"
        elif any(kw in user_query_lower for kw in ["फ्लोचार्ट", "कार्यप्रवाह", "பணிப்பாய்வு", "ஃப்ளோசார்ட்"]):
            user_query_lower = "show me the datamind ai agent workflow diagram"

        # 2. Check which tools have already been executed
        tool_results = {}
        for msg in messages:
            if msg.get("role") == "tool":
                content_str = msg.get("content", "")
                try:
                    res_dict = json.loads(content_str)
                    tool_name = res_dict.get("metadata", {}).get("tool_name")
                    if tool_name:
                        tool_results[tool_name] = res_dict
                except Exception:
                    pass

        # 3. Detect diagram-specific queries (ER diagram or agent workflow)
        is_er = any(kw in user_query_lower for kw in ["er diagram", "entity", "relationship"])
        is_workflow = any(kw in user_query_lower for kw in ["agent workflow", "flowchart", "agent flowchart", "workflow diagram", "flow", "diagram"])

        if is_er:
            if "generate_flowchart" not in tool_results:
                return LLMResponse(
                    tool_calls=[ToolCall(id="mock_call_er", name="generate_flowchart", arguments={"diagram_type": "er"})],
                    finish_reason="tool_calls",
                    model="mock",
                )
            else:
                return LLMResponse(
                    content="Here is the Entity-Relationship (ER) diagram of the database. It displays the tables: categories, products, customers, orders, order_items, and reviews, highlighting primary keys (🔑) and foreign key relationships.",
                    finish_reason="stop",
                    model="mock",
                )

        if is_workflow:
            if "generate_flowchart" not in tool_results:
                return LLMResponse(
                    tool_calls=[ToolCall(
                        id="mock_call_flow",
                        name="generate_flowchart",
                        arguments={"diagram_type": "flowchart", "description": user_query}
                    )],
                    finish_reason="tool_calls",
                    model="mock",
                )
            else:
                return LLMResponse(
                    content="Here is the process flowchart illustrating the agentic tool-calling loop of DataMind AI.",
                    finish_reason="stop",
                    model="mock",
                )

        # 4. Detect database data-related queries
        is_db_query = any(kw in user_query_lower for kw in [
            "top", "best", "selling", "revenue", "sales", "product", "trend", "month", "order", "category", "rating",
            "payment", "method", "customer", "price", "stock", "count", "average", "avg", "distribution",
            "review", "reviews", "item", "items", "table"
        ])

        if is_db_query:
            # Step A: Discover Schema
            if "get_schema" not in tool_results:
                return LLMResponse(
                    tool_calls=[ToolCall(id="mock_call_schema", name="get_schema", arguments={})],
                    finish_reason="tool_calls",
                    model="mock",
                )

            # Step B: Formulate and Execute SQL Query
            if "execute_query" not in tool_results:
                sql = ""
                if "best-selling" in user_query_lower or ("top" in user_query_lower and "revenue" in user_query_lower):
                    sql = (
                        "SELECT p.name, SUM(oi.quantity * oi.unit_price) AS revenue "
                        "FROM order_items oi JOIN products p ON oi.product_id = p.product_id "
                        "GROUP BY p.product_id ORDER BY revenue DESC LIMIT 5"
                    )
                elif "monthly revenue" in user_query_lower or ("revenue" in user_query_lower and "trend" in user_query_lower):
                    sql = (
                        "SELECT strftime('%Y-%m', order_date) AS month, SUM(total_amount) AS revenue "
                        "FROM orders WHERE order_date LIKE '2025%' GROUP BY month ORDER BY month"
                    )
                elif "average order value" in user_query_lower or ("order value" in user_query_lower and "category" in user_query_lower):
                    sql = (
                        "SELECT c.name AS category, AVG(o.total_amount) AS avg_order_value "
                        "FROM orders o JOIN order_items oi ON o.order_id = oi.order_id "
                        "JOIN products p ON oi.product_id = p.product_id "
                        "JOIN categories c ON p.category_id = c.category_id "
                        "GROUP BY c.category_id ORDER BY avg_order_value DESC"
                    )
                elif "placed each month" in user_query_lower or "orders per month" in user_query_lower or ("orders" in user_query_lower and "month" in user_query_lower):
                    sql = (
                        "SELECT strftime('%Y-%m', order_date) AS month, COUNT(order_id) AS order_count "
                        "FROM orders WHERE order_date LIKE '2025%' GROUP BY month ORDER BY month"
                    )
                elif "payment method" in user_query_lower or "payment" in user_query_lower:
                    sql = (
                        "SELECT payment_method, COUNT(order_id) AS order_count "
                        "FROM orders GROUP BY payment_method ORDER BY order_count DESC"
                    )
                elif "rating" in user_query_lower or "reviews" in user_query_lower or "review" in user_query_lower:
                    sql = (
                        "SELECT p.name, ROUND(AVG(r.rating), 2) AS avg_rating "
                        "FROM reviews r JOIN products p ON r.product_id = p.product_id "
                        "GROUP BY p.product_id ORDER BY avg_rating DESC LIMIT 5"
                    )
                else:
                    if "product" in user_query_lower:
                        sql = "SELECT name, price, stock_qty FROM products LIMIT 5"
                    elif "order_item" in user_query_lower or "item" in user_query_lower:
                        sql = "SELECT order_id, product_id, quantity, unit_price FROM order_items LIMIT 5"
                    elif "order" in user_query_lower:
                        sql = "SELECT order_id, order_date, total_amount, status FROM orders LIMIT 5"
                    elif "customer" in user_query_lower:
                        sql = "SELECT first_name, last_name, email, city FROM customers LIMIT 5"
                    elif "category" in user_query_lower or "categories" in user_query_lower:
                        sql = "SELECT name, description FROM categories LIMIT 5"
                    elif "review" in user_query_lower or "reviews" in user_query_lower:
                        sql = "SELECT rating, comment FROM reviews LIMIT 5"
                    else:
                        sql = "SELECT name FROM sqlite_master WHERE type='table'"

                return LLMResponse(
                    tool_calls=[ToolCall(id="mock_call_query", name="execute_query", arguments={"sql": sql})],
                    finish_reason="tool_calls",
                    model="mock",
                )

            # Step C: Run Visualization & Summary Explainer
            query_result = tool_results["execute_query"]
            data_payload = query_result.get("data", {})
            columns = data_payload.get("columns", [])
            rows = data_payload.get("rows", [])

            if "generate_chart" not in tool_results or "explain_data" not in tool_results:
                tool_calls = []
                if "generate_chart" not in tool_results:
                    tool_calls.append(
                        ToolCall(
                            id="mock_call_chart",
                            name="generate_chart",
                            arguments={
                                "columns": columns,
                                "rows": rows,
                                "query_intent": user_query
                            }
                        )
                    )
                if "explain_data" not in tool_results:
                    tool_calls.append(
                        ToolCall(
                            id="mock_call_explain",
                            name="explain_data",
                            arguments={
                                "columns": columns,
                                "rows": rows,
                                "query_intent": user_query
                            }
                        )
                    )
                return LLMResponse(
                    tool_calls=tool_calls,
                    finish_reason="tool_calls",
                    model="mock",
                )

            # Step D: Return Final Answer
            explanation = tool_results["explain_data"].get("data", {}).get("explanation", "")
            return LLMResponse(
                content=f"Here is the database query summary and visualization for your question: **{user_query}**.\n\n{explanation}",
                finish_reason="stop",
                model="mock",
            )

        # 5. General Chatbot Fallback
        if "hello" in user_query_lower or "hi" in user_query_lower:
            reply = "Hello! I am DataMind AI, your database chatbot assistant. How can I help you explore your database today?"
        elif "who are you" in user_query_lower or "what is this" in user_query_lower:
            reply = (
                "I am **DataMind AI**, an agentic database assistant. I can connect to databases, "
                "inspect schemas, execute SQL queries, build interactive charts, and explain the data "
                "using plain English summaries. Ask me queries about tables like Products, Orders, Customers, "
                "or click any suggested queries in the sidebar to try it out!"
            )
        elif "help" in user_query_lower:
            reply = (
                "You can query the database using plain English. For example:\n"
                "- *'What are the top 5 products by revenue?'*\n"
                "- *'Show monthly revenue trend for 2025'*\n"
                "- *'Show the distribution of orders by payment method'*\n"
                "I will query the database, generate a chart, and explain the key findings."
            )
        else:
            reply = (
                f"I'm running in offline chatbot mode. I didn't recognize a specific database query in: "
                f"'{user_query}'. For database queries, please mention keywords like 'revenue', 'products', 'orders', "
                f"or 'categories' to trigger the SQL agent tools."
            )

        return LLMResponse(
            content=reply,
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
