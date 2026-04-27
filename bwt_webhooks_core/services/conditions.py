"""Pure condition and literal-value helpers used by both rule engines.

The ORM models still own rule iteration (recordsets) and action
execution (record creation, queueing). What lives here is the
operator evaluation table and the JSON literal decoder, both of which
are pure and shared between inbound and outbound rule engines.
"""

import json
from typing import Any


class UnsupportedOperator(Exception):
    """Raised when a rule references an operator we do not implement."""

    def __init__(self, operator: str):
        super().__init__(operator)
        self.operator = operator


def decode_literal_value(value: Any) -> Any:
    """Decode a stored literal: JSON-loaded if possible, else as-is.

    ``False``, ``None`` and empty strings round-trip unchanged so the
    callers' truthiness checks keep working.
    """
    if value in (False, None, "") or not isinstance(value, str):
        return value
    try:
        return json.loads(value)
    except json.JSONDecodeError:
        return value


def evaluate_condition(actual_value: Any, operator: str, expected_value: Any) -> bool:
    """Apply ``operator`` to ``(actual_value, expected_value)``.

    Supported operators: ``is_set``, ``not_set``, ``equals``,
    ``not_equals``, ``contains``. Raises :class:`UnsupportedOperator`
    for anything else so the caller can localize the error message.
    """
    if operator == "is_set":
        return actual_value not in (False, None, "")
    if operator == "not_set":
        return actual_value in (False, None, "")
    actual_text = "" if actual_value in (False, None) else str(actual_value)
    expected_text = expected_value or ""
    if operator == "equals":
        return actual_text == expected_text
    if operator == "not_equals":
        return actual_text != expected_text
    if operator == "contains":
        return expected_text in actual_text
    raise UnsupportedOperator(operator)
