"""
LLMSQL Question Analyzer

Deeply analyzes user questions to extract:
- Intent and objectives
- Entities and metrics
- Filters and constraints
- Multi-step dependencies
- Required analytical operations
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any
import re


@dataclass
class QuestionAnalysis:
    """Structured analysis of a user question."""
    
    # Core intent
    primary_objective: str = ""
    question_type: str = ""  # single_query, multi_step, comparison, ranking, trend
    
    # Entities and metrics
    entities: list[str] = field(default_factory=list)  # products, customers, orders
    metrics: list[str] = field(default_factory=list)  # revenue, count, average
    dimensions: list[str] = field(default_factory=list)  # category, month, region
    
    # Operations
    filters: list[dict[str, Any]] = field(default_factory=list)
    grouping: list[str] = field(default_factory=list)
    sorting: list[dict[str, str]] = field(default_factory=list)  # [{field, direction}]
    ranking_required: bool = False
    top_n: int | None = None
    bottom_n: int | None = False
    
    # Comparisons and time
    comparisons: list[str] = field(default_factory=list)
    time_period: str | None = None
    time_comparison: bool = False
    
    # Multi-step analysis
    is_multi_step: bool = False
    analytical_steps: list[str] = field(default_factory=list)
    step_dependencies: list[tuple[int, int]] = field(default_factory=list)  # (step_idx, depends_on_idx)
    
    # Visualization hint
    suggested_viz: str | None = None  # bar, line, pie, scatter, table, er, flowchart
    
    # Original question
    original_question: str = ""
    
    # Contract: what must the answer contain?
    requirements: list[str] = field(default_factory=list)


class QuestionAnalyzer:
    """Analyzes natural language questions to extract structured intent."""
    
    # Keywords for different analytical operations
    RANKING_KEYWORDS = {'top', 'best', 'highest', 'most', 'leading', 'bottom', 'worst', 'lowest', 'least'}
    COMPARISON_KEYWORDS = {'compare', 'vs', 'versus', 'difference', 'between', 'against'}
    TREND_KEYWORDS = {'trend', 'over time', 'monthly', 'weekly', 'daily', 'growth', 'timeline', 'change'}
    AGGREGATION_KEYWORDS = {'total', 'sum', 'count', 'average', 'avg', 'mean', 'median', 'max', 'min'}
    FILTER_KEYWORDS = {'where', 'with', 'having', 'only', 'excluding', 'including', 'for'}
    
    # Multi-step indicators
    MULTI_STEP_PATTERNS = [
        r'\band\b.*\b(what|which|show|list)',  # "and what are"
        r',\s*(then|and then|after that)',  # "then show"
        r'(first|second|third|finally)',  # explicit step markers
    ]
    
    # Metric patterns
    REVENUE_PATTERNS = r'revenue|sales|earnings|income|receipts'
    COUNT_PATTERNS = r'\bcount|number of|how many|total (orders|products|customers)'
    AVERAGE_PATTERNS = r'average|avg|mean|typical'
    
    def analyze(self, question: str) -> QuestionAnalysis:
        """Analyze a user question and return structured analysis."""
        analysis = QuestionAnalysis(original_question=question)
        question_lower = question.lower()
        
        # Detect question type
        analysis.is_multi_step = self._is_multi_step(question_lower)
        analysis.question_type = self._classify_question_type(question_lower, analysis.is_multi_step)
        
        # Extract core components
        analysis.entities = self._extract_entities(question_lower)
        analysis.metrics = self._extract_metrics(question_lower)
        analysis.dimensions = self._extract_dimensions(question_lower)
        
        # Extract operations
        analysis.ranking_required = self._detect_ranking(question_lower)
        analysis.top_n = self._extract_top_n(question_lower)
        analysis.bottom_n = self._extract_bottom_n(question_lower)
        analysis.sorting = self._extract_sorting(question_lower, analysis.metrics)
        
        # Time analysis
        analysis.time_period = self._extract_time_period(question_lower)
        analysis.time_comparison = self._detect_time_comparison(question_lower)
        
        # Multi-step decomposition
        if analysis.is_multi_step:
            self._decompose_multi_step(question, question_lower, analysis)
        else:
            analysis.analytical_steps = [question]
            analysis.requirements = [f"Answer: {question}"]
        
        # Visualization suggestion
        analysis.suggested_viz = self._suggest_visualization(question_lower, analysis)
        
        # Build requirements contract
        self._build_requirements(analysis)
        
        return analysis
    
    def _is_multi_step(self, question_lower: str) -> bool:
        """Detect if question requires multiple analytical steps."""
        # Check for explicit multi-step patterns
        for pattern in self.MULTI_STEP_PATTERNS:
            if re.search(pattern, question_lower):
                return True
        
        # Check for nested questions (multiple question words)
        question_words = ['what', 'which', 'who', 'how many', 'show', 'list', 'find']
        count = sum(1 for word in question_words if word in question_lower)
        if count > 1:
            return True
        
        return False
    
    def _classify_question_type(self, question_lower: str, is_multi: bool) -> str:
        """Classify the type of question."""
        if is_multi:
            return "multi_step"
        elif any(kw in question_lower for kw in self.TREND_KEYWORDS):
            return "trend"
        elif any(kw in question_lower for kw in self.RANKING_KEYWORDS):
            return "ranking"
        elif any(kw in question_lower for kw in self.COMPARISON_KEYWORDS):
            return "comparison"
        else:
            return "single_query"
    
    def _extract_entities(self, question_lower: str) -> list[str]:
        """Extract database entities mentioned in the question."""
        entities = []
        entity_keywords = {
            'product': ['product', 'products', 'item', 'items'],
            'category': ['category', 'categories'],
            'customer': ['customer', 'customers', 'buyer', 'buyers'],
            'order': ['order', 'orders', 'purchase', 'purchases'],
            'review': ['review', 'reviews', 'rating', 'ratings'],
        }
        
        for entity, keywords in entity_keywords.items():
            if any(kw in question_lower for kw in keywords):
                entities.append(entity)
        
        return entities
    
    def _extract_metrics(self, question_lower: str) -> list[str]:
        """Extract metrics being requested."""
        metrics = []
        
        if re.search(self.REVENUE_PATTERNS, question_lower):
            metrics.append('revenue')
        if re.search(self.COUNT_PATTERNS, question_lower):
            metrics.append('count')
        if re.search(self.AVERAGE_PATTERNS, question_lower):
            metrics.append('average')
        if 'quantity' in question_lower or 'qty' in question_lower:
            metrics.append('quantity')
        if 'price' in question_lower:
            metrics.append('price')
        
        return metrics
    
    def _extract_dimensions(self, question_lower: str) -> list[str]:
        """Extract dimensions for grouping/filtering."""
        dimensions = []
        
        dimension_keywords = {
            'category': ['by category', 'per category', 'each category'],
            'product': ['by product', 'per product', 'each product'],
            'month': ['by month', 'monthly', 'per month', 'each month'],
            'year': ['by year', 'yearly', 'per year'],
            'customer': ['by customer', 'per customer'],
            'payment_method': ['by payment', 'payment method'],
        }
        
        for dim, keywords in dimension_keywords.items():
            if any(kw in question_lower for kw in keywords):
                dimensions.append(dim)
        
        return dimensions
    
    def _detect_ranking(self, question_lower: str) -> bool:
        """Detect if ranking is required."""
        return any(kw in question_lower for kw in self.RANKING_KEYWORDS)
    
    def _extract_top_n(self, question_lower: str) -> int | None:
        """Extract top N limit if specified."""
        # Pattern: "top 5", "top 10", "best 3"
        match = re.search(r'\b(top|best|highest)\s+(\d+)\b', question_lower)
        if match:
            return int(match.group(2))
        
        # Pattern: "5 best", "3 top"
        match = re.search(r'\b(\d+)\s+(top|best|highest)\b', question_lower)
        if match:
            return int(match.group(1))
        
        return None
    
    def _extract_bottom_n(self, question_lower: str) -> int | None:
        """Extract bottom N limit if specified."""
        match = re.search(r'\b(bottom|worst|lowest)\s+(\d+)\b', question_lower)
        if match:
            return int(match.group(2))
        return None
    
    def _extract_sorting(self, question_lower: str, metrics: list[str]) -> list[dict[str, str]]:
        """Extract sorting requirements."""
        sorting = []
        
        if any(kw in question_lower for kw in ['highest', 'most', 'top', 'best', 'descending']):
            # Descending sort on primary metric
            if metrics:
                sorting.append({'field': metrics[0], 'direction': 'DESC'})
            else:
                sorting.append({'field': 'value', 'direction': 'DESC'})
        elif any(kw in question_lower for kw in ['lowest', 'least', 'bottom', 'worst', 'ascending']):
            if metrics:
                sorting.append({'field': metrics[0], 'direction': 'ASC'})
            else:
                sorting.append({'field': 'value', 'direction': 'ASC'})
        
        return sorting
    
    def _extract_time_period(self, question_lower: str) -> str | None:
        """Extract time period constraints."""
        if '2025' in question_lower:
            return '2025'
        elif '2024' in question_lower:
            return '2024'
        elif 'this year' in question_lower:
            return 'current_year'
        elif 'last year' in question_lower:
            return 'previous_year'
        elif 'this month' in question_lower:
            return 'current_month'
        elif 'last month' in question_lower:
            return 'previous_month'
        
        return None
    
    def _detect_time_comparison(self, question_lower: str) -> bool:
        """Detect if time-based comparison is needed."""
        return any(kw in question_lower for kw in [
            'growth', 'change', 'increase', 'decrease', 'compared to',
            'year-over-year', 'month-over-month', 'yoy', 'mom'
        ])
    
    def _decompose_multi_step(self, question: str, question_lower: str, analysis: QuestionAnalysis) -> None:
        """Decompose multi-step questions into individual steps."""
        # Example: "Which category has highest revenue, and what are top 3 products in that category?"
        
        # Split on common conjunctions
        parts = re.split(r',?\s+and\s+(?:what|which|show|list)', question, flags=re.IGNORECASE)
        
        if len(parts) > 1:
            # Multiple sub-questions detected
            analysis.analytical_steps = [parts[0]]
            analysis.requirements.append(f"Step 1: {parts[0]}")
            
            for i, part in enumerate(parts[1:], start=2):
                # Clean up the part
                part = part.strip().rstrip('?')
                if not part:
                    continue
                
                # Check if this step depends on previous
                if any(ref in part.lower() for ref in ['that', 'this', 'the', 'its', 'their']):
                    # Dependent step
                    analysis.step_dependencies.append((i-1, i-2))  # Current depends on previous
                    analysis.analytical_steps.append(f"Using result from Step {i-1}: {part}")
                    analysis.requirements.append(f"Step {i}: Use ACTUAL result from Step {i-1} to {part}")
                else:
                    analysis.analytical_steps.append(part)
                    analysis.requirements.append(f"Step {i}: {part}")
        else:
            # Single complex question - analyze for nested intent
            analysis.analytical_steps = [question]
            analysis.requirements.append(f"Answer: {question}")
    
    def _suggest_visualization(self, question_lower: str, analysis: QuestionAnalysis) -> str | None:
        """Suggest appropriate visualization based on question."""
        # ER diagram
        if any(kw in question_lower for kw in ['er diagram', 'entity relationship', 'database structure', 'schema diagram']):
            return 'er'
        
        # Flowchart
        if any(kw in question_lower for kw in ['flowchart', 'workflow', 'process', 'flow diagram']):
            return 'flowchart'
        
        # Data visualizations
        if analysis.question_type == 'trend' or any(kw in question_lower for kw in self.TREND_KEYWORDS):
            return 'line'
        elif analysis.ranking_required and analysis.top_n and analysis.top_n <= 10:
            return 'bar'
        elif 'distribution' in question_lower or 'proportion' in question_lower:
            return 'pie'
        elif 'correlation' in question_lower or ' vs ' in question_lower:
            return 'scatter'
        
        return 'bar'  # Default
    
    def _build_requirements(self, analysis: QuestionAnalysis) -> None:
        """Build a requirements contract for answer validation."""
        if not analysis.requirements:
            analysis.requirements = []
        
        # Add metric requirements
        for metric in analysis.metrics:
            analysis.requirements.append(f"Include {metric} values")
        
        # Add ranking requirements
        if analysis.top_n:
            analysis.requirements.append(f"Return exactly top {analysis.top_n} results")
        if analysis.bottom_n:
            analysis.requirements.append(f"Return exactly bottom {analysis.bottom_n} results")
        
        # Add entity requirements
        for entity in analysis.entities:
            analysis.requirements.append(f"Include {entity} information")
        
        # Add visualization requirement
        if analysis.suggested_viz:
            analysis.requirements.append(f"Generate {analysis.suggested_viz} visualization")
        
        # Add explanation requirement
        if analysis.question_type != 'flowchart' and analysis.suggested_viz != 'er':
            analysis.requirements.append("Provide clear explanation of findings")
