from odoo import api, fields, models
from odoo.exceptions import ValidationError

from odoo.addons.bwt_webhooks_core.models.const import INBOUND_SOURCE_KIND_SELECTION


class WebhookInboundHandlerRuleLookup(models.Model):
    _name = "bwt.webhook.inbound.handler.rule.lookup"
    _description = "Webhook Handler Inbound Rule Lookup"
    _order = "sequence, id"
    _check_company_auto = True

    rule_id = fields.Many2one(
        "bwt.webhook.inbound.handler.rule",
        required=True,
        ondelete="cascade",
        index=True,
        check_company=True,
    )
    company_id = fields.Many2one(
        "res.company",
        related="rule_id.company_id",
        store=True,
        readonly=True,
        index=True,
    )
    sequence = fields.Integer(required=True, default=10)
    target_field_name = fields.Char(required=True, string="Target Field")
    source_kind = fields.Selection(selection=INBOUND_SOURCE_KIND_SELECTION, required=True, default="resolved_value")
    source_expression = fields.Char(string="Source Key")
    literal_value = fields.Char()

    @api.constrains("source_kind", "source_expression")
    def _check_lookup_configuration(self):
        for lookup in self:
            if lookup.source_kind != "literal" and not lookup.source_expression:
                raise ValidationError(self.env._("Lookup rows require Source Key unless the source kind is Literal."))
