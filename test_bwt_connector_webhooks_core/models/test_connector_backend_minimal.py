"""Minimal in-test connector backend used by core test cases.

The model inherits the private abstract base directly so the base
behaviors (scoping, code normalization, validation, super-chain
anchors) can be exercised without pulling in either side mixin addon.
"""

from odoo import api, fields, models


class TestConnectorBackendMinimal(models.Model):
    _name = "bwt.test.connector.webhook.backend.minimal"
    _inherit = [
        "connector.backend",
        "bwt.connector.webhook.backend.base",
    ]
    _description = "Test Connector Webhook Backend (Minimal)"

    name = fields.Char(required=True)
    code = fields.Char(required=True)
    description = fields.Char()
    active = fields.Boolean(default=True)
    company_id = fields.Many2one("res.company", required=True, default=lambda self: self.env.company)

    @api.constrains("code")
    def _check_webhook_backend_configuration(self):
        self._validate_webhook_backend_configuration()


class TestConnectorBackendMinimalNoCompany(models.Model):
    """Minimal backend without ``company_id`` to exercise the no-scope branch."""

    _name = "bwt.test.connector.webhook.backend.minimal.no.company"
    _inherit = [
        "connector.backend",
        "bwt.connector.webhook.backend.base",
    ]
    _description = "Test Connector Webhook Backend (Minimal, No Company)"

    name = fields.Char(required=True)
    code = fields.Char(required=True)
    active = fields.Boolean(default=True)

    @api.constrains("code")
    def _check_webhook_backend_configuration(self):
        self._validate_webhook_backend_configuration()
