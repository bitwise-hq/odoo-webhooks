"""Outbound-only in-test connector backend.

Used by callback dispatch, request-data merge, queueing, and
action-view tests. Tests are responsible for creating the outbound
endpoint records they need and linking them via
``connector_backend_ref``.
"""

from odoo import api, fields, models


class TestConnectorBackendOutbound(models.Model):
    _name = "bwt.test.connector.webhook.backend.outbound"
    _inherit = [
        "connector.backend",
        "bwt.connector.webhook.outbound.mixin",
    ]
    _description = "Test Connector Webhook Backend (Outbound)"

    name = fields.Char(required=True)
    code = fields.Char(required=True)
    active = fields.Boolean(default=True)
    company_id = fields.Many2one("res.company", required=True, default=lambda self: self.env.company)

    @api.constrains("code")
    def _check_webhook_backend_configuration(self):
        self._validate_webhook_backend_configuration()


class TestConnectorBackendOutboundBare(models.Model):
    """Outbound mixin with no overrides.

    Used to exercise default abstract behaviors without contributing
    any custom delivery handling.
    """

    _name = "bwt.test.connector.webhook.backend.outbound.bare"
    _inherit = [
        "connector.backend",
        "bwt.connector.webhook.outbound.mixin",
    ]
    _description = "Test Connector Webhook Backend (Outbound Bare)"

    name = fields.Char(required=True)
    code = fields.Char(required=True)
    active = fields.Boolean(default=True)
    company_id = fields.Many2one("res.company", required=True, default=lambda self: self.env.company)

    @api.constrains("code")
    def _check_webhook_backend_configuration(self):
        self._validate_webhook_backend_configuration()


class TestConnectorBackendOutboundHooked(models.Model):
    """Outbound mixin with header-provider hooks wired up.

    Exercises the default ``_handle_outbound_webhook_delivery``
    orchestration by contributing extra headers (auth +
    per-delivery idempotency key) and an optional dispatch-gate
    switch.
    """

    _name = "bwt.test.connector.webhook.backend.outbound.hooked"
    _inherit = [
        "connector.backend",
        "bwt.connector.webhook.outbound.mixin",
    ]
    _description = "Test Connector Webhook Backend (Outbound Hooked)"

    name = fields.Char(required=True)
    code = fields.Char(required=True)
    active = fields.Boolean(default=True)
    company_id = fields.Many2one("res.company", required=True, default=lambda self: self.env.company)
    dispatch_blocked = fields.Boolean(default=False)

    @api.constrains("code")
    def _check_webhook_backend_configuration(self):
        self._validate_webhook_backend_configuration()

    def _check_outbound_dispatch_allowed(self, delivery):
        self.ensure_one()
        if self.dispatch_blocked:
            from odoo.addons.bwt_connector_webhooks_core.services.result_types import (
                webhook_dead_letter,
            )

            return webhook_dead_letter("blocked by test")
        return None

    def _get_outbound_extra_headers(self, delivery):
        self.ensure_one()
        headers = {"Authorization": "Bearer test-token"}
        try:
            context_values = delivery._get_context_values()
        except Exception:  # pylint: disable=broad-except
            context_values = {}
        idempotency_key = context_values.get("idempotency_key")
        if idempotency_key:
            headers["Idempotency-Key"] = idempotency_key
        return headers


class TestConnectorBackendOutboundBinding(models.Model):
    """A simple binding-style record carrying ``backend_id``.

    Used by tests that exercise binding resolution against a record
    whose ``backend_id`` may not match the resolving backend.
    """

    _name = "bwt.test.connector.webhook.outbound.binding"
    _description = "Test Connector Webhook Outbound Binding"

    name = fields.Char(required=True)
    backend_id = fields.Reference(
        selection=[
            ("bwt.test.connector.webhook.backend.outbound", "Outbound Backend"),
            (
                "bwt.test.connector.webhook.backend.outbound.bare",
                "Outbound Bare Backend",
            ),
        ]
    )
