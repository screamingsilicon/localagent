"""Tests for highlighters/sql.py."""

from __future__ import annotations

import re
import unittest

from .sql import highlight, diff_highlight


def _strip_ansi(s: str) -> str:
    return re.sub(r"\033\[[0-9;]*m", "", s)


class TestSqlHighlight(unittest.TestCase):
    """Basic SQL highlighting tests."""

    def test_empty_input(self):
        result = highlight("")
        self.assertEqual(result, "")

    def test_simple_select(self):
        sql = "SELECT * FROM users"
        result = highlight(sql)
        plain = _strip_ansi(result)
        self.assertEqual(plain, sql)

    def test_plain_text_passthrough(self):
        sql = "SELECT name, age FROM users WHERE id = 1\n"
        result = highlight(sql)
        self.assertEqual(_strip_ansi(result), sql)

    def test_select_with_where(self):
        sql = """SELECT name, email
FROM users
WHERE active = true
ORDER BY created_at DESC"""
        result = highlight(sql)
        plain = _strip_ansi(result)
        self.assertIn("name", plain)
        self.assertIn("email", plain)
        self.assertIn("users", plain)

    def test_select_with_join(self):
        sql = """SELECT u.name, o.total
FROM users u
INNER JOIN orders o ON u.id = o.user_id
WHERE o.total > 100"""
        result = highlight(sql)
        plain = _strip_ansi(result)
        self.assertIn("users", plain)
        self.assertIn("orders", plain)

    def test_insert(self):
        sql = "INSERT INTO users (name, email) VALUES ('Alice', 'alice@example.com')"
        result = highlight(sql)
        plain = _strip_ansi(result)
        self.assertEqual(plain, sql)

    def test_update(self):
        sql = "UPDATE users SET active = false WHERE id = 42"
        result = highlight(sql)
        plain = _strip_ansi(result)
        self.assertIn("users", plain)
        self.assertIn("active", plain)
        self.assertIn("false", plain)

    def test_delete(self):
        sql = "DELETE FROM sessions WHERE expired_at < NOW()"
        result = highlight(sql)
        plain = _strip_ansi(result)
        self.assertIn("sessions", plain)

    def test_create_table(self):
        sql = """CREATE TABLE users (
    id INTEGER PRIMARY KEY AUTO_INCREMENT,
    name VARCHAR(255) NOT NULL,
    email VARCHAR(255) UNIQUE,
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
)"""
        result = highlight(sql)
        plain = _strip_ansi(result)
        self.assertIn("users", plain)
        self.assertIn("INTEGER", plain)
        self.assertIn("VARCHAR", plain)

    def test_drop_table(self):
        sql = "DROP TABLE IF EXISTS temp_data"
        result = highlight(sql)
        plain = _strip_ansi(result)
        self.assertEqual(plain, sql)

    def test_alter_table(self):
        sql = "ALTER TABLE users ADD COLUMN phone VARCHAR(20)"
        result = highlight(sql)
        plain = _strip_ansi(result)
        self.assertIn("users", plain)
        self.assertIn("phone", plain)

    def test_single_quoted_string(self):
        sql = "SELECT * FROM users WHERE name = 'Alice'"
        result = highlight(sql)
        plain = _strip_ansi(result)
        self.assertIn("Alice", plain)

    def test_double_quoted_string(self):
        sql = 'SELECT * FROM users WHERE name = "Bob"'
        result = highlight(sql)
        plain = _strip_ansi(result)
        self.assertIn("Bob", plain)

    def test_escaped_string(self):
        sql = r"SELECT * FROM users WHERE name = 'O\'Brien'"
        result = highlight(sql)
        plain = _strip_ansi(result)
        self.assertIn("O", plain)
        self.assertIn("Brien", plain)

    def test_numbers_integer(self):
        sql = "SELECT * FROM products WHERE price > 100"
        result = highlight(sql)
        plain = _strip_ansi(result)
        self.assertIn("100", plain)

    def test_numbers_float(self):
        sql = "SELECT * FROM products WHERE tax_rate = 0.0825"
        result = highlight(sql)
        plain = _strip_ansi(result)
        self.assertIn("0.0825", plain)

    def test_negative_number(self):
        sql = "SELECT * FROM accounts WHERE balance < -1000"
        result = highlight(sql)
        plain = _strip_ansi(result)
        self.assertIn("-1000", plain)

    def test_line_comment(self):
        sql = "-- Get all active users\nSELECT * FROM users WHERE active = true"
        result = highlight(sql)
        plain = _strip_ansi(result)
        self.assertIn("active users", plain)

    def test_block_comment(self):
        sql = "/* User query */ SELECT * FROM users"
        result = highlight(sql)
        plain = _strip_ansi(result)
        self.assertIn("User query", plain)

    def test_inline_comment(self):
        sql = "SELECT name -- username\nFROM users"
        result = highlight(sql)
        plain = _strip_ansi(result)
        self.assertIn("username", plain)

    def test_aggregate_functions(self):
        sql = "SELECT COUNT(*), SUM(amount), AVG(price) FROM orders"
        result = highlight(sql)
        plain = _strip_ansi(result)
        self.assertIn("COUNT", plain)
        self.assertIn("SUM", plain)
        self.assertIn("AVG", plain)

    def test_case_when(self):
        sql = """SELECT name,
CASE WHEN age >= 18 THEN 'adult' ELSE 'minor' END AS category
FROM users"""
        result = highlight(sql)
        plain = _strip_ansi(result)
        self.assertIn("adult", plain)
        self.assertIn("minor", plain)

    def test_case_insensitive_keywords(self):
        sql = "select * from users where id = 1"
        result = highlight(sql)
        # Should be colored (keywords matched case-insensitively)
        self.assertNotEqual(result, _strip_ansi(result))

    def test_mixed_case_keywords(self):
        sql = "SeLeCt * FrOm users WhErE id = 1"
        result = highlight(sql)
        self.assertNotEqual(result, _strip_ansi(result))

    def test_null_value(self):
        sql = "SELECT * FROM users WHERE email IS NULL"
        result = highlight(sql)
        self.assertIn("NULL", _strip_ansi(result))

    def test_true_false(self):
        sql = "SELECT * FROM users WHERE active = true AND deleted = false"
        result = highlight(sql)
        plain = _strip_ansi(result)
        self.assertIn("true", plain)
        self.assertIn("false", plain)

    def test_between(self):
        sql = "SELECT * FROM orders WHERE amount BETWEEN 10 AND 100"
        result = highlight(sql)
        plain = _strip_ansi(result)
        self.assertEqual(plain, sql)

    def test_like_pattern(self):
        sql = "SELECT * FROM users WHERE name LIKE '%smith%'"
        result = highlight(sql)
        plain = _strip_ansi(result)
        self.assertIn("smith", plain)

    def test_in_clause(self):
        sql = "SELECT * FROM users WHERE role IN ('admin', 'editor')"
        result = highlight(sql)
        plain = _strip_ansi(result)
        self.assertIn("admin", plain)

    def test_subquery(self):
        sql = """SELECT name FROM users
WHERE id IN (SELECT user_id FROM orders WHERE total > 100)"""
        result = highlight(sql)
        plain = _strip_ansi(result)
        self.assertIn("orders", plain)

    def test_cte_with_recursive(self):
        sql = """WITH RECURSIVE tree AS (
    SELECT id, parent_id, name FROM categories WHERE parent_id IS NULL
    UNION ALL
    SELECT c.id, c.parent_id, c.name FROM categories c JOIN tree t ON c.parent_id = t.id
)
SELECT * FROM tree"""
        result = highlight(sql)
        plain = _strip_ansi(result)
        self.assertIn("categories", plain)

    def test_group_by_having(self):
        sql = """SELECT department, COUNT(*) as cnt
FROM employees
GROUP BY department
HAVING COUNT(*) > 5
ORDER BY cnt DESC"""
        result = highlight(sql)
        plain = _strip_ansi(result)
        self.assertIn("department", plain)
        self.assertIn("employees", plain)

    def test_limit_offset(self):
        sql = "SELECT * FROM products ORDER BY price LIMIT 10 OFFSET 20"
        result = highlight(sql)
        plain = _strip_ansi(result)
        self.assertEqual(plain, sql)

    def test_union(self):
        sql = "SELECT name FROM users UNION SELECT name FROM admins"
        result = highlight(sql)
        plain = _strip_ansi(result)
        self.assertIn("users", plain)
        self.assertIn("admins", plain)

    def test_transaction_statements(self):
        sql = "BEGIN; UPDATE accounts SET balance = balance - 100 WHERE id = 1; COMMIT;"
        result = highlight(sql)
        plain = _strip_ansi(result)
        self.assertIn("BEGIN", plain)
        self.assertIn("COMMIT", plain)

    def test_operators(self):
        sql = "SELECT * FROM users WHERE age >= 18 AND status <> 'banned'"
        result = highlight(sql)
        plain = _strip_ansi(result)
        self.assertEqual(plain, sql)

    def test_arithmetic_in_select(self):
        sql = "SELECT price * quantity AS total FROM order_items"
        result = highlight(sql)
        plain = _strip_ansi(result)
        self.assertIn("total", plain)

    def test_colors_are_injected(self):
        """Ensure that highlighting actually adds ANSI codes."""
        sql = "SELECT name, COUNT(*) FROM users WHERE active = true GROUP BY name"
        result = highlight(sql)
        self.assertNotEqual(result, _strip_ansi(result))

    def test_whitespace_preserved(self):
        sql = "  SELECT  *   FROM   users  \n"
        result = highlight(sql)
        plain = _strip_ansi(result)
        self.assertEqual(plain, sql)


