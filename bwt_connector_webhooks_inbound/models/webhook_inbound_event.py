"""Connector-aware override for ``bwt.webhook.inbound.event``.

Hooks into the framework's ``_invoke_inbound_dispatch`` extension
point so connector-linked endpoints can route processing directly
to the linked backend's ``_handle_inbound_webhook_event`` without
requiring a ``bwt.webhook.handler`` proxy row.
"""

from odoo import models, _

from odoo.addons.bwt_connector_webhooks_core.services.result_types import (
    webhook_dead_letter,
)


class WebhookInboundEvent(models.Model):
    _inherit = "bwt.webhook.inbound.event"

    def _invoke_inbound_dispatch(self):
        self.ensure_one()
        backend = self.endpoint_id.connector_backend_ref
        if not backend:
            return super()._invoke_inbound_dispatch()
        result = backend._handle_inbound_webhook_event(self)
        if result is None:
            return webhook_dead_letter(
                _(
                    "Connector backend %(name)s did not return a result for the inbound webhook event.",
                    name=backend.display_name,
                )
            )
        return result
