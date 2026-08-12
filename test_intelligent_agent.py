"""
Test script for the Intelligent Agent

Tests the critical multi-step question:
"Which product category generates the highest revenue, and what are the top 3 products in that category?"
"""

import asyncio
import sys
from pathlib import Path

# Add src to path
sys.path.insert(0, str(Path(__file__).parent))

from src.database.db_manager import DatabaseManager
from src.agent.intelligent_agent import IntelligentAgent
from src.tools.schema_discovery import SchemaDiscoveryTool
from src.tools.query_executor import ExecuteQueryTool
from src.tools.visualizer import VisualizeDataTool
from src.tools.diagrammer import SystemDiagramTool
from src.tools.insight_explainer import ExplainInsightsTool
from src.config import get_settings


async def test_intelligent_agent():
    """Test the intelligent agent with the critical multi-step question."""
    
    print("=" * 80)
    print("Testing Intelligent Agent")
    print("=" * 80)
    
    # Initialize components
    settings = get_settings()
    db = DatabaseManager(settings.default_db_path)
    
    tools = [
        SchemaDiscoveryTool(db),
        ExecuteQueryTool(db),
        VisualizeDataTool(),
        SystemDiagramTool(db),
        ExplainInsightsTool(),
    ]
    
    agent = IntelligentAgent(
        db_manager=db,
        tools=tools,
        llm_provider=settings.llm_provider
    )
    
    # Test questions
    test_questions = [
        "Which product category generates the highest revenue, and what are the top 3 products in that category?",
        "What are the top 5 best-selling products by revenue?",
        "Show me monthly revenue trend for 2025",
    ]
    
    for i, question in enumerate(test_questions, 1):
        print(f"\n{'='*80}")
        print(f"Test {i}: {question}")
        print('='*80)
        
        try:
            event_count = 0
            async for event in agent.query_stream(question, session_id=f"test-{i}"):
                event_count += 1
                event_type = event.get("type")
                data = event.get("data", {})
                
                if event_type == "analysis":
                    print(f"\n[ANALYSIS]")
                    print(f"  Question Type: {data.get('question_type')}")
                    print(f"  Multi-Step: {data.get('is_multi_step')}")
                    print(f"  Entities: {data.get('entities')}")
                    print(f"  Metrics: {data.get('metrics')}")
                    print(f"  Requirements: {data.get('requirements', [])[:3]}")
                
                elif event_type == "plan":
                    print(f"\n[EXECUTION PLAN]")
                    print(f"  Total Steps: {data.get('total_steps')}")
                    for step_desc in data.get('step_descriptions', []):
                        print(f"    - {step_desc}")
                
                elif event_type == "step_start":
                    print(f"\n[STEP {data.get('step_id')}] {data.get('description')}")
                    print(f"  Operation: {data.get('operation')}")
                
                elif event_type == "sql":
                    sql = data.get('sql', '')
                    result = data.get('result', {})
                    print(f"\n[SQL EXECUTED]")
                    print(f"  {sql}")
                    print(f"  Rows returned: {result.get('row_count', 0)}")
                    if result.get('rows'):
                        print(f"  First row: {result['rows'][0]}")
                
                elif event_type == "extraction":
                    print(f"\n[EXTRACTED] {data.get('extracted')}")
                
                elif event_type == "chart":
                    print(f"\n[CHART] Type: {data.get('chart_type')}")
                
                elif event_type == "insights":
                    print(f"\n[INSIGHTS]")
                    explanation = data.get('explanation', '')
                    print(f"  {explanation[:200]}...")
                
                elif event_type == "answer_chunk":
                    # Skip printing chunks during test
                    pass
                
                elif event_type == "complete":
                    print(f"\n[COMPLETE]")
                    print(f"  Steps Executed: {data.get('steps_executed')}")
                    print(f"  All Validated: {data.get('all_validated')}")
                
                elif event_type == "validation_failed":
                    print(f"\n[WARNING] Validation failed at step {data.get('step_id')}")
                
                elif event_type == "status":
                    print(f"[STATUS] {data.get('message')}")
            
            print(f"\nTotal events: {event_count}")
            
        except Exception as exc:
            print(f"\n[ERROR] {exc}")
            import traceback
            traceback.print_exc()
    
    print(f"\n{'='*80}")
    print("Testing Complete")
    print('='*80)


if __name__ == "__main__":
    asyncio.run(test_intelligent_agent())
