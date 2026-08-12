"""
Unit tests for chart type selection logic (select_chart_type).
Verifies that data shapes and query intents map to the correct Plotly chart types.
"""

import unittest
from src.tools.visualizer import select_chart_type, VisualizeDataTool


class TestVisualizerChartSelection(unittest.TestCase):

    def test_categorical_bar_chart(self):
        columns = ["category_name", "total_revenue"]
        rows = [
            {"category_name": f"Category {i}", "total_revenue": 1000 * i}
            for i in range(1, 6)
        ]
        chart_type = select_chart_type(columns, rows, query_intent="top 5 categories by revenue")
        self.assertEqual(chart_type, "bar")

    def test_horizontal_bar_chart(self):
        columns = ["product_name", "sales"]
        rows = [
            {"product_name": f"Product {i}", "sales": 50 * i}
            for i in range(1, 20)
        ]
        chart_type = select_chart_type(columns, rows)
        self.assertEqual(chart_type, "horizontal_bar")

    def test_time_series_line_chart(self):
        columns = ["order_date", "daily_orders"]
        rows = [
            {"order_date": f"2025-01-0{i}", "daily_orders": 10 + i}
            for i in range(1, 9)
        ]
        chart_type = select_chart_type(columns, rows, query_intent="monthly revenue trend")
        self.assertEqual(chart_type, "line")

    def test_proportion_pie_chart(self):
        columns = ["payment_method", "order_count"]
        rows = [
            {"payment_method": "Credit Card", "order_count": 500},
            {"payment_method": "PayPal", "order_count": 300},
            {"payment_method": "Apple Pay", "order_count": 200},
        ]
        chart_type = select_chart_type(columns, rows, query_intent="distribution of payment methods")
        self.assertEqual(chart_type, "pie")

    def test_scatter_chart(self):
        columns = ["price", "rating"]
        rows = [
            {"price": 10 + i, "rating": 3.0 + (i * 0.1)}
            for i in range(1, 10)
        ]
        chart_type = select_chart_type(columns, rows, query_intent="correlation between price and rating scatter")
        self.assertEqual(chart_type, "scatter")

    def test_tool_execution(self):
        tool = VisualizeDataTool()
        self.assertEqual(tool.name, "generate_chart")
        result = tool.execute(
            columns=["category", "sales"],
            rows=[{"category": "A", "sales": 100}, {"category": "B", "sales": 200}],
            query_intent="sales comparison",
        )
        self.assertTrue(result.success)
        self.assertIn("plotly_spec", result.data)


if __name__ == "__main__":
    unittest.main()
