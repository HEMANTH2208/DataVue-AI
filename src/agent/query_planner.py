"""
LLMSQL Query Planner

Creates multi-step analytical execution plans based on question analysis.
Ensures dependent steps use actual results from previous steps.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any
from src.agent.question_analyzer import QuestionAnalysis


@dataclass
class AnalyticalStep:
    """A single step in the analytical plan."""
    
    step_id: int
    description: str
    operation: str  # schema_discovery, query, visualize, explain, diagram
    depends_on: list[int] = field(default_factory=list)  # step_ids this depends on
    
    # For query steps
    query_intent: str = ""
    expected_columns: list[str] = field(default_factory=list)
    validation_rules: list[str] = field(default_factory=list)
    
    # Execution state
    executed: bool = False
    result: Any = None
    validated: bool = False


@dataclass
class ExecutionPlan:
    """Complete execution plan for a question."""
    
    question: str
    analysis: QuestionAnalysis
    steps: list[AnalyticalStep] = field(default_factory=list)
    current_step: int = 0
    
    def get_next_step(self) -> AnalyticalStep | None:
        """Get the next unexecuted step whose dependencies are satisfied."""
        for step in self.steps:
            if step.executed:
                continue
            
            # Check if all dependencies are satisfied
            deps_satisfied = all(
                self.steps[dep_id].executed and self.steps[dep_id].validated
                for dep_id in step.depends_on
            )
            
            if deps_satisfied:
                return step
        
        return None
    
    def mark_step_complete(self, step_id: int, result: Any, validated: bool = True) -> None:
        """Mark a step as complete with its result."""
        for step in self.steps:
            if step.step_id == step_id:
                step.executed = True
                step.result = result
                step.validated = validated
                break
    
    def get_step(self, step_id: int) -> AnalyticalStep | None:
        """Get step by ID."""
        for step in self.steps:
            if step.step_id == step_id:
                return step
        return None
    
    def all_steps_complete(self) -> bool:
        """Check if all steps are executed and validated."""
        return all(step.executed and step.validated for step in self.steps)


class QueryPlanner:
    """Creates execution plans from question analysis."""
    
    def create_plan(self, analysis: QuestionAnalysis) -> ExecutionPlan:
        """Create a complete execution plan from question analysis."""
        plan = ExecutionPlan(
            question=analysis.original_question,
            analysis=analysis
        )
        
        step_id = 0
        
        # Step 0: Always start with schema discovery if we don't have it
        schema_step = AnalyticalStep(
            step_id=step_id,
            description="Discover database schema",
            operation="schema_discovery",
            query_intent="Get database structure"
        )
        plan.steps.append(schema_step)
        step_id += 1
        
        # Handle different question types
        if analysis.question_type == "multi_step":
            step_id = self._plan_multi_step(analysis, plan, step_id)
        elif analysis.suggested_viz in ['er', 'flowchart']:
            step_id = self._plan_diagram(analysis, plan, step_id)
        else:
            step_id = self._plan_single_query(analysis, plan, step_id)
        
        return plan
    
    def _plan_multi_step(self, analysis: QuestionAnalysis, plan: ExecutionPlan, start_id: int) -> int:
        """
        Plan multi-step analytical queries with STRICT sequential validation.
        
        CRITICAL: Never generate partial answers. Each stage must be validated
        before proceeding to dependent stages.
        """
        step_id = start_id
        
        # Example: "Which category has highest revenue, and what are top 3 products in that category?"
        # This becomes a STRICT sequential pipeline:
        # Stage 1: Query ALL categories by revenue
        # Stage 2: VALIDATE and EXTRACT highest category
        # Stage 3: Query products ONLY in validated category
        # Stage 4: VALIDATE exactly 3 products returned
        # Stage 5: Generate visualizations
        # Stage 6: Generate explanation
        
        if 'category' in analysis.entities and 'product' in analysis.entities:
            # Category -> Product drill-down pattern
            
            # STAGE 1: Calculate revenue for ALL categories
            step1 = AnalyticalStep(
                step_id=step_id,
                description="Stage 1: Calculate revenue for ALL categories",
                operation="query",
                depends_on=[0],  # depends on schema
                query_intent="Calculate total revenue for each category. Return ALL categories sorted by revenue descending.",
                expected_columns=['category_id', 'category_name', 'revenue'],
                validation_rules=[
                    "MUST return ALL categories, not filtered",
                    "MUST include category_id for subsequent stages",
                    "MUST include category_name for display",
                    "MUST calculate revenue as SUM(quantity × unit_price)",
                    "MUST be sorted by revenue DESC",
                    "MUST NOT hardcode any category value"
                ]
            )
            plan.steps.append(step1)
            step_id += 1
            
            # STAGE 2: EXTRACT highest revenue category
            step2 = AnalyticalStep(
                step_id=step_id,
                description="Stage 2: Extract and validate highest revenue category from Stage 1 results",
                operation="validate_and_extract",
                depends_on=[step1.step_id],
                query_intent="Extract the category_id and category_name of the highest revenue category",
                validation_rules=[
                    "MUST extract actual category_id from Stage 1 first row",
                    "MUST extract actual category_name from Stage 1 first row",
                    "MUST NOT assume or hardcode category values",
                    "Extracted values become inputs to Stage 3"
                ]
            )
            plan.steps.append(step2)
            step_id += 1
            
            # STAGE 3: Query products in validated category ONLY
            step3 = AnalyticalStep(
                step_id=step_id,
                description=f"Stage 3: Get top {analysis.top_n or 3} products in the highest revenue category",
                operation="query",
                depends_on=[step2.step_id],  # MUST wait for Stage 2
                query_intent=f"Calculate product revenue ONLY for products in the category identified in Stage 2. Return top {analysis.top_n or 3} products by revenue.",
                expected_columns=['product_id', 'product_name', 'revenue'],
                validation_rules=[
                    f"MUST use actual category_id from Stage 2 result",
                    f"MUST NOT hardcode category_id value",
                    f"MUST calculate revenue as SUM(quantity × unit_price) for products in that category only",
                    f"MUST be sorted by revenue DESC",
                    f"MUST LIMIT {analysis.top_n or 3}",
                    f"MUST return EXACTLY {analysis.top_n or 3} or fewer products",
                    f"MUST NOT return products from other categories"
                ]
            )
            plan.steps.append(step3)
            step_id += 1
            
            # STAGE 4: Visualize category comparison (answers sub-question 1)
            step4 = AnalyticalStep(
                step_id=step_id,
                description="Stage 4: Visualize revenue by category",
                operation="visualize",
                depends_on=[step1.step_id],
                query_intent="Show revenue comparison across all categories",
                validation_rules=[
                    "Chart must show ALL categories from Stage 1",
                    "Chart must highlight the highest revenue category",
                    "Chart type must be bar chart for ranking"
                ]
            )
            plan.steps.append(step4)
            step_id += 1
            
            # STAGE 5: Visualize top products (answers sub-question 2)
            step5 = AnalyticalStep(
                step_id=step_id,
                description=f"Stage 5: Visualize top {analysis.top_n or 3} products in winning category",
                operation="visualize",
                depends_on=[step3.step_id],
                query_intent=f"Show top {analysis.top_n or 3} products by revenue",
                validation_rules=[
                    f"Chart must show EXACTLY the products from Stage 3",
                    f"Chart must show {analysis.top_n or 3} or fewer products",
                    "Chart type must be bar chart for ranking",
                    "Chart must be labeled with winning category name"
                ]
            )
            plan.steps.append(step5)
            step_id += 1
            
            # STAGE 6: Generate COMPLETE explanation (both sub-questions)
            step6 = AnalyticalStep(
                step_id=step_id,
                description="Stage 6: Generate complete explanation covering BOTH sub-questions",
                operation="explain",
                depends_on=[step1.step_id, step3.step_id],  # Depends on BOTH stages
                query_intent="Explain: 1) Which category has highest revenue, 2) What are the top products in that category",
                validation_rules=[
                    "Explanation MUST answer BOTH parts of the question",
                    "MUST state the winning category name and revenue",
                    "MUST list the top products with their revenue",
                    "MUST NOT mention generic statistics irrelevant to the question",
                    "MUST NOT use hardcoded values",
                    "All values MUST come from validated Stage 1 and Stage 3 results"
                ]
            )
            plan.steps.append(step6)
            step_id += 1
        
        else:
            # Generic multi-step: treat each analytical step as separate query with validation
            for i, step_desc in enumerate(analysis.analytical_steps):
                if i == 0:
                    # First query
                    query_step = AnalyticalStep(
                        step_id=step_id,
                        description=f"Stage {i+1}: {step_desc}",
                        operation="query",
                        depends_on=[0],
                        query_intent=step_desc,
                        validation_rules=[
                            f"MUST fully answer: {step_desc}",
                            "MUST NOT use hardcoded values",
                            "Result will be validated before proceeding to dependent stages"
                        ]
                    )
                    plan.steps.append(query_step)
                    step_id += 1
                else:
                    # Check if this step depends on previous
                    depends_on_prev = any(ref in step_desc.lower() for ref in ['that', 'this', 'the', 'its', 'their'])
                    
                    if depends_on_prev:
                        # Add extraction step first
                        extract_step = AnalyticalStep(
                            step_id=step_id,
                            description=f"Extract validated results from Stage {i}",
                            operation="validate_and_extract",
                            depends_on=[step_id - 1],
                            query_intent=f"Extract identifier from previous stage for use in Stage {i+1}",
                            validation_rules=[
                                "MUST extract actual values from previous stage",
                                "MUST NOT hardcode or assume values"
                            ]
                        )
                        plan.steps.append(extract_step)
                        step_id += 1
                    
                    # Dependent query
                    query_step = AnalyticalStep(
                        step_id=step_id,
                        description=f"Stage {i+1}: {step_desc}",
                        operation="query",
                        depends_on=[step_id - 1],
                        query_intent=step_desc,
                        validation_rules=[
                            f"MUST fully answer: {step_desc}",
                            "MUST use actual values from previous validated stage" if depends_on_prev else "Standard validation",
                            "MUST NOT hardcode values"
                        ]
                    )
                    plan.steps.append(query_step)
                    step_id += 1
            
            # Add visualizations for each analytical component
            # Count query steps
            query_steps = [s for s in plan.steps if s.operation == "query"]
            
            for i, query_step in enumerate(query_steps):
                if analysis.suggested_viz not in ['er', 'flowchart']:
                    viz_step = AnalyticalStep(
                        step_id=step_id,
                        description=f"Visualize results from Stage {query_step.step_id}",
                        operation="visualize",
                        depends_on=[query_step.step_id],
                        validation_rules=[
                            f"MUST visualize data from Stage {query_step.step_id}",
                            "MUST NOT include data from other stages unless explicitly required"
                        ]
                    )
                    plan.steps.append(viz_step)
                    step_id += 1
            
            # Final comprehensive explanation covering ALL sub-questions
            explain_step = AnalyticalStep(
                step_id=step_id,
                description="Generate complete explanation covering ALL sub-questions",
                operation="explain",
                depends_on=[s.step_id for s in query_steps],  # Depends on ALL query stages
                query_intent="Explain findings from all analytical stages",
                validation_rules=[
                    "MUST answer EVERY sub-question in the original question",
                    "MUST NOT generate partial answer",
                    "All values MUST come from validated results",
                    "MUST NOT fabricate or estimate values"
                ]
            )
            plan.steps.append(explain_step)
            step_id += 1
        
        return step_id
    
    def _plan_single_query(self, analysis: QuestionAnalysis, plan: ExecutionPlan, start_id: int) -> int:
        """Plan a single-query analysis."""
        step_id = start_id
        
        # Step 1: Execute main query
        validation_rules = []
        if analysis.top_n:
            validation_rules.append(f"Result must contain at most {analysis.top_n} rows")
        if analysis.metrics:
            validation_rules.append(f"Result must include metrics: {', '.join(analysis.metrics)}")
        
        query_step = AnalyticalStep(
            step_id=step_id,
            description=analysis.original_question,
            operation="query",
            depends_on=[0],
            query_intent=analysis.original_question,
            expected_columns=[*analysis.dimensions, *analysis.metrics],
            validation_rules=validation_rules
        )
        plan.steps.append(query_step)
        step_id += 1
        
        # Step 2: Visualize
        if analysis.suggested_viz not in ['er', 'flowchart']:
            viz_step = AnalyticalStep(
                step_id=step_id,
                description=f"Generate {analysis.suggested_viz} chart",
                operation="visualize",
                depends_on=[step_id - 1]
            )
            plan.steps.append(viz_step)
            step_id += 1
        
        # Step 3: Explain
        explain_step = AnalyticalStep(
            step_id=step_id,
            description="Generate explanation",
            operation="explain",
            depends_on=[step_id - 2 if analysis.suggested_viz not in ['er', 'flowchart'] else step_id - 1]
        )
        plan.steps.append(explain_step)
        step_id += 1
        
        return step_id
    
    def _plan_diagram(self, analysis: QuestionAnalysis, plan: ExecutionPlan, start_id: int) -> int:
        """Plan diagram generation."""
        step_id = start_id
        
        diagram_step = AnalyticalStep(
            step_id=step_id,
            description=f"Generate {analysis.suggested_viz} diagram",
            operation="diagram",
            depends_on=[0],
            query_intent=analysis.original_question
        )
        plan.steps.append(diagram_step)
        step_id += 1
        
        return step_id
