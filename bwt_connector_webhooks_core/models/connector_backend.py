"""Reference-selection used by the inbound/outbound endpoint extensions to
enumerate the connector backends that own webhook endpoints.

Backends opt in by inheriting one of the side mixins
(``bwt.connector.webhook.inbound.mixin`` or
``bwt.connector.webhook.outbound.mixin``); both side mixins extend
:class:`bwt.connector.webhook.backend.base`, which sets the class
marker :attr:`_is_connector_webhook_backend = True`.
"""

from odoo import api, models


class ConnectorBackend(models.AbstractModel):
    _inherit = "connector.backend"

    @api.model
    def _selection_connector_webhook_backend_models(self):
        """Return ``[(model_name, label), ...]`` for opted-in connector backends."""
        selection = []
        for model_name in sorted(self.env):
            if model_name == "connector.backend":
                continue
            model = self.env[model_name]
            if model._abstract:
                continue
            if not getattr(model, "_is_connector_webhook_backend", False):
                continue
            selection.append((model_name, model._description or model_name))
        return selection
