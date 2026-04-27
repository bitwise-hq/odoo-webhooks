"""Base test case for webhooks framework tests.

:class:`WebhookTestCase` instantiates a :class:`WebhookFactory` for each
test and resolves a few common record references. Subclass it whenever
a test needs framework records; tests that don't can still inherit from
``odoo.tests.common.TransactionCase`` directly.

Tests should follow these conventions:

* one observable behavior per test method, named
  ``test_<state>_<action>_<expected>``;
* layout each test as Arrange / Act / Assert blocks separated by a
  blank line;
* use ``self.factory`` for fixtures, override the few fields that
  matter, and inline anything truly specific to the test;
* keep one test class per System-Under-Test (model method, controller,
  service) with a class docstring describing the surface under test.
"""

from odoo.tests.common import TransactionCase

from .factories import WebhookFactory


class WebhookTestCase(TransactionCase):
    """Base class wiring a :class:`WebhookFactory` into ``self.factory``."""

    def setUp(self):
        super().setUp()
        self.factory = WebhookFactory(self.env)
