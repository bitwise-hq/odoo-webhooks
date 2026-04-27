from odoo import _, api, fields, models
from odoo.exceptions import ValidationError

from .const import OUTBOUND_RULE_SOURCE_SELECTION


class WebhookOutboundEndpointHeaderRule(models.Model):
    _name = "webhook.outbound.endpoint.header.rule"
    _description = "Webhook Outbound Endpoint Header Rule"
    _order = "sequence, id"
    _check_company_auto = True

    endpoint_id = fields.Many2one(
        "webhook.outbound.endpoint",
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
    partner_id = fields.Many2one(
        "res.partner",
        related="endpoint_id.partner_id",
        store=True,
        readonly=True,
        index=True,
    )
    sequence = fields.Integer(required=True, default=10)
    active = fields.Boolean(default=True)
    header_name = fields.Char(required=True)
    source_kind = fields.Selection(
        selection=OUTBOUND_RULE_SOURCE_SELECTION, required=True, default="literal"
    )
    source_expression = fields.Char(string="Source Key")
    literal_value = fields.Text()

    @api.constrains("source_kind", "source_expression")
    def _check_header_rule_configuration(self):
        for rule in self:
            if rule.source_kind != "literal" and not rule.source_expression:
                raise ValidationError(
                    _(
                        "Header rules require Source Key unless the source kind is Literal."
                    )
                )
