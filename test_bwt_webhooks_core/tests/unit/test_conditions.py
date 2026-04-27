"""Unit tests for :mod:`bwt_webhooks_core.services.conditions`.

Test suites in this module:

* :class:`TestDecodeLiteralValue` — JSON-aware literal coercion used by
  rule conditions.
* :class:`TestEvaluateCondition` — operator dispatch table that powers
  inbound and outbound rule matching.
"""

from .common import WebhookServiceTestCase

from odoo.addons.bwt_webhooks_core.services.conditions import (
    UnsupportedOperator,
    decode_literal_value,
    evaluate_condition,
)


class TestDecodeLiteralValue(WebhookServiceTestCase):
    """``decode_literal_value`` coerces stored literals into Python values."""

    def test_blank_inputs_pass_through(self):
        for value in (False, None, ""):
            self.assertEqual(decode_literal_value(value), value)

    def test_non_string_pass_through(self):
        self.assertEqual(decode_literal_value(7), 7)
        self.assertEqual(decode_literal_value([1]), [1])

    def test_valid_json_decoded(self):
        self.assertEqual(decode_literal_value('{"a": 1}'), {"a": 1})
        self.assertEqual(decode_literal_value("true"), True)
        self.assertEqual(decode_literal_value("42"), 42)

    def test_invalid_json_returned_as_string(self):
        self.assertEqual(decode_literal_value("not json"), "not json")


class TestEvaluateCondition(WebhookServiceTestCase):
    """``evaluate_condition`` dispatches operators against literal values."""

    def test_is_set_truthy_values(self):
        self.assertTrue(evaluate_condition("x", "is_set", None))
        self.assertTrue(evaluate_condition("0", "is_set", None))
        # Note: 0 == False in Python, so it's treated as blank by design.
        self.assertFalse(evaluate_condition(False, "is_set", None))
        self.assertFalse(evaluate_condition("", "is_set", None))
        self.assertFalse(evaluate_condition(None, "is_set", None))

    def test_not_set_blank_values(self):
        self.assertTrue(evaluate_condition(False, "not_set", None))
        self.assertTrue(evaluate_condition("", "not_set", None))
        self.assertFalse(evaluate_condition("x", "not_set", None))

    def test_equals_compares_text(self):
        self.assertTrue(evaluate_condition(7, "equals", "7"))
        self.assertTrue(evaluate_condition(False, "equals", ""))
        self.assertFalse(evaluate_condition("x", "equals", "y"))

    def test_not_equals(self):
        self.assertTrue(evaluate_condition("x", "not_equals", "y"))
        self.assertFalse(evaluate_condition("x", "not_equals", "x"))

    def test_contains(self):
        self.assertTrue(evaluate_condition("xyz", "contains", "y"))
        self.assertFalse(evaluate_condition("xyz", "contains", "Q"))

    def test_unsupported_operator_raises(self):
        with self.assertRaises(UnsupportedOperator) as ctx:
            evaluate_condition("x", "regex", "y")
        self.assertEqual(ctx.exception.operator, "regex")