class TestSqlDiff(unittest.TestCase):
    """Diff highlighting for SQL."""

    def test_simple_diff(self):
        old_src = "SELECT * FROM users\n"
        new_src = "SELECT * FROM customers\n"
        result = diff_highlight(old_src, new_src)
        self.assertIn("SELECT", _strip_ansi(result))

    def test_add_where_clause(self):
        old_src = "SELECT * FROM users\n"
        new_src = "SELECT * FROM users WHERE active = true\n"
        result = diff_highlight(old_src, new_src)
        self.assertIn("WHERE", _strip_ansi(result))

    def test_remove_column(self):
        old_src = "SELECT name, email, phone FROM users\n"
        new_src = "SELECT name, email FROM users\n"
        result = diff_highlight(old_src, new_src)
        stripped = _strip_ansi(result)
        self.assertIn("-", stripped)

    def test_identical_sources(self):
        src = "SELECT * FROM users WHERE id = 1"
        result = diff_highlight(src, src)
        self.assertIsInstance(result, str)

    def test_multiline_diff(self):
        old_src = """SELECT name, email
FROM users
WHERE id = 1"""
        new_src = """SELECT name, email, phone
FROM users
WHERE id = 2"""
        result = diff_highlight(old_src, new_src)
        self.assertIn("phone", _strip_ansi(result))


