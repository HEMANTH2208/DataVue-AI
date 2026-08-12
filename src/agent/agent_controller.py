"""
LLMSQL Agent Controller

Orchestrates the agentic tool-calling loop:
    1. Receives user prompt
    2. Sends to LLM with registered tool specs
    3. Processes tool calls returned by LLM
    4. Feeds tool results back to LLM
    5. Repeats until LLM produces a final text response
    6. Yields SSE events at each lifecycle stage

Supports progressive event streaming for real-time UI updates.
"""

from __future__ import annotations

import json
from typing import Any, AsyncGenerator

from src.tools.base import Tool, ToolResult
from src.services.llm_service import (
    SYSTEM_PROMPT,
    LLMResponse,
    create_llm_service,
)
from src.agent.conversation import ConversationManager, ConversationSession
from src.database.db_manager import DatabaseManager


# Maximum tool-calling iterations to prevent infinite loops
MAX_TOOL_ITERATIONS = 10


class AgentController:
    """LLMSQL Agent orchestrator managing the tool-calling loop."""

    def __init__(
        self,
        db_manager: DatabaseManager,
        tools: list[Tool],
        llm_provider: str | None = None,
    ) -> None:
        self._db = db_manager
        self._tools: dict[str, Tool] = {t.name: t for t in tools}
        self._llm = create_llm_service(llm_provider)
        self._conversation_manager = ConversationManager()

    @property
    def conversation_manager(self) -> ConversationManager:
        return self._conversation_manager

    def _get_tool_specs(self) -> list[dict[str, Any]]:
        """Return function-calling specs for all registered tools."""
        return [tool.get_tool_spec() for tool in self._tools.values()]

    def _execute_tool(self, tool_name: str, arguments: dict[str, Any]) -> ToolResult:
        """Execute a named tool with the given arguments."""
        tool = self._tools.get(tool_name)
        if not tool:
            return ToolResult(
                success=False,
                error=f"Unknown tool: {tool_name}. Available: {list(self._tools.keys())}",
            )
        return tool.execute(**arguments)

    def set_llm_provider(self, provider: str) -> None:
        """Dynamically set or override the active LLM provider."""
        from src.services.llm_service import create_llm_service
        self._llm = create_llm_service(provider)

    def _detect_language(self, text: str) -> str:
        """Check for Tamil or Hindi character blocks, default to English."""
        # Tamil Unicode Block: 0B80 - 0BFF
        if any(ord(char) >= 0x0B80 and ord(char) <= 0x0BFF for char in text):
            return "ta"
        # Devanagari (Hindi) Unicode Block: 0900 - 097F
        if any(ord(char) >= 0x0900 and ord(char) <= 0x097F for char in text):
            return "hi"
        return "en"

    def _translate_via_mymemory(self, text: str, source_lang: str) -> str:
        """Call MyMemory Translation API to translate text to English."""
        import urllib.parse
        import urllib.request
        import json

        url = f"https://api.mymemory.translated.net/get?q={urllib.parse.quote(text)}&langpair={source_lang}|en"
        try:
            req = urllib.request.Request(url, headers={"User-Agent": "Mozilla/5.0"})
            with urllib.request.urlopen(req, timeout=5) as response:
                res_data = json.loads(response.read().decode())
                translated = res_data.get("responseData", {}).get("translatedText", "")
                if translated:
                    return translated
        except Exception as e:
            print(f"[Translation API Error] MyMemory failed: {e}")
        return text

    def _is_english(self, text: str) -> bool:
        """Heuristic: is this query likely English?"""
        return self._detect_language(text) == "en"

    def _translate_to_english(self, text: str) -> str:
        """Translate Tamil or Hindi text to English using a separate translation API."""
        lang = self._detect_language(text)
        if lang != "en":
            return self._translate_via_mymemory(text, lang)
        return text

    # ------------------------------------------------------------------
    # Synchronous query (for simple /api/query endpoint)
    # ------------------------------------------------------------------

    def query(self, user_message: str, session_id: str | None = None) -> dict[str, Any]:
        """Process a user query through the full agentic tool loop.

        Returns a complete response payload with:
            - answer: Final LLM text response
            - sql: Generated SQL (if any)
            - chart: Plotly chart spec (if any)
            - diagram: Mermaid markup (if any)
            - insights: Statistical insights (if any)
            - tool_trace: List of tools invoked with timing
            - session_id: Conversation session identifier
        """
        session = self._conversation_manager.get_or_create_session(session_id)

        # Check if the query is in non-English (Tamil/Hindi) and translate it
        if not self._is_english(user_message):
            try:
                translated = self._translate_to_english(user_message)
                print(f"[Translation] Translated '{user_message}' to '{translated}'")
                user_message = translated
            except Exception as exc:
                print(f"[Translation Error] Failed to translate: {exc}")

        # Build context-enriched system prompt with active database context
        system_prompt = SYSTEM_PROMPT
        context_summary = session.get_context_summary()
        if context_summary:
            system_prompt += f"\n\n## Conversation Context\n{context_summary}"

        # Inject active database identity so the LLM never queries the wrong DB
        try:
            from src.database.resolver import get_active_database_path, active_session_id, _session_databases
            active_path = get_active_database_path(session_id)
            import os
            db_source = "default"
            sid = session_id or active_session_id.get()
            if sid and sid in _session_databases:
                db_source = _session_databases[sid].source_type
            system_prompt += (
                f"\n\n## Active Database (Current Session)\n"
                f"- Source: {db_source}\n"
                f"- Path: {os.path.basename(active_path)}\n"
                f"\nIMPORTANT: Query ONLY tables that exist in the schema returned by get_schema above."
                f" NEVER use table or column names not present in that schema."
            )
        except Exception as _db_ctx_err:
            print(f"[DB Context Warning] Could not inject DB context: {_db_ctx_err}")

        # Add user message to session
        session.add_message("user", user_message)

        # Build message list for LLM
        messages: list[dict[str, Any]] = [
            {"role": "system", "content": system_prompt},
        ] + session.messages

        tool_specs = self._get_tool_specs()

        # Response accumulator
        response_payload: dict[str, Any] = {
            "answer": "",
            "sql": None,
            "query_result": None,
            "chart": None,
            "diagram": None,
            "insights": None,
            "tool_trace": [],
            "session_id": session.session_id,
        }

        # --- Agentic tool loop ---
        for iteration in range(MAX_TOOL_ITERATIONS):
            try:
                llm_response: LLMResponse = self._llm.chat(messages, tool_specs)
            except Exception as exc:
                import traceback
                print(f"[Fallback] LLM provider error: {exc}. Stack trace:\n{traceback.format_exc()}")
                from src.services.llm_service import MockProvider
                self._llm = MockProvider()
                llm_response = self._llm.chat(messages, tool_specs)

            if not llm_response.tool_calls:
                # LLM produced a final text response
                response_payload["answer"] = llm_response.content or ""
                session.add_message("assistant", llm_response.content or "")
                break

            # Process each tool call
            tool_calls_raw = []
            for tc in llm_response.tool_calls:
                tool_calls_raw.append({
                    "id": tc.id,
                    "type": "function",
                    "function": {
                        "name": tc.name,
                        "arguments": json.dumps(tc.arguments),
                    },
                })

            session.add_assistant_tool_calls(tool_calls_raw)
            messages.append({
                "role": "assistant",
                "content": None,
                "tool_calls": tool_calls_raw,
            })

            for tc in llm_response.tool_calls:
                result = self._execute_tool(tc.name, tc.arguments)

                # Record in trace
                trace_entry = {
                    "tool": tc.name,
                    "arguments": tc.arguments,
                    "success": result.success,
                    "execution_time_ms": result.metadata.get("execution_time_ms"),
                }
                response_payload["tool_trace"].append(trace_entry)
                session.record_tool_execution(tc.name, result.to_dict())

                # Extract structured data for response payload
                if tc.name == "execute_query" and result.success:
                    response_payload["sql"] = result.metadata.get("executed_sql")
                    response_payload["query_result"] = result.data
                    session.last_sql = result.metadata.get("executed_sql")
                    session.last_query_result = result.data
                elif tc.name == "generate_chart" and result.success:
                    response_payload["chart"] = result.data
                elif tc.name == "generate_flowchart" and result.success:
                    response_payload["diagram"] = result.data
                elif tc.name == "explain_data" and result.success:
                    response_payload["insights"] = result.data

                # Feed result back to LLM
                result_str = json.dumps(result.to_dict(), default=str)
                session.add_tool_result(tc.name, tc.id, result_str)
                messages.append({
                    "role": "tool",
                    "tool_call_id": tc.id,
                    "content": result_str,
                })

        # ── GROUNDING GUARD ──
        # Strip chart and insights from the response if no real query result exists.
        # This prevents hallucinated charts from reaching the frontend.
        query_result = response_payload.get("query_result")
        has_real_data = (
            query_result is not None
            and isinstance(query_result, dict)
            and query_result.get("row_count", 0) > 0
        )
        if not has_real_data:
            # Suppress any charts or insights generated without real data
            if response_payload.get("chart") is not None:
                print("[Grounding Guard] Suppressed chart: no verified query result.")
                response_payload["chart"] = None
            if response_payload.get("insights") is not None:
                print("[Grounding Guard] Suppressed insights: no verified query result.")
                response_payload["insights"] = None
            # If the LLM never called execute_query, override the answer
            if query_result is None and not response_payload["answer"].strip():
                response_payload["answer"] = (
                    "The available database data is insufficient to answer this question."
                )

        response_payload["tool_trace"] = response_payload["tool_trace"]
        return response_payload

    # ------------------------------------------------------------------
    # Async SSE streaming query
    # ------------------------------------------------------------------

    async def query_stream(
        self, user_message: str, session_id: str | None = None
    ) -> AsyncGenerator[dict[str, Any], None]:
        """Process a user query with SSE event streaming.

        Yields dict events with 'type' and 'data' keys:
            - type: "status" | "tool_start" | "tool_result" | "sql" | "chart" |
                    "diagram" | "insights" | "answer" | "complete"
        """
        session = self._conversation_manager.get_or_create_session(session_id)

        # Check if the query is in non-English (Tamil/Hindi) and translate it
        if not self._is_english(user_message):
            yield {
                "type": "status",
                "data": {
                    "message": "Translating query to English...",
                    "session_id": session.session_id,
                },
            }
            try:
                translated = self._translate_to_english(user_message)
                print(f"[Translation] Translated '{user_message}' to '{translated}'")
                user_message = translated
            except Exception as exc:
                print(f"[Translation Error] Failed to translate: {exc}")

        yield {"type": "status", "data": {"message": "Thinking...", "session_id": session.session_id}}

        system_prompt = SYSTEM_PROMPT
        context_summary = session.get_context_summary()
        if context_summary:
            system_prompt += f"\n\n## Conversation Context\n{context_summary}"

        # Inject active database identity into the streaming system prompt
        try:
            from src.database.resolver import get_active_database_path, active_session_id, _session_databases
            active_path = get_active_database_path(session_id)
            import os
            db_source = "default"
            sid = session_id or active_session_id.get()
            if sid and sid in _session_databases:
                db_source = _session_databases[sid].source_type
            system_prompt += (
                f"\n\n## Active Database (Current Session)\n"
                f"- Source: {db_source}\n"
                f"- Path: {os.path.basename(active_path)}\n"
                f"\nIMPORTANT: Query ONLY tables that exist in the schema returned by get_schema above."
                f" NEVER use table or column names not present in that schema."
            )
        except Exception as _db_ctx_err:
            print(f"[DB Context Warning] Could not inject DB context: {_db_ctx_err}")

        session.add_message("user", user_message)
        messages: list[dict[str, Any]] = [
            {"role": "system", "content": system_prompt},
        ] + session.messages

        tool_specs = self._get_tool_specs()
        tool_trace: list[dict[str, Any]] = []
        last_query_data = None

        for iteration in range(MAX_TOOL_ITERATIONS):
            try:
                llm_response: LLMResponse = self._llm.chat(messages, tool_specs)
            except Exception as exc:
                print(f"[Fallback] LLM provider error: {exc}. Falling back to MockProvider.")
                yield {
                    "type": "status",
                    "data": {
                        "message": "Quota limit reached. Falling back to offline mock mode...",
                        "session_id": session.session_id,
                    },
                }
                from src.services.llm_service import MockProvider
                self._llm = MockProvider()
                llm_response = self._llm.chat(messages, tool_specs)

            if not llm_response.tool_calls:
                # ── STRICT GROUNDING: Do NOT autonomously inject charts or insights ──
                # Charts and insights are ONLY emitted when the LLM explicitly calls those tools
                # through the tool-calling loop above. If the LLM skipped them, that is a
                # deliberate or necessary choice — do not override it with autonomous injection.
                answer = llm_response.content or ""
                
                # If LLM produced an answer without ever calling execute_query,
                # replace it with the insufficiency message to prevent hallucination.
                query_was_executed = any(t["tool"] == "execute_query" for t in tool_trace)
                if not query_was_executed and answer.strip():
                    # Only override if this looks like a database question
                    db_keywords = ["top", "best", "revenue", "sales", "product", "order",
                                   "category", "customer", "rating", "payment", "count",
                                   "average", "total", "distribution", "trend"]
                    if any(kw in user_message.lower() for kw in db_keywords):
                        print("[Grounding Guard] LLM answered without execute_query — overriding.")
                        answer = "The available database data is insufficient to answer this question."

                session.add_message("assistant", answer)
                
                # Stream the answer word by word
                words = answer.split(" ")
                current_content = ""
                for i, word in enumerate(words):
                    if i > 0:
                        current_content += " "
                    current_content += word
                    yield {"type": "answer_chunk", "data": {"content": current_content}}
                    import asyncio
                    await asyncio.sleep(0.02)
                break

            tool_calls_raw = []
            for tc in llm_response.tool_calls:
                tool_calls_raw.append({
                    "id": tc.id,
                    "type": "function",
                    "function": {
                        "name": tc.name,
                        "arguments": json.dumps(tc.arguments),
                    },
                })

            session.add_assistant_tool_calls(tool_calls_raw)
            messages.append({
                "role": "assistant",
                "content": None,
                "tool_calls": tool_calls_raw,
            })

            for tc in llm_response.tool_calls:
                yield {
                    "type": "tool_start",
                    "data": {"tool": tc.name, "arguments": tc.arguments},
                }

                result = self._execute_tool(tc.name, tc.arguments)

                trace_entry = {
                    "tool": tc.name,
                    "arguments": tc.arguments,
                    "success": result.success,
                    "execution_time_ms": result.metadata.get("execution_time_ms"),
                }
                tool_trace.append(trace_entry)
                session.record_tool_execution(tc.name, result.to_dict())

                yield {
                    "type": "tool_result",
                    "data": trace_entry,
                }

                # Stream structured data as specific event types
                if tc.name == "execute_query" and result.success:
                    session.last_sql = result.metadata.get("executed_sql")
                    session.last_query_result = result.data
                    last_query_data = result.data
                    yield {
                        "type": "sql",
                        "data": {"sql": result.metadata.get("executed_sql"), "result": result.data},
                    }
                elif tc.name == "generate_chart" and result.success:
                    yield {"type": "chart", "data": result.data}
                elif tc.name == "generate_flowchart" and result.success:
                    yield {"type": "diagram", "data": result.data}
                elif tc.name == "explain_data" and result.success:
                    yield {"type": "insights", "data": result.data}

                result_str = json.dumps(result.to_dict(), default=str)
                session.add_tool_result(tc.name, tc.id, result_str)
                messages.append({
                    "role": "tool",
                    "tool_call_id": tc.id,
                    "content": result_str,
                })

        yield {
            "type": "complete",
            "data": {"tool_trace": tool_trace, "session_id": session.session_id},
        }
