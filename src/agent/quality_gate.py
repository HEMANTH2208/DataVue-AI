"""
LLMSQL Quality Gate

Final validation before displaying results to ensure:
- All requirements are met
- No hardcoded values in dependent queries
- Proper metric definitions used
- No generic statistics unless relevant
- Evidence-based insights only
- Proper formatting
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any
import re


@dataclass
class QualityGateResult:
    """Result of quality gate validation."""
    
    passed: bool
    failures: list[str] = None
    warnings: list[str] = None
    
    def __post_init__(self):
        if self.failures is None:
            self.failures = []
        if self.warnings is None:
            self.warnings = []


class QualityGate:
    """Final quality validation before user-facing output."""
    
    def validate_final_response(
        self,
        question: str,
        sql: str | None,
        result: dict[str, Any] | None,
        explanation: str,
        visualizations: list[dict] = None,
        intermediate_results: list[dict] = None
    ) -> QualityGateResult:
        """
        Comprehensive final validation check before displaying results.
        
        Returns QualityGateResult indicating if response meets all quality criteria.
        """
        failures = []
        warnings = []
        
        # Check 1: Intent Coverage
        if not self._check_intent_covered(question, explanation):
            failures.append("Response does not directly answer the user's question")
        
        # Check 2: No Hardcoded Values in Dependent Queries
        if sql and intermediate_results:
            hardcoded = self._check_hardcoded_values(sql, intermediate_results)
            if hardcoded:
                failures.append(f"Query contains hardcoded values: {hardcoded}")
        
        # Check 3: Result-Explanation Consistency
        if result and explanation:
            consistency_issues = self._check_consistency(result, explanation)
            if consistency_issues:
                failures.extend(consistency_issues)
        
        # Check 4: No Generic Statistics (unless relevant)
        generic_stats = self._check_generic_statistics(question, explanation)
        if generic_stats:
            warnings.append(f"Contains generic statistics not relevant to question: {generic_stats}")
        
        # Check 5: No Internal IDs Presented as Insights
        if explanation:
            id_issues = self._check_id_exposure(explanation)
            if id_issues:
                failures.extend(id_issues)
        
        # Check 6: Proper Currency Formatting
        if explanation:
            format_issues = self._check_formatting(explanation)
            if format_issues:
                warnings.extend(format_issues)
        
        # Check 7: Evidence-Based Claims Only
        if explanation:
            unsupported = self._check_unsupported_claims(explanation, result)
            if unsupported:
                warnings.extend(unsupported)
        
        # Check 8: Visualization Matches Question
        if visualizations and result:
            viz_issues = self._check_visualization_relevance(question, visualizations, result)
            if viz_issues:
                warnings.extend(viz_issues)
        
        passed = len(failures) == 0
        
        return QualityGateResult(
            passed=passed,
            failures=failures,
            warnings=warnings
        )
    
    def _check_intent_covered(self, question: str, explanation: str) -> bool:
        """Check if explanation addresses the question."""
        question_lower = question.lower()
        explanation_lower = explanation.lower()
        
        # Extract key question words
        question_keywords = set()
        
        # Entities
        entity_patterns = ['product', 'category', 'customer', 'order', 'review']
        for entity in entity_patterns:
            if entity in question_lower:
                question_keywords.add(entity)
        
        # Metrics
        metric_patterns = ['revenue', 'sales', 'price', 'quantity', 'count']
        for metric in metric_patterns:
            if metric in question_lower:
                question_keywords.add(metric)
        
        # Operations
        if any(kw in question_lower for kw in ['highest', 'top', 'best', 'most']):
            question_keywords.add('ranking')
        
        # Check if explanation addresses these
        coverage = sum(1 for kw in question_keywords if kw in explanation_lower)
        
        return coverage >= len(question_keywords) * 0.6  # At least 60% coverage
    
    def _check_hardcoded_values(
        self,
        sql: str,
        intermediate_results: list[dict]
    ) -> str | None:
        """Check for hardcoded values that should be dynamic."""
        sql_lower = sql.lower()
        
        # Look for hardcoded IDs like "category_id = 1"
        hardcoded_patterns = [
            r'category_id\s*=\s*\d+',
            r'product_id\s*=\s*\d+',
            r'customer_id\s*=\s*\d+',
        ]
        
        for pattern in hardcoded_patterns:
            match = re.search(pattern, sql_lower)
            if match:
                return match.group(0)
        
        return None
    
    def _check_consistency(
        self,
        result: dict[str, Any],
        explanation: str
    ) -> list[str]:
        """Check consistency between result and explanation."""
        issues = []
        
        row_count = result.get("row_count", 0)
        explanation_lower = explanation.lower()
        
        # Check if explanation mentions different row counts
        row_mentions = re.findall(r'(\d+)\s+(results?|rows?|products?|categories?|items?)', explanation_lower)
        
        for num_str, entity in row_mentions:
            num = int(num_str)
            if 'result' in entity or 'row' in entity:
                if num != row_count and row_count > 0:
                    issues.append(
                        f"Explanation mentions {num} {entity} but actual result has {row_count} rows"
                    )
        
        # Check if explanation mentions values not in results
        # Extract all numbers from explanation
        exp_values = re.findall(r'₹?([\d,]+\.?\d*)', explanation)
        
        if exp_values and result.get("rows"):
            # Get all values from results
            result_values = set()
            for row in result["rows"]:
                for value in row.values():
                    if value is not None:
                        # Normalize value
                        try:
                            if isinstance(value, (int, float)):
                                result_values.add(f"{float(value):.2f}")
                                result_values.add(f"{float(value):,.2f}")
                        except:
                            pass
            
            # Check if explanation values exist in results (loose check)
            # This is approximate due to formatting differences
            suspicious_count = 0
            for val in exp_values[:5]:  # Check first 5 values
                normalized_val = val.replace(',', '')
                if normalized_val not in ' '.join(str(v) for v in result_values):
                    suspicious_count += 1
            
            if suspicious_count >= 3:
                issues.append("Explanation may contain values not present in results")
        
        return issues
    
    def _check_generic_statistics(self, question: str, explanation: str) -> list[str]:
        """Check for generic statistics not relevant to the question."""
        generic_phrases = []
        explanation_lower = explanation.lower()
        question_lower = question.lower()
        
        # Generic phrases that should only appear if relevant
        checks = [
            ('the query returned', ['how many', 'count']),
            ('average', ['average', 'avg', 'mean']),
            ('total', ['total', 'sum', 'all']),
            ('range', ['range', 'min', 'max']),
            ('for column', []),  # Almost never appropriate
        ]
        
        for phrase, relevant_keywords in checks:
            if phrase in explanation_lower:
                # Check if relevant to question
                is_relevant = any(kw in question_lower for kw in relevant_keywords)
                if not is_relevant and relevant_keywords:
                    generic_phrases.append(phrase)
        
        return generic_phrases
    
    def _check_id_exposure(self, explanation: str) -> list[str]:
        """Check if internal IDs are being presented as insights."""
        issues = []
        explanation_lower = explanation.lower()
        
        # Patterns that suggest IDs are being treated as meaningful
        problematic_patterns = [
            (r'product\s+\d+\s+leads', 'product ID presented as insight'),
            (r'category\s+\d+\s+(?:has|leads|generates)', 'category ID presented as insight'),
            (r'customer\s+\d+\s+(?:has|made)', 'customer ID presented as insight'),
        ]
        
        for pattern, message in problematic_patterns:
            if re.search(pattern, explanation_lower):
                issues.append(message)
        
        return issues
    
    def _check_formatting(self, explanation: str) -> list[str]:
        """Check for proper formatting."""
        issues = []
        
        # Check for dollar signs (should be rupees)
        if '$' in explanation:
            issues.append("Contains dollar sign ($) instead of rupee symbol (₹)")
        
        # Check for inconsistent number formatting
        # This is a simplified check
        numbers = re.findall(r'₹?([\d,]+\.?\d*)', explanation)
        if numbers:
            # Check if large numbers lack comma separators
            for num in numbers:
                if len(num.replace(',', '').replace('.', '')) > 4 and ',' not in num:
                    issues.append(f"Large number {num} lacks comma separators")
                    break
        
        return issues
    
    def _check_unsupported_claims(
        self,
        explanation: str,
        result: dict[str, Any] | None
    ) -> list[str]:
        """Check for claims not supported by data."""
        warnings = []
        explanation_lower = explanation.lower()
        
        # Causal language patterns
        causal_patterns = [
            'caused',
            'because of',
            'led to',
            'resulted in',
            'driving',
            'responsible for',
        ]
        
        for pattern in causal_patterns:
            if pattern in explanation_lower:
                warnings.append(
                    f"Contains causal language ('{pattern}') that may not be supported by correlation data"
                )
        
        # Superlative business claims
        unsupported_patterns = [
            'best',
            'worst',
            'optimal',
            'ideal',
            'perfect',
            'should',
            'must',
        ]
        
        for pattern in unsupported_patterns:
            if pattern in explanation_lower:
                # Check if it's just describing data vs making recommendations
                context = re.findall(rf'\b\w+\s+{pattern}\s+\w+\b', explanation_lower)
                if any('we should' in c or 'you should' in c for c in context):
                    warnings.append(
                        f"Contains prescriptive language ('{pattern}') beyond data description"
                    )
        
        return warnings
    
    def _check_visualization_relevance(
        self,
        question: str,
        visualizations: list[dict],
        result: dict[str, Any]
    ) -> list[str]:
        """Check if visualizations are relevant to the question."""
        warnings = []
        question_lower = question.lower()
        
        for viz in visualizations:
            chart_type = viz.get('chart_type', '').lower()
            
            # Check if chart type matches question intent
            if 'trend' in question_lower or 'over time' in question_lower:
                if chart_type not in ['line', 'timeline']:
                    warnings.append(
                        f"Trend question but using {chart_type} chart instead of line chart"
                    )
            
            elif any(kw in question_lower for kw in ['top', 'highest', 'best']):
                if chart_type not in ['bar', 'horizontal_bar']:
                    warnings.append(
                        f"Ranking question but using {chart_type} chart instead of bar chart"
                    )
            
            elif 'distribution' in question_lower or 'proportion' in question_lower:
                if chart_type not in ['pie', 'donut']:
                    warnings.append(
                        f"Distribution question but using {chart_type} chart"
                    )
        
        return warnings
    
    def filter_response_fields(
        self,
        question: str,
        columns: list[str],
        rows: list[dict[str, Any]]
    ) -> tuple[list[str], list[dict[str, Any]]]:
        """
        Filter result columns to include only those relevant to answering the question.
        
        Returns: (filtered_columns, filtered_rows)
        """
        question_lower = question.lower()
        
        # Always exclude these unless explicitly requested
        always_exclude = {'created_at', 'updated_at', 'deleted_at'}
        
        # Conditionally exclude IDs
        id_columns = {col for col in columns if col.lower().endswith('_id') or col.lower() == 'id'}
        
        # Check if user explicitly asked for IDs
        id_requested = any(kw in question_lower for kw in ['id', 'identifier', 'key'])
        
        if not id_requested:
            always_exclude.update(id_columns)
        
        # Filter columns
        filtered_columns = [col for col in columns if col not in always_exclude]
        
        # If we filtered everything, keep at least name and primary metric
        if not filtered_columns and columns:
            # Keep first 2-3 most relevant columns
            filtered_columns = columns[:min(3, len(columns))]
        
        # Filter rows
        filtered_rows = []
        for row in rows:
            filtered_row = {k: v for k, v in row.items() if k in filtered_columns}
            filtered_rows.append(filtered_row)
        
        return filtered_columns, filtered_rows
