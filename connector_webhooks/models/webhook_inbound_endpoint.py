from odoo import api, fields, models
from odoo.exceptions import ValidationError


class WebhookInboundEndpoint(models.Model):
    _inherit = "webhook.inbound.endpoint"

    _connector_backend_ref_uniq = models.Constraint(
        "unique(connector_backend_ref)",
        "A connector backend can only be linked to one inbound webhook endpoint.",
    )

    connector_backend_ref = fields.Reference(
        selection=lambda self: self.env[
            "connector.backend"
        ]._selection_connector_backend_models(),
        string="Connector Backend",
        copy=False,
        help="Optional connector backend record that owns this inbound webhook endpoint.",
    )

    @api.constrains("connector_backend_ref", "company_id")
    def _check_connector_backend_company(self):
        for endpoint in self:
            backend = endpoint.connector_backend_ref
            if not backend:
                continue
            backend_company = getattr(backend, "company_id", False)
            if backend_company and backend_company != endpoint.company_id:
                raise ValidationError(
                    self.env._(
                        "The linked connector backend company must match the inbound endpoint company."
                    )
                )