class TestSqlEdgeCases(unittest.TestCase):
    """Edge cases and malformed input."""

    def test_malformed_sql_no_crash(self):
        """Malformed SQL should not crash the highlighter."""
        result = highlight("SELECT * FROM")
        self.assertIsInstance(result, str)

    def test_unclosed_string(self):
        result = highlight("SELECT * FROM users WHERE name = 'Alice")
        self.assertIsInstance(result, str)

    def test_empty_query(self):
        result = highlight(";")
        self.assertIsInstance(result, str)

    def test_just_a_comment(self):
        result = highlight("-- this is just a comment")
        plain = _strip_ansi(result)
        self.assertIn("comment", plain)

    def test_unicode_in_string(self):
        sql = "SELECT * FROM users WHERE name = '日本語'"
        result = highlight(sql)
        plain = _strip_ansi(result)
        self.assertIn("日本語", plain)

    def test_schema_qualified_table(self):
        sql = "SELECT * FROM public.users"
        result = highlight(sql)
        plain = _strip_ansi(result)
        self.assertEqual(plain, sql)

    def test_alias_with_as(self):
        sql = "SELECT u.name AS username FROM users AS u"
        result = highlight(sql)
        plain = _strip_ansi(result)
        self.assertIn("username", plain)

    def test_multiple_semicolons(self):
        sql = "SELECT 1; SELECT 2; SELECT 3;"
        result = highlight(sql)
        plain = _strip_ansi(result)
        self.assertEqual(plain, sql)

    def test_parenthesized_expression(self):
        sql = "SELECT * FROM users WHERE (age > 18 AND active = true) OR admin = true"
        result = highlight(sql)
        plain = _strip_ansi(result)
        self.assertEqual(plain, sql)


class TestSqlShowTrailing(unittest.TestCase):
    """Test trailing whitespace visualization."""

    def test_trailing_spaces_visualized(self):
        result = highlight("SELECT * FROM users   \n", show_trailing=True)
        self.assertIn("\033[1;31m", result)

    def test_trailing_tabs_visualized(self):
        result = highlight("SELECT name\t\nFROM users\n", show_trailing=True)
        self.assertIn("\033[1;31m", result)

    def test_no_trailing_no_markers(self):
        result = highlight("SELECT * FROM users\n", show_trailing=True)
        self.assertNotIn("\u00b7", _strip_ansi(result))


if __name__ == "__main__":
    unittest.main()
