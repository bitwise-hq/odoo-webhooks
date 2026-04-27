"""Inbound side mixin for connector backends.

Extends :class:`bwt.connector.webhook.backend.base` with the
per-backend dispatch hook called by the connector-aware
``bwt.webhook.inbound.event._invoke_inbound_dispatch`` override.

A concrete connector backend opts in by listing both
``connector.backend`` and ``bwt.connector.webhook.inbound.mixin`` in its
``_inherit`` (and additionally ``bwt.connector.webhook.outbound.mixin``
when it also delivers outbound webhooks).

Endpoint records are seeded as XML data by the concrete connector
addon (e.g. ``bwt_stripe_core``); this mixin does not create or update
``bwt.webhook.inbound.endpoint`` rows.
"""

from odoo import fields, models
from odoo.exceptions import ValidationError


class ConnectorWebhookInboundMixin(models.AbstractModel):
    _name = "bwt.connector.webhook.inbound.mixin"
    _inherit = "bwt.connector.webhook.backend.base"
    _description = "Connector Webhook Inbound Mixin"

    webhook_endpoint_id = fields.Many2one(
        "bwt.webhook.inbound.endpoint",
        string="Inbound Endpoint",
        compute="_compute_webhook_endpoint_id",
        readonly=True,
    )

    def _compute_webhook_endpoint_id(self):
        endpoint_model = self.env["bwt.webhook.inbound.endpoint"]
        for backend in self:
            ref = backend._get_connector_backend_reference()
            if not ref:
                backend.webhook_endpoint_id = endpoint_model
                continue
            backend.webhook_endpoint_id = endpoint_model.search(
                [("connector_backend_ref", "=", ref)],
                limit=1,
            )

    # ==================================================================
    # Dispatch hook (called by the connector-aware event override)
    # ==================================================================
    def _handle_inbound_webhook_event(self, event):  # noqa: ARG002
        """Per-backend inbound processing hook (override in consuming addons).

        Concrete backends return one of ``webhook_done()`` /
        ``webhook_dead_letter()`` / ``webhook_retry()`` /
        ``webhook_cancel()`` from
        :mod:`bwt_connector_webhooks_core.services.result_types`.

        A ``None`` return is upgraded to a dead-letter by the
        connector-aware
        :meth:`bwt.webhook.inbound.event._invoke_inbound_dispatch`
        override, so the default no-op behavior of this hook produces
        a deterministic framework-level dead letter.
        """
        self.ensure_one()
        return None

    # ==================================================================
    # Action
    # ==================================================================
    def action_view_inbound_endpoint(self):
        self.ensure_one()
        endpoint = self.webhook_endpoint_id
        if not endpoint:
            raise ValidationError(self.env._("No inbound webhook endpoint is linked to this backend."))
        action = self.env.ref("bwt_webhooks_inbound.action_webhook_endpoint").read()[0]
        action.update(
            {
                "res_id": endpoint.id,
                "view_mode": "form",
                "views": [
                    (
                        self.env.ref("bwt_webhooks_inbound.view_webhook_endpoint_form").id,
                        "form",
                    )
                ],
            }
        )
        return action
