"""
Unit tests for sqlparse token-based SQL guardrails.
Verifies that SELECT queries pass and mutating/dangerous statements are blocked.
"""

import unittest
from src.database.guardrails import validate_sql


class TestSQLGuardrails(unittest.TestCase):

    def test_valid_select_query(self):
        sql = "SELECT name, price FROM products WHERE price > 50"
        result = validate_sql(sql)
        self.assertTrue(result.is_safe)
        self.assertIn("LIMIT 1000", result.query)

    def test_valid_join_query(self):
        sql = """
        SELECT c.name, SUM(o.total_amount) as rev
        FROM customers c
        JOIN orders o ON c.customer_id = o.customer_id
        GROUP BY c.name
        ORDER BY rev DESC
        """
        result = validate_sql(sql)
        self.assertTrue(result.is_safe)

    def test_blocked_drop_table(self):
        sql = "DROP TABLE orders"
        result = validate_sql(sql)
        self.assertFalse(result.is_safe)
        self.assertIn("Blocked operation", result.violation)

    def test_blocked_delete(self):
        sql = "DELETE FROM customers WHERE customer_id = 1"
        result = validate_sql(sql)
        self.assertFalse(result.is_safe)

    def test_blocked_insert(self):
        sql = "INSERT INTO categories (name) VALUES ('Test')"
        result = validate_sql(sql)
        self.assertFalse(result.is_safe)

    def test_blocked_update(self):
        sql = "UPDATE products SET price = 0"
        result = validate_sql(sql)
        self.assertFalse(result.is_safe)

    def test_blocked_multi_statement(self):
        sql = "SELECT * FROM products; DROP TABLE products;"
        result = validate_sql(sql)
        self.assertFalse(result.is_safe)
        self.assertIn("Multi-statement", result.violation)

    def test_existing_limit_preserved(self):
        sql = "SELECT * FROM products LIMIT 5"
        result = validate_sql(sql)
        self.assertTrue(result.is_safe)
        self.assertIn("LIMIT 5", result.query)


if __name__ == "__main__":
    unittest.main()
