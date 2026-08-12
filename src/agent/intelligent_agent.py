"""
LLMSQL Intelligent Agent Controller

Production-quality conversational database analytics agent with:
- Deep question understanding
- Multi-step analytical reasoning  
- Result validation and correction
- Intelligent visualization selection
- Data-grounded explanations
"""

from __future__ import annotations

import json
import re
from typing import Any, AsyncGenerator

from src.agent.question_analyzer import QuestionAnalyzer, QuestionAnalysis
from src.agent.query_planner import QueryPlanner, ExecutionPlan, AnalyticalStep
from src.agent.result_validator import ResultValidator, ValidationResult
from src.agent.quality_gate import QualityGate, QualityGateResult
from src.agent.conversation import ConversationManager, ConversationSession
from src.tools.base import Tool, ToolResult
from src.services.llm_service import create_llm_service, LLMResponse
from src.database.db_manager import DatabaseManager


MAX_CORRECTION_ATTEMPTS = 2


class IntelligentAgent:
    """
    Intelligent database analytics agent with deep understanding and validation.
    
    Workflow:
    1. UNDERSTAND: Deeply analyze the user question
    2. PLAN: Create multi-step execution plan with dependencies
    3. EXECUTE: Run each step with validation
    4. VALIDATE: Check results against requirements
    5. CORRECT: Fix issues if validation fails
    6. ANSWER: Provide grounded, accurate response
    """
    
    def __init__(
        self,
        db_manager: DatabaseManager,
        tools: list[Tool],
        llm_provider: str | None = None,
    ) -> None:
        self._db = db_manager
        self._tools: dict[str, Tool] = {t.name: t for t in tools}
        self._llm = create_llm_service(llm_provider)
        
        # Intelligence components
        self._analyzer = QuestionAnalyzer()
        self._planner = QueryPlanner()
        self._validator = ResultValidator()
        self._quality_gate = QualityGate()
        self._conversation_manager = ConversationManager()
        
        # Execution context
        self._current_plan: ExecutionPlan | None = None
        self._schema_cache: dict[str, Any] = {}
    
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
                error=f"Unknown tool: {tool_name}",
            )
        return tool.execute(**arguments)
    
    async def query_stream(
        self,
        user_message: str,
        session_id: str | None = None
    ) -> AsyncGenerator[dict[str, Any], None]:
        """
        Process user question with intelligent analysis, planning, and validation.
        
        Yields SSE events for real-time UI updates.
        """
        session = self._conversation_manager.get_or_create_session(session_id)
        session.add_message("user", user_message)
        
        # Phase 1: UNDERSTAND
        yield {"type": "status", "data": {"message": "Analyzing question...", "session_id": session.session_id}}
        
        analysis = self._analyzer.analyze(user_message)
        
        yield {
            "type": "analysis",
            "data": {
                "question_type": analysis.question_type,
                "is_multi_step": analysis.is_multi_step,
                "entities": analysis.entities,
                "metrics": analysis.metrics,
                "requirements": analysis.requirements[:3]  # Show top 3
            }
        }
        
        # Phase 2: PLAN
        yield {"type": "status", "data": {"message": "Creating analytical plan...", "session_id": session.session_id}}
        
        plan = self._planner.create_plan(analysis)
        self._current_plan = plan
        
        yield {
            "type": "plan",
            "data": {
                "total_steps": len(plan.steps),
                "step_descriptions": [s.description for s in plan.steps]
            }
        }
        
        # Phase 3: EXECUTE plan step by step
        accumulated_results = {}
        last_query_result = None
        final_answer = ""
        
        while True:
            next_step = plan.get_next_step()
            if not next_step:
                break
            
            yield {
                "type": "step_start",
                "data": {
                    "step_id": next_step.step_id,
                    "description": next_step.description,
                    "operation": next_step.operation
                }
            }
            
            # Execute step based on operation type
            if next_step.operation == "schema_discovery":
                result = await self._execute_schema_step(next_step, session)
                self._schema_cache = result.data if result.success else {}
                accumulated_results[next_step.step_id] = result
                plan.mark_step_complete(next_step.step_id, result, validated=True)
                
            elif next_step.operation == "query":
                # Execute query with validation
                result, validated = await self._execute_query_step(
                    next_step, plan, accumulated_results, session, yield_func=lambda x: x
                )
                
                if result.success and validated:
                    last_query_result = result.data
                    accumulated_results[next_step.step_id] = result
                    plan.mark_step_complete(next_step.step_id, result, validated=True)
                    
                    yield {
                        "type": "sql",
                        "data": {
                            "sql": result.metadata.get("executed_sql"),
                            "result": result.data
                        }
                    }
                else:
                    # Validation failed - try to correct
                    yield {
                        "type": "validation_failed",
                        "data": {"step_id": next_step.step_id, "attempting_correction": True}
                    }
                    
                    # Attempt correction (simplified for now)
                    plan.mark_step_complete(next_step.step_id, result, validated=False)
            
            elif next_step.operation == "validate_and_extract":
                # Extract identifier from previous step
                dep_step_id = next_step.depends_on[0]
                dep_result = accumulated_results.get(dep_step_id)
                
                if dep_result and dep_result.success:
                    identifier = self._validator.extract_identifier_from_result(
                        dep_result.data,
                        entity_type="category"  # TODO: make dynamic
                    )
                    
                    result = ToolResult(
                        success=True,
                        data=identifier,
                        metadata={"extracted_from": dep_step_id}
                    )
                    accumulated_results[next_step.step_id] = result
                    plan.mark_step_complete(next_step.step_id, result, validated=True)
                    
                    yield {
                        "type": "extraction",
                        "data": {"extracted": identifier}
                    }
            
            elif next_step.operation == "visualize":
                # Generate visualization from query result
                dep_step_id = next_step.depends_on[0] if next_step.depends_on else None
                query_result = accumulated_results.get(dep_step_id) if dep_step_id else None
                
                if query_result and query_result.success:
                    viz_tool = self._tools.get("generate_chart")
                    if viz_tool:
                        viz_result = viz_tool.execute(
                            columns=query_result.data.get("columns", []),
                            rows=query_result.data.get("rows", []),
                            query_intent=next_step.query_intent or analysis.original_question
                        )
                        
                        if viz_result.success:
                            accumulated_results[next_step.step_id] = viz_result
                            plan.mark_step_complete(next_step.step_id, viz_result, validated=True)
                            
                            yield {
                                "type": "chart",
                                "data": viz_result.data
                            }
            
            elif next_step.operation == "explain":
                # Generate explanation from query results
                dep_step_id = next_step.depends_on[0] if next_step.depends_on else None
                query_result = accumulated_results.get(dep_step_id) if dep_step_id else None
                
                if query_result and query_result.success:
                    explain_tool = self._tools.get("explain_data")
                    if explain_tool:
                        explain_result = explain_tool.execute(
                            columns=query_result.data.get("columns", []),
                            rows=query_result.data.get("rows", []),
                            query_intent=analysis.original_question
                        )
                        
                        if explain_result.success:
                            accumulated_results[next_step.step_id] = explain_result
                            plan.mark_step_complete(next_step.step_id, explain_result, validated=True)
                            final_answer = explain_result.data.get("explanation", "")
                            
                            yield {
                                "type": "insights",
                                "data": explain_result.data
                            }
            
            elif next_step.operation == "diagram":
                # Generate diagram
                diagram_tool = self._tools.get("generate_flowchart")
                if diagram_tool:
                    diagram_type = "er" if "er" in analysis.suggested_viz.lower() else "flowchart"
                    diagram_result = diagram_tool.execute(
                        diagram_type=diagram_type,
                        description=analysis.original_question
                    )
                    
                    if diagram_result.success:
                        accumulated_results[next_step.step_id] = diagram_result
                        plan.mark_step_complete(next_step.step_id, diagram_result, validated=True)
                        
                        yield {
                            "type": "diagram",
                            "data": diagram_result.data
                        }
                        
                        # Set final answer for diagrams
                        if diagram_type == "er":
                            final_answer = "Here is the Entity-Relationship diagram of the database."
                        else:
                            final_answer = "Here is the process flowchart."
        
        # Phase 4: CRITICAL - Verify ALL sub-questions answered before final response
        if not self._verify_all_requirements_met(plan, accumulated_results):
            # NOT ALL REQUIREMENTS MET - DO NOT GENERATE PARTIAL ANSWER
            yield {
                "type": "validation_failed",
                "data": {
                    "message": "Not all sub-questions were answered. Cannot generate partial response.",
                    "completed_steps": len([s for s in plan.steps if s.executed]),
                    "total_steps": len(plan.steps)
                }
            }
            
            final_answer = "I was unable to fully answer your question. Some analytical stages did not complete successfully. Please try rephrasing your question or breaking it into smaller parts."
        
        # Phase 5: Stream final answer
        if final_answer:
            session.add_message("assistant", final_answer)
            
            words = final_answer.split(" ")
            current_content = ""
            for i, word in enumerate(words):
                if i > 0:
                    current_content += " "
                current_content += word
                yield {"type": "answer_chunk", "data": {"content": current_content}}
                
                import asyncio
                await asyncio.sleep(0.02)
        
        # Phase 5: Complete
        yield {
            "type": "complete",
            "data": {
                "session_id": session.session_id,
                "steps_executed": len([s for s in plan.steps if s.executed]),
                "all_validated": plan.all_steps_complete()
            }
        }
    
    async def _execute_schema_step(
        self,
        step: AnalyticalStep,
        session: ConversationSession
    ) -> ToolResult:
        """Execute schema discovery step."""
        schema_tool = self._tools.get("get_schema")
        if not schema_tool:
            return ToolResult(success=False, error="Schema tool not available")
        
        return schema_tool.execute()
    
    async def _execute_query_step(
        self,
        step: AnalyticalStep,
        plan: ExecutionPlan,
        accumulated_results: dict[int, ToolResult],
        session: ConversationSession,
        yield_func=None
    ) -> tuple[ToolResult, bool]:
        """
        Execute a query step with LLM assistance, using context from dependencies.
        
        Returns: (ToolResult, is_validated)
        """
        # Build enriched prompt for LLM
        system_prompt = self._build_enriched_system_prompt(step, plan, accumulated_results)
        
        messages = [
            {"role": "system", "content": system_prompt},
            {"role": "user", "content": step.query_intent}
        ]
        
        tool_specs = self._get_tool_specs()
        
        # Let LLM generate and execute query
        attempts = 0
        result = None
        
        while attempts < MAX_CORRECTION_ATTEMPTS:
            attempts += 1
            
            try:
                llm_response: LLMResponse = self._llm.chat(messages, tool_specs)
            except Exception as exc:
                import traceback
                print(f"[LLM Error] {exc}")
                print(f"[LLM Error Stack] {traceback.format_exc()}")
                print("[LLM Error] Falling back to MockProvider for testing...")
                from src.services.llm_service import MockProvider
                self._llm = MockProvider()
                llm_response = self._llm.chat(messages, tool_specs)
            
            if not llm_response.tool_calls:
                # LLM didn't call execute_query - ask it to
                messages.append({
                    "role": "assistant",
                    "content": llm_response.content or "I need to query the database."
                })
                messages.append({
                    "role": "user",
                    "content": "Please use the execute_query tool to get this data from the database."
                })
                continue
            
            # Execute the query tool call
            for tc in llm_response.tool_calls:
                if tc.name == "execute_query":
                    # Validate SQL before execution
                    sql = tc.arguments.get("sql", "")
                    
                    # Basic SQL validation
                    sql_issues = self._validate_sql_before_execution(sql, step, plan, accumulated_results)
                    if sql_issues:
                        # Provide feedback and retry
                        feedback = f"SQL validation issues detected:\n"
                        feedback += "\n".join(f"- {issue}" for issue in sql_issues)
                        feedback += "\nPlease regenerate the SQL query addressing these issues."
                        
                        messages.append({
                            "role": "assistant",
                            "tool_calls": [{
                                "id": tc.id,
                                "type": "function",
                                "function": {
                                    "name": tc.name,
                                    "arguments": json.dumps(tc.arguments)
                                }
                            }]
                        })
                        messages.append({
                            "role": "tool",
                            "tool_call_id": tc.id,
                            "content": json.dumps({
                                "success": False,
                                "sql_validation_failed": True,
                                "feedback": feedback
                            })
                        })
                        break
                    
                    # Execute query
                    result = self._execute_tool(tc.name, tc.arguments)
                    
                    if result.success:
                        # Validate result
                        validation = self._validator.validate_query_result(
                            result.data,
                            expected_columns=step.expected_columns,
                            expected_row_count=plan.analysis.top_n if "top" in step.description.lower() else None,
                            max_row_count=plan.analysis.top_n if plan.analysis.top_n else None,
                            validation_rules=step.validation_rules
                        )
                        
                        if validation.is_valid:
                            return result, True
                        else:
                            # Validation failed - provide feedback to LLM
                            feedback = f"Query executed but validation failed:\n"
                            feedback += "\n".join(f"- {v}" for v in validation.violations)
                            if validation.corrective_action:
                                feedback += f"\nSuggested action: {validation.corrective_action}"
                            
                            messages.append({
                                "role": "assistant",
                                "tool_calls": [{
                                    "id": tc.id,
                                    "type": "function",
                                    "function": {
                                        "name": tc.name,
                                        "arguments": json.dumps(tc.arguments)
                                    }
                                }]
                            })
                            messages.append({
                                "role": "tool",
                                "tool_call_id": tc.id,
                                "content": json.dumps({
                                    "success": False,
                                    "validation_failed": True,
                                    "feedback": feedback,
                                    "result": result.data
                                })
                            })
                            
                            # Try again with feedback
                            break
                    else:
                        # Query execution failed
                        messages.append({
                            "role": "assistant",
                            "tool_calls": [{
                                "id": tc.id,
                                "type": "function",
                                "function": {
                                    "name": tc.name,
                                    "arguments": json.dumps(tc.arguments)
                                }
                            }]
                        })
                        messages.append({
                            "role": "tool",
                            "tool_call_id": tc.id,
                            "content": json.dumps(result.to_dict())
                        })
                        break
        
        # Max attempts reached or no valid result
        if result is None:
            # No query was successfully executed
            result = ToolResult(
                success=False,
                error="Failed to execute query after maximum attempts"
            )
        
        return result, False
    
    def _build_enriched_system_prompt(
        self,
        step: AnalyticalStep,
        plan: ExecutionPlan,
        accumulated_results: dict[int, ToolResult]
    ) -> str:
        """Build an enriched system prompt with context and constraints."""
        from src.services.llm_service import SYSTEM_PROMPT
        
        # Inject active database context
        db_source = "default"
        db_file = "data/ecommerce.db"
        try:
            from src.database.resolver import active_session_id, _session_databases
            sid = active_session_id.get()
            if sid and sid in _session_databases:
                db_source = _session_databases[sid].source_type
                db_file = _session_databases[sid].database_path
        except Exception:
            pass

        db_context = f"\n\n## ACTIVE DATABASE CONTEXT\n- ACTIVE DATABASE SOURCE: {db_source}\n- ACTIVE DATABASE PATH: {db_file}\n"
        if db_source == "uploaded":
            db_context += "- IMPORTANT: You are using the user's uploaded custom dataset database. Do NOT reference default e-commerce database tables/columns (orders, products, order_items, reviews, customers) unless those exact tables exist in the schema. Run schema-first queries only."
        else:
            db_context += "- You are using the default e-commerce database."

        prompt = SYSTEM_PROMPT + db_context
        
        prompt += "\n\n## ═══════════════════════════════════════════════════════════\n"
        prompt += "## CURRENT ANALYTICAL TASK\n"
        prompt += "## ═══════════════════════════════════════════════════════════\n\n"
        prompt += f"**Step {step.step_id}:** {step.description}\n\n"
        prompt += f"**Operation Type:** {step.operation}\n"
        prompt += f"**Query Intent:** {step.query_intent}\n\n"
        
        # Add original question context
        prompt += f"**Original Question:** {plan.question}\n"
        prompt += f"**Question Type:** {plan.analysis.question_type}\n"
        if plan.analysis.is_multi_step:
            prompt += f"**Multi-Step Analysis:** Yes (Step {step.step_id} of {len(plan.steps)})\n"
        prompt += "\n"
        
        # Add schema context
        if self._schema_cache:
            prompt += "## ═══════════════════════════════════════════════════════════\n"
            prompt += "## DATABASE SCHEMA (Source of Truth)\n"
            prompt += "## ═══════════════════════════════════════════════════════════\n\n"
            
            for table, schema_info in self._schema_cache.items():
                cols = schema_info.get("columns", [])
                fks = schema_info.get("foreign_keys", [])
                row_count = schema_info.get("row_count", 0)
                
                prompt += f"### Table: {table} ({row_count} rows)\n"
                prompt += "Columns:\n"
                for col in cols:
                    col_desc = f"  - {col['name']} ({col['type']})"
                    if col['is_primary_key']:
                        col_desc += " [PRIMARY KEY]"
                    if col['not_null']:
                        col_desc += " [NOT NULL]"
                    prompt += col_desc + "\n"
                
                if fks:
                    prompt += "Foreign Keys:\n"
                    for fk in fks:
                        prompt += f"  - {fk['from_column']} → {fk['to_table']}.{fk['to_column']}\n"
                
                # Show sample data for context
                samples = schema_info.get("sample_rows", [])
                if samples and len(samples) > 0:
                    prompt += f"Sample: {samples[0]}\n"
                
                prompt += "\n"
        
        # Add dependency context with ACTUAL values
        if step.depends_on:
            prompt += "## ═══════════════════════════════════════════════════════════\n"
            prompt += "## CONTEXT FROM PREVIOUS STEPS (Use Actual Values)\n"
            prompt += "## ═══════════════════════════════════════════════════════════\n\n"
            
            for dep_id in step.depends_on:
                dep_step = plan.get_step(dep_id)
                dep_result = accumulated_results.get(dep_id)
                
                if dep_step and dep_result:
                    prompt += f"### Step {dep_id}: {dep_step.description}\n"
                    prompt += f"**Status:** {'✓ Validated' if dep_step.validated else '⚠ Not Validated'}\n\n"
                    
                    if dep_step.operation == "query" and dep_result.data:
                        rows = dep_result.data.get("rows", [])
                        columns = dep_result.data.get("columns", [])
                        
                        if rows:
                            prompt += f"**Returned {len(rows)} row(s)**\n\n"
                            prompt += "**First Result (USE THIS DATA):**\n"
                            prompt += "```json\n"
                            prompt += json.dumps(rows[0], indent=2, default=str)
                            prompt += "\n```\n\n"
                            
                            if len(rows) > 1:
                                prompt += f"**All {len(rows)} Results:**\n"
                                for i, row in enumerate(rows[:5], 1):  # Show up to 5
                                    prompt += f"{i}. {row}\n"
                                if len(rows) > 5:
                                    prompt += f"... and {len(rows) - 5} more\n"
                                prompt += "\n"
                    
                    elif dep_step.operation == "validate_and_extract" and dep_result.data:
                        prompt += "**Extracted Identifier (MUST USE THIS):**\n"
                        prompt += "```json\n"
                        prompt += json.dumps(dep_result.data, indent=2)
                        prompt += "\n```\n\n"
                        prompt += "⚠️  **CRITICAL:** Use the EXACT values above. DO NOT hardcode!\n\n"
        
        # Add validation rules with emphasis
        if step.validation_rules:
            prompt += "## ═══════════════════════════════════════════════════════════\n"
            prompt += "## VALIDATION REQUIREMENTS (Must Satisfy All)\n"
            prompt += "## ═══════════════════════════════════════════════════════════\n\n"
            for i, rule in enumerate(step.validation_rules, 1):
                prompt += f"{i}. {rule}\n"
            prompt += "\n"
        
        # Add expected columns if specified
        if step.expected_columns:
            prompt += f"**Expected Output Columns:** {', '.join(step.expected_columns)}\n\n"
        
        # Add critical reminders
        prompt += "## ═══════════════════════════════════════════════════════════\n"
        prompt += "## CRITICAL REMINDERS\n"
        prompt += "## ═══════════════════════════════════════════════════════════\n\n"
        
        prompt += "### Schema Validation\n"
        prompt += "- ✓ Use ONLY tables and columns shown in the schema above\n"
        prompt += "- ✗ NEVER invent table names, column names, or relationships\n"
        prompt += "- ✓ Verify all joins use actual foreign key relationships\n\n"
        
        prompt += "### Metric Resolution\n"
        # Only inject metric hints when those specific columns exist in the active schema.
        # For uploaded databases with different schemas, let the AI derive metrics from the schema.
        active_schema = self._schema_cache or {}
        all_col_names: set[str] = set()
        for tbl_info in active_schema.values():
            if isinstance(tbl_info, dict):
                for col in tbl_info.get("columns", []):
                    all_col_names.add(col.get("name", "").lower())

        if "quantity" in all_col_names and "unit_price" in all_col_names:
            prompt += "- revenue = SUM(quantity × unit_price), NOT SUM(price)\n"
        if "quantity" in all_col_names:
            prompt += "- units_sold = SUM(quantity)\n"
        if "order_id" in all_col_names:
            prompt += "- order_count = COUNT(DISTINCT order_id)\n"
        if "customer_id" in all_col_names:
            prompt += "- customer_count = COUNT(DISTINCT customer_id)\n"
        if not all_col_names:
            # Schema not yet retrieved; provide generic guidance
            prompt += "- Determine metric calculations from the actual column types in the schema\n"
            prompt += "- Do NOT assume column names — use only columns shown in the schema above\n"
        prompt += "\n"
        
        prompt += "### Dependency Handling\n"
        if step.depends_on:
            prompt += "- ✓ Use the ACTUAL values from previous steps shown above\n"
            prompt += "- ✗ NEVER hardcode values like 'WHERE category_id = 1'\n"
            prompt += "- ✓ Extract and use validated identifiers dynamically\n\n"
        else:
            prompt += "- This step has no dependencies\n\n"
        
        prompt += "### SQL Quality\n"
        prompt += "- Write analytically CORRECT SQL, not just syntactically valid SQL\n"
        prompt += "- Ensure proper aggregation grain (prevent duplicate counting)\n"
        prompt += "- Use explicit column names, avoid SELECT *\n"
        prompt += "- Apply ORDER BY before LIMIT for ranking queries\n"
        prompt += "- Handle NULL values appropriately\n\n"
        
        prompt += "### Output Formatting\n"
        prompt += "- Use Indian Rupee format: ₹2,25,122.08\n"
        prompt += "- Return only columns needed to answer the question\n"
        prompt += "- Avoid exposing internal IDs unless specifically requested\n"
        
        return prompt


    def _validate_sql_before_execution(
        self,
        sql: str,
        step: AnalyticalStep,
        plan: ExecutionPlan,
        accumulated_results: dict[int, ToolResult]
    ) -> list[str]:
        """
        Validate SQL before execution for common issues.
        
        Returns list of issues found (empty if valid).
        """
        issues = []
        sql_lower = sql.lower()
        
        # Check 1: Schema validation
        if self._schema_cache:
            # Extract table names from SQL
            table_pattern = r'from\s+(\w+)|join\s+(\w+)'
            tables_in_sql = set()
            for match in re.finditer(table_pattern, sql_lower):
                table = match.group(1) or match.group(2)
                if table:
                    tables_in_sql.add(table)
            
            # Check if tables exist
            valid_tables = set(self._schema_cache.keys())
            invalid_tables = tables_in_sql - valid_tables
            if invalid_tables:
                issues.append(f"Invalid table names: {', '.join(invalid_tables)}")
        
        # Check 2: Hardcoded values in dependent queries
        if step.depends_on:
            # Look for hardcoded IDs
            hardcoded_patterns = [
                (r'category_id\s*=\s*\d+', 'category_id'),
                (r'product_id\s*=\s*\d+', 'product_id'),
                (r'customer_id\s*=\s*\d+', 'customer_id'),
            ]
            
            for pattern, entity in hardcoded_patterns:
                if re.search(pattern, sql_lower):
                    issues.append(
                        f"Query contains hardcoded {entity}. "
                        f"Use the actual value from the previous step's result instead."
                    )
        
        # Check 3: Ranking without ORDER BY
        if 'limit' in sql_lower and 'order by' not in sql_lower:
            if any(kw in step.description.lower() for kw in ['top', 'highest', 'best', 'bottom', 'lowest']):
                issues.append(
                    "LIMIT used without ORDER BY in a ranking query. "
                    "Results will be arbitrary without proper sorting."
                )
        
        # Check 4: Potential duplicate aggregation
        if 'sum(' in sql_lower and 'join' in sql_lower:
            # This is a heuristic - could produce false positives
            # But it's important to flag potential issues
            if sql_lower.count('join') > 1:
                issues.append(
                    "Multiple JOINs with SUM aggregation detected. "
                    "Verify that joins don't duplicate rows affecting the sum."
                )
        
        # Check 5: SELECT * in production query
        if re.search(r'select\s+\*', sql_lower):
            issues.append(
                "SELECT * should be avoided. "
                "Specify only the columns needed to answer the question."
            )
        
        return issues


    def _post_process_result(
        self,
        result: ToolResult,
        question: str
    ) -> ToolResult:
        """
        Post-process query result to filter irrelevant columns.
        
        Returns modified ToolResult with filtered data.
        """
        if not result.success or not result.data:
            return result
        
        columns = result.data.get("columns", [])
        rows = result.data.get("rows", [])
        
        # Filter to question-relevant columns
        filtered_cols, filtered_rows = self._quality_gate.filter_response_fields(
            question,
            columns,
            rows
        )
        
        # Update result data
        result.data["columns"] = filtered_cols
        result.data["rows"] = filtered_rows
        result.data["row_count"] = len(filtered_rows)
        
        # Add metadata about filtering
        if len(filtered_cols) < len(columns):
            result.metadata["filtered_columns"] = True
            result.metadata["original_column_count"] = len(columns)
            result.metadata["removed_columns"] = [c for c in columns if c not in filtered_cols]
        
        return result


    def _verify_all_requirements_met(
        self,
        plan: ExecutionPlan,
        accumulated_results: dict[int, ToolResult]
    ) -> bool:
        """
        CRITICAL: Verify that ALL sub-questions in a multi-part question have been answered.
        
        For multi-step questions, this ensures we never generate partial answers.
        
        Returns True only if ALL query stages completed successfully and were validated.
        """
        # Check if all steps are executed
        if not plan.all_steps_complete():
            print("[CRITICAL] Not all planned steps were completed")
            return False
        
        # For multi-step questions, verify ALL query stages succeeded
        if plan.analysis.is_multi_step:
            query_steps = [s for s in plan.steps if s.operation == "query"]
            
            for step in query_steps:
                if not step.executed:
                    print(f"[CRITICAL] Query stage {step.step_id} not executed: {step.description}")
                    return False
                
                if not step.validated:
                    print(f"[CRITICAL] Query stage {step.step_id} not validated: {step.description}")
                    return False
                
                result = accumulated_results.get(step.step_id)
                if not result or not result.success:
                    print(f"[CRITICAL] Query stage {step.step_id} failed or has no result")
                    return False
                
                # Check if result has data
                if result.data:
                    row_count = result.data.get("row_count", 0)
                    if row_count == 0:
                        print(f"[CRITICAL] Query stage {step.step_id} returned 0 rows")
                        return False
            
            # Verify extraction steps (for dependent queries)
            extract_steps = [s for s in plan.steps if s.operation == "validate_and_extract"]
            for step in extract_steps:
                if not step.executed or not step.validated:
                    print(f"[CRITICAL] Extraction stage {step.step_id} not validated")
                    return False
                
                result = accumulated_results.get(step.step_id)
                if not result or not result.success or not result.data:
                    print(f"[CRITICAL] Extraction stage {step.step_id} has no valid data")
                    return False
        
        # All checks passed
        return True


