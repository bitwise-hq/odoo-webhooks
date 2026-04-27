from odoo import api, fields, models
from odoo.exceptions import ValidationError

from odoo.addons.bwt_webhooks_core.models.const import OUTBOUND_CONTEXT_SOURCE_SELECTION


class WebhookOutboundDeliveryContextLine(models.Model):
    _name = "bwt.webhook.outbound.delivery.context.line"
    _description = "Webhook Outbound Delivery Context Line"
    _order = "sequence, id"
    _check_company_auto = True

    delivery_id = fields.Many2one(
        "bwt.webhook.outbound.delivery",
        required=True,
        ondelete="cascade",
        index=True,
        check_company=True,
    )
    company_id = fields.Many2one(
        "res.company",
        related="delivery_id.company_id",
        store=True,
        readonly=True,
        index=True,
    )
    sequence = fields.Integer(required=True, default=10)
    active = fields.Boolean(default=True)
    key_name = fields.Char(required=True, string="Context Key")
    source_kind = fields.Selection(selection=OUTBOUND_CONTEXT_SOURCE_SELECTION, required=True, default="literal")
    source_expression = fields.Char(string="Source Key")
    literal_value = fields.Text()

    @api.constrains("source_kind", "source_expression")
    def _check_context_line_configuration(self):
        for line in self:
            if line.source_kind != "literal" and not line.source_expression:
                raise ValidationError(self.env._("Context lines require Source Key unless the source kind is Literal."))
