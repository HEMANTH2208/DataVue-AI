"""
Test script for verifying the CRITICAL MULTI-PART QUESTION RULE implementation.

This script tests that the system:
1. NEVER generates partial answers to multi-part questions
2. NEVER hardcodes intermediate values (category_id, product_id, etc.)
3. Uses ACTUAL validated results from previous stages
4. Validates every stage before proceeding
5. Displays error if ANY stage fails
"""

import requests
import json
import sys
import time


BASE_URL = "http://localhost:8000"
COLORS = {
    'GREEN': '\033[92m',
    'RED': '\033[91m',
    'YELLOW': '\033[93m',
    'BLUE': '\033[94m',
    'RESET': '\033[0m',
    'BOLD': '\033[1m'
}


def print_color(message, color='RESET'):
    """Print colored message."""
    print(f"{COLORS[color]}{message}{COLORS['RESET']}")


def print_header(message):
    """Print section header."""
    print("\n" + "="*80)
    print_color(f"{COLORS['BOLD']}{message}", 'BLUE')
    print("="*80 + "\n")


def test_multi_part_question(question, model='gemini'):
    """
    Test a multi-part question and verify the implementation.
    
    Checks:
    - Question is decomposed into stages
    - All stages complete
    - No hardcoded values in SQL
    - Complete answer (not partial)
    """
    print_header(f"Testing: {question}")
    
    # Send request
    response = requests.get(
        f"{BASE_URL}/api/query/intelligent/stream",
        params={'question': question, 'model': model},
        stream=True
    )
    
    if response.status_code != 200:
        print_color(f"❌ Request failed: {response.status_code}", 'RED')
        return False
    
    # Parse SSE events
    events = []
    analysis = None
    plan = None
    sql_queries = []
    extractions = []
    charts = []
    insights = None
    final_answer = ""
    validation_failures = []
    completion = None
    
    for line in response.iter_lines(decode_unicode=True):
        if line.startswith('data: '):
            try:
                data = json.loads(line[6:])
                events.append(data)
                
                event_type = data.get('type')
                event_data = data.get('data', {})
                
                if event_type == 'analysis':
                    analysis = event_data
                elif event_type == 'plan':
                    plan = event_data
                elif event_type == 'sql':
                    sql_queries.append(event_data)
                elif event_type == 'extraction':
                    extractions.append(event_data)
                elif event_type == 'chart':
                    charts.append(event_data)
                elif event_type == 'insights':
                    insights = event_data
                elif event_type == 'answer_chunk':
                    final_answer = event_data.get('content', '')
                elif event_type == 'validation_failed':
                    validation_failures.append(event_data)
                elif event_type == 'complete':
                    completion = event_data
                    
            except json.JSONDecodeError:
                pass
    
    # Verification checks
    print_color("\n📋 VERIFICATION RESULTS:", 'BOLD')
    all_checks_passed = True
    
    # Check 1: Question Analysis
    print_color("\n1️⃣ Question Analysis:", 'YELLOW')
    if analysis:
        is_multi_step = analysis.get('is_multi_step', False)
        print(f"   Multi-step detected: {is_multi_step}")
        if not is_multi_step:
            print_color("   ⚠️  Warning: Expected multi-step question", 'YELLOW')
    else:
        print_color("   ❌ No analysis phase detected", 'RED')
        all_checks_passed = False
    
    # Check 2: Planning
    print_color("\n2️⃣ Execution Plan:", 'YELLOW')
    if plan:
        total_steps = plan.get('total_steps', 0)
        print(f"   Total steps planned: {total_steps}")
        print("   Steps:")
        for i, desc in enumerate(plan.get('step_descriptions', []), 1):
            print(f"      {i}. {desc}")
        
        # Verify sequential stages
        query_stages = [d for d in plan.get('step_descriptions', []) if 'Stage' in d and 'Query' not in d]
        if len(query_stages) >= 2:
            print_color(f"   ✓ Sequential stages detected: {len(query_stages)}", 'GREEN')
        else:
            print_color(f"   ⚠️  Expected multiple sequential stages", 'YELLOW')
    else:
        print_color("   ❌ No execution plan detected", 'RED')
        all_checks_passed = False
    
    # Check 3: SQL Queries - No hardcoded values
    print_color("\n3️⃣ SQL Query Validation:", 'YELLOW')
    if sql_queries:
        print(f"   Queries executed: {len(sql_queries)}")
        
        for i, query_data in enumerate(sql_queries, 1):
            sql = query_data.get('sql', '')
            print(f"\n   Query {i}:")
            print(f"   {sql[:100]}...")
            
            # Check for hardcoded IDs
            import re
            hardcoded_patterns = [
                (r'category_id\s*=\s*\d+', 'category_id'),
                (r'product_id\s*=\s*\d+', 'product_id'),
                (r'customer_id\s*=\s*\d+', 'customer_id'),
            ]
            
            found_hardcoded = False
            for pattern, entity in hardcoded_patterns:
                matches = re.findall(pattern, sql.lower())
                if matches and i > 1:  # Only check dependent queries
                    print_color(f"   ❌ VIOLATION: Hardcoded {entity} found: {matches}", 'RED')
                    all_checks_passed = False
                    found_hardcoded = True
            
            if not found_hardcoded and i > 1:
                print_color(f"   ✓ No hardcoded values detected", 'GREEN')
            
            # Check result
            result = query_data.get('result', {})
            row_count = result.get('row_count', 0)
            print(f"   Result: {row_count} rows returned")
    else:
        print_color("   ⚠️  No SQL queries executed", 'YELLOW')
    
    # Check 4: Extraction Steps
    print_color("\n4️⃣ Extraction Validation:", 'YELLOW')
    if extractions:
        print(f"   Extraction steps: {len(extractions)}")
        for i, extract in enumerate(extractions, 1):
            extracted_data = extract.get('extracted', {})
            print(f"   Extraction {i}: {extracted_data}")
            if extracted_data:
                print_color(f"   ✓ Valid data extracted", 'GREEN')
            else:
                print_color(f"   ❌ No data extracted", 'RED')
                all_checks_passed = False
    else:
        print_color("   ⚠️  No extraction steps (may be normal for simple queries)", 'YELLOW')
    
    # Check 5: Visualizations
    print_color("\n5️⃣ Visualizations:", 'YELLOW')
    if charts:
        print(f"   Charts generated: {len(charts)}")
        for i, chart in enumerate(charts, 1):
            chart_type = chart.get('chart_type', 'unknown')
            print(f"   Chart {i}: {chart_type}")
        
        # For multi-part questions, expect multiple charts
        if len(charts) >= 2:
            print_color(f"   ✓ Multiple visualizations for multi-part answer", 'GREEN')
        else:
            print_color(f"   ⚠️  Expected multiple charts for multi-part question", 'YELLOW')
    else:
        print_color("   ⚠️  No visualizations generated", 'YELLOW')
    
    # Check 6: Insights and Explanation
    print_color("\n6️⃣ Explanation Quality:", 'YELLOW')
    if insights:
        explanation = insights.get('explanation', '')
        print(f"   Explanation length: {len(explanation)} chars")
        
        # Check if explanation addresses multiple parts
        keywords_to_check = ['category', 'categories', 'product', 'products', 'revenue', 'top']
        found_keywords = [kw for kw in keywords_to_check if kw in explanation.lower()]
        print(f"   Keywords found: {found_keywords}")
        
        if len(found_keywords) >= 4:
            print_color(f"   ✓ Comprehensive explanation covering multiple aspects", 'GREEN')
        else:
            print_color(f"   ⚠️  Explanation may be incomplete", 'YELLOW')
    
    # Check 7: Final Answer Completeness
    print_color("\n7️⃣ Final Answer:", 'YELLOW')
    if final_answer:
        print(f"   Answer length: {len(final_answer)} chars")
        print(f"   Preview: {final_answer[:200]}...")
        
        # Check for both parts of the question
        has_category_info = any(word in final_answer.lower() for word in ['category', 'categories'])
        has_product_info = any(word in final_answer.lower() for word in ['product', 'products'])
        
        if has_category_info and has_product_info:
            print_color(f"   ✓ Answer addresses BOTH sub-questions", 'GREEN')
        else:
            print_color(f"   ❌ VIOLATION: Partial answer detected!", 'RED')
            print(f"      Has category info: {has_category_info}")
            print(f"      Has product info: {has_product_info}")
            all_checks_passed = False
    else:
        print_color("   ❌ No final answer generated", 'RED')
        all_checks_passed = False
    
    # Check 8: Validation Failures
    print_color("\n8️⃣ Validation Status:", 'YELLOW')
    if validation_failures:
        print_color(f"   ⚠️  {len(validation_failures)} validation failure(s) detected", 'YELLOW')
        for failure in validation_failures:
            print(f"      {failure}")
    else:
        print_color(f"   ✓ No validation failures", 'GREEN')
    
    # Check 9: Completion Status
    print_color("\n9️⃣ Completion:", 'YELLOW')
    if completion:
        all_validated = completion.get('all_validated', False)
        steps_executed = completion.get('steps_executed', 0)
        print(f"   Steps executed: {steps_executed}")
        print(f"   All validated: {all_validated}")
        
        if all_validated:
            print_color(f"   ✓ All stages completed and validated", 'GREEN')
        else:
            print_color(f"   ❌ Not all stages validated", 'RED')
            all_checks_passed = False
    else:
        print_color("   ❌ No completion event", 'RED')
        all_checks_passed = False
    
    # Final verdict
    print_color("\n" + "="*80, 'BOLD')
    if all_checks_passed:
        print_color("✅ TEST PASSED: Multi-part question rule correctly implemented!", 'GREEN')
    else:
        print_color("❌ TEST FAILED: Issues detected in implementation", 'RED')
    print_color("="*80 + "\n", 'BOLD')
    
    return all_checks_passed


