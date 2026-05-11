from odoo import api, fields, models
from odoo.exceptions import ValidationError

WEBHOOK_SEMANTIC_SELECTION = [
    ("topic", "Topic"),
    ("event_type", "Event Type"),
    ("event_id", "Business Event Identity"),
    ("delivery_id", "Delivery Identity"),
    ("notification_id", "Notification ID"),
    ("idempotency_key", "Explicit Idempotency Key"),
    ("signature", "Signature"),
    ("signature_timestamp", "Signature Timestamp"),
    ("occurred_at", "Occurred At"),
    ("tenant_key", "Tenant / Shop / Account"),
    ("version", "Version"),
    ("resource_reference", "Resource Reference"),
    ("handler_selector", "Handler Selector"),
]
WEBHOOK_SEMANTIC_NAMES = tuple(name for name, _label in WEBHOOK_SEMANTIC_SELECTION)


class WebhookInboundEndpointSemanticBinding(models.Model):
    _name = "bwt.webhook.inbound.endpoint.semantic.binding"
    _description = "Webhook Endpoint Semantic Binding"
    _order = "semantic_name, id"
    _check_company_auto = True

    _sql_constraints = [
        (
            "endpoint_semantic_uniq",
            "unique(endpoint_id, semantic_name)",
            "Each semantic can be bound only once per endpoint.",
        ),
    ]

    endpoint_id = fields.Many2one(
        "bwt.webhook.inbound.endpoint",
        required=True,
        ondelete="cascade",
        index=True,
        check_company=True,
    )
    company_id = fields.Many2one(
        "res.company",
        related="endpoint_id.company_id",
        store=True,
        readonly=True,
        index=True,
    )
    semantic_name = fields.Selection(selection=WEBHOOK_SEMANTIC_SELECTION, required=True, index=True)
    value_key = fields.Char(
        required=True,
        index=True,
        string="Resolved Key",
        help="Resolved key produced by the Value Resolution rules that should feed this built-in semantic.",
    )
    note = fields.Char()

    @api.constrains("value_key")
    def _check_value_key(self):
        for binding in self:
            if not (binding.value_key or "").strip():
                raise ValidationError(self.env._("Semantic bindings require a resolved key."))

    @api.model
    def _normalize_vals(self, vals):
        normalized_vals = dict(vals)
        value_key = normalized_vals.get("value_key")
        if value_key is not None:
            normalized_vals["value_key"] = value_key.strip()
        return normalized_vals

    @api.model_create_multi
    def create(self, vals_list):
        vals_list = [self._normalize_vals(vals) for vals in vals_list]
        records = super().create(vals_list)
        records._check_value_key()
        return records

    def write(self, vals):
        result = super().write(self._normalize_vals(vals))
        self._check_value_key()
        return result
