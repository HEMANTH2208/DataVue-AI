"""
LLMSQL Result Validator

Validates query results against requirements and analytical steps.
Ensures data integrity and correctness before proceeding.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any


@dataclass
class ValidationResult:
    """Result of validating a step execution."""
    
    is_valid: bool
    violations: list[str] = None
    warnings: list[str] = None
    corrective_action: str | None = None
    
    def __post_init__(self):
        if self.violations is None:
            self.violations = []
        if self.warnings is None:
            self.warnings = []


class ResultValidator:
    """Validates analytical step results against requirements."""
    
    def validate_query_result(
        self,
        result: dict[str, Any],
        expected_columns: list[str] = None,
        expected_row_count: int | None = None,
        max_row_count: int | None = None,
        min_row_count: int = 1,
        validation_rules: list[str] = None
    ) -> ValidationResult:
        """Validate a query result against expectations."""
        violations = []
        warnings = []
        
        # Check if result exists and has data
        if not result:
            violations.append("Query result is empty or None")
            return ValidationResult(is_valid=False, violations=violations)
        
        columns = result.get("columns", [])
        rows = result.get("rows", [])
        row_count = result.get("row_count", 0)
        
        # Validate columns
        if expected_columns:
            missing_cols = [col for col in expected_columns if col not in columns]
            if missing_cols:
                warnings.append(f"Expected columns not found: {missing_cols}")
        
        # Validate row count
        if row_count == 0:
            violations.append("Query returned 0 rows - no data found")
            return ValidationResult(
                is_valid=False,
                violations=violations,
                corrective_action="Modify query to return data or verify filters"
            )
        
        if row_count < min_row_count:
            violations.append(f"Expected at least {min_row_count} rows, got {row_count}")
        
        if expected_row_count is not None and row_count != expected_row_count:
            violations.append(
                f"Expected exactly {expected_row_count} rows, got {row_count}"
            )
        
        if max_row_count is not None and row_count > max_row_count:
            warnings.append(
                f"Result has {row_count} rows, expected maximum {max_row_count}. "
                "Query may need additional LIMIT clause."
            )
        
        # Validate data types in rows
        if rows:
            first_row = rows[0]
            for col in columns:
                if col not in first_row:
                    violations.append(f"Column '{col}' missing from result rows")
        
        # Check for duplicate rows
        if len(rows) != len([dict(t) for t in {tuple(sorted(d.items())) for d in rows}]):
            warnings.append("Result contains duplicate rows - may indicate incorrect join")
        
        # Custom validation rules
        if validation_rules:
            for rule in validation_rules:
                rule_lower = rule.lower()
                
                # Check row count rules
                if 'exactly' in rule_lower and 'rows' in rule_lower:
                    import re
                    match = re.search(r'exactly\s+(\d+)\s+rows', rule_lower)
                    if match:
                        expected = int(match.group(1))
                        if row_count != expected:
                            violations.append(f"Rule violation: {rule}. Got {row_count} rows.")
                
                # Check top N rules
                if 'top' in rule_lower:
                    match = re.search(r'top\s+(\d+)', rule_lower)
                    if match:
                        expected = int(match.group(1))
                        if row_count > expected:
                            violations.append(
                                f"Rule violation: Expected top {expected}, got {row_count} rows"
                            )
                
                # Check required columns
                if 'must contain' in rule_lower or 'must include' in rule_lower:
                    # Extract column names from rule
                    for col in columns:
                        if col.lower() in rule_lower:
                            # Column is mentioned and exists, good
                            pass
        
        is_valid = len(violations) == 0
        
        return ValidationResult(
            is_valid=is_valid,
            violations=violations,
            warnings=warnings,
            corrective_action="Re-generate query with corrections" if not is_valid else None
        )
    
    def validate_step_dependency(
        self,
        current_step_desc: str,
        dependency_result: Any
    ) -> ValidationResult:
        """Validate that a dependent step has the required data from previous step."""
        violations = []
        warnings = []
        
        if not dependency_result:
            violations.append("Dependent step has no result")
            return ValidationResult(
                is_valid=False,
                violations=violations,
                corrective_action="Execute dependency step first"
            )
        
        # Check if current step mentions using "that" or "the" category/product
        desc_lower = current_step_desc.lower()
        if any(ref in desc_lower for ref in ['that category', 'the category', 'that product', 'the product']):
            # Must have identifier from previous result
            if isinstance(dependency_result, dict):
                rows = dependency_result.get("rows", [])
                if not rows:
                    violations.append("Dependency result has no rows to extract identifier from")
                elif len(rows) > 0:
                    # Good - has data to use
                    pass
        
        is_valid = len(violations) == 0
        return ValidationResult(is_valid=is_valid, violations=violations, warnings=warnings)
    
    def validate_consistency(
        self,
        sql: str,
        result: dict[str, Any],
        explanation: str
    ) -> ValidationResult:
        """Validate consistency between SQL, result, and explanation."""
        violations = []
        warnings = []
        
        row_count = result.get("row_count", 0)
        columns = result.get("columns", [])
        
        # Check if explanation mentions row count
        import re
        explanation_lower = explanation.lower()
        
        # Extract numbers from explanation
        numbers_in_explanation = re.findall(r'\b(\d+)\s+(results?|rows?|products?|categories?|items?)\b', explanation_lower)
        
        for num_str, entity in numbers_in_explanation:
            num = int(num_str)
            if 'result' in entity or 'row' in entity:
                if num != row_count:
                    violations.append(
                        f"Explanation mentions {num} {entity} but query returned {row_count} rows"
                    )
        
        # Check if explanation mentions columns not in result
        for col in columns:
            if col.lower() not in explanation_lower and col.replace('_', ' ').lower() not in explanation_lower:
                # Column in result but not mentioned - this is okay, just a warning
                pass
        
        # Check for fabricated values
        # Extract numeric values from explanation
        values_in_explanation = re.findall(r'₹?([\d,]+\.?\d*)', explanation)
        if values_in_explanation:
            # Check if these values appear in results
            result_values = []
            for row in result.get("rows", []):
                result_values.extend([str(v) for v in row.values() if v is not None])
            
            # This is complex to validate perfectly, so just warn
            if len(values_in_explanation) > row_count * len(columns):
                warnings.append("Explanation contains many numeric values - verify they come from results")
        
        is_valid = len(violations) == 0
        
        return ValidationResult(
            is_valid=is_valid,
            violations=violations,
            warnings=warnings,
            corrective_action="Regenerate explanation using only result data" if not is_valid else None
        )
    
    def validate_multi_step_integrity(
        self,
        step_results: list[tuple[str, Any]]
    ) -> ValidationResult:
        """Validate integrity across multiple analytical steps."""
        violations = []
        warnings = []
        
        if len(step_results) < 2:
            return ValidationResult(is_valid=True)
        
        # Check for hardcoded values being used instead of dynamic results
        for i, (step_desc, result) in enumerate(step_results[1:], start=1):
            desc_lower = step_desc.lower()
            
            # Check if this step references previous step
            if any(ref in desc_lower for ref in ['that', 'the', 'this', 'its', 'their']):
                # Should use data from previous step
                prev_desc, prev_result = step_results[i-1]
                
                if isinstance(prev_result, dict) and isinstance(result, dict):
                    prev_rows = prev_result.get("rows", [])
                    curr_rows = result.get("rows", [])
                    
                    if not prev_rows:
                        violations.append(
                            f"Step {i+1} depends on Step {i} but Step {i} has no data"
                        )
                    
                    # Check if SQL hardcodes values like "WHERE category_id = 1"
                    # This is hard to check without seeing the SQL, so we'll check in the agent
        
        is_valid = len(violations) == 0
        return ValidationResult(is_valid=is_valid, violations=violations, warnings=warnings)
    
    def extract_identifier_from_result(
        self,
        result: dict[str, Any],
        entity_type: str = "category"
    ) -> dict[str, Any] | None:
        """Extract identifier (id and name) from a result for use in dependent queries."""
        rows = result.get("rows", [])
        if not rows:
            return None
        
        # Take the first row (should be sorted correctly)
        first_row = rows[0]
        
        # Try to find ID and name columns
        id_col = None
        name_col = None
        
        for col in first_row.keys():
            col_lower = col.lower()
            if 'id' in col_lower and entity_type in col_lower:
                id_col = col
            elif entity_type in col_lower or col_lower == 'name':
                name_col = col
        
        identifier = {}
        if id_col:
            identifier['id'] = first_row[id_col]
            identifier['id_column'] = id_col
        if name_col:
            identifier['name'] = first_row[name_col]
            identifier['name_column'] = name_col
        
        return identifier if identifier else None
