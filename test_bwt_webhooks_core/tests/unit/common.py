"""Tagged base class for pure-Python service unit tests.

Odoo's test runner filters by tag; ``odoo.tests.BaseCase`` has no
default tags and would be silently skipped. The tags applied here
match what :class:`odoo.tests.TransactionCase` ships with so the
tests run as part of the standard install/upgrade test suite.
"""

from odoo.tests import BaseCase, tagged


@tagged("standard", "at_install")
class WebhookServiceTestCase(BaseCase):
    """Pure-Python unit test base — no DB or ORM setup."""