def main():
    """Run test suite."""
    print_color("""
╔══════════════════════════════════════════════════════════════════════════════╗
║                                                                              ║
║           CRITICAL MULTI-PART QUESTION RULE - TEST SUITE                    ║
║                                                                              ║
║  Testing that the system NEVER generates partial answers to multi-part      ║
║  analytical questions.                                                       ║
║                                                                              ║
╚══════════════════════════════════════════════════════════════════════════════╝
    """, 'BLUE')
    
    # Check server health
    print_color("🔍 Checking server health...", 'YELLOW')
    try:
        response = requests.get(f"{BASE_URL}/api/health?model=gemini", timeout=5)
        if response.status_code == 200:
            print_color("✓ Server is running\n", 'GREEN')
        else:
            print_color(f"❌ Server health check failed: {response.status_code}", 'RED')
            sys.exit(1)
    except Exception as e:
        print_color(f"❌ Cannot connect to server: {e}", 'RED')
        print_color("Please ensure the server is running on http://localhost:8000", 'YELLOW')
        sys.exit(1)
    
    # Test cases
    test_cases = [
        {
            'name': 'Test 1: Category → Products (Critical Test)',
            'question': 'Which product category generates the highest revenue, and what are the top 3 products in that category?',
            'model': 'gemini'
        },
        {
            'name': 'Test 2: Customer → Orders',
            'question': 'Which customer has placed the most orders, and what are their top 3 purchased products?',
            'model': 'gemini'
        },
        {
            'name': 'Test 3: Time → Categories',
            'question': 'Which month had the highest revenue in 2025, and what were the top product categories that month?',
            'model': 'gemini'
        }
    ]
    
    results = []
    
    for i, test_case in enumerate(test_cases, 1):
        print_header(f"TEST CASE {i}/{len(test_cases)}: {test_case['name']}")
        
        try:
            passed = test_multi_part_question(
                test_case['question'],
                test_case['model']
            )
            results.append((test_case['name'], passed))
            
            # Wait between tests to avoid rate limits
            if i < len(test_cases):
                print_color("\n⏳ Waiting 3 seconds before next test...", 'YELLOW')
                time.sleep(3)
        except Exception as e:
            print_color(f"❌ Test failed with exception: {e}", 'RED')
            results.append((test_case['name'], False))
    
    # Summary
    print_header("TEST SUITE SUMMARY")
    passed_count = sum(1 for _, passed in results if passed)
    total_count = len(results)
    
    print(f"\nResults: {passed_count}/{total_count} tests passed\n")
    
    for test_name, passed in results:
        status = "✅ PASSED" if passed else "❌ FAILED"
        color = 'GREEN' if passed else 'RED'
        print_color(f"{status}: {test_name}", color)
    
    print("\n" + "="*80)
    
    if passed_count == total_count:
        print_color("🎉 ALL TESTS PASSED!", 'GREEN')
        print_color("The CRITICAL MULTI-PART QUESTION RULE is correctly implemented.", 'GREEN')
        return 0
    else:
        print_color(f"⚠️  {total_count - passed_count} TEST(S) FAILED", 'RED')
        print_color("Please review the implementation for issues.", 'RED')
        return 1


if __name__ == '__main__':
    sys.exit(main())
