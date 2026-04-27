"""Inbound-only in-test connector backend.

Inherits the inbound mixin and a default ``_handle_inbound_webhook_event``
that returns a deterministic ``done`` result so callback dispatch tests
can verify routing.
"""

from odoo import api, fields, models


class TestConnectorBackendInbound(models.Model):
    _name = "bwt.test.connector.webhook.backend.inbound"
    _inherit = [
        "connector.backend",
        "bwt.connector.webhook.inbound.mixin",
    ]
    _description = "Test Connector Webhook Backend (Inbound)"

    name = fields.Char(required=True)
    code = fields.Char(required=True)
    active = fields.Boolean(default=True)
    company_id = fields.Many2one("res.company", required=True, default=lambda self: self.env.company)

    @api.constrains("code")
    def _check_webhook_backend_configuration(self):
        self._validate_webhook_backend_configuration()

    def _handle_inbound_webhook_event(self, event):
        self.ensure_one()
        return {"status": "done", "note": f"handled {event.id}"}


class TestConnectorBackendInboundBare(models.Model):
    """Inbound mixin with no overrides.

    Used to exercise default abstract behaviors (default
    ``_handle_inbound_webhook_event`` dead-letter).
    """

    _name = "bwt.test.connector.webhook.backend.inbound.bare"
    _inherit = [
        "connector.backend",
        "bwt.connector.webhook.inbound.mixin",
    ]
    _description = "Test Connector Webhook Backend (Inbound Bare)"

    name = fields.Char(required=True)
    code = fields.Char(required=True)
    active = fields.Boolean(default=True)
    company_id = fields.Many2one("res.company", required=True, default=lambda self: self.env.company)

    @api.constrains("code")
    def _check_webhook_backend_configuration(self):
        self._validate_webhook_backend_configuration()
