from odoo import api, fields, models
from odoo.exceptions import ValidationError

from odoo.addons.bwt_webhooks_core.models.const import OUTBOUND_RULE_STATUS_SELECTION


class WebhookOutboundHandlerRule(models.Model):
    _name = "bwt.webhook.outbound.handler.rule"
    _description = "Webhook Handler Outbound Rule"
    _order = "sequence, id"
    _check_company_auto = True

    name = fields.Char(required=True, default=lambda self: self.env._("Outbound Rule"))
    sequence = fields.Integer(required=True, default=10)
    active = fields.Boolean(default=True)
    handler_id = fields.Many2one(
        "bwt.webhook.handler",
        required=True,
        ondelete="cascade",
        index=True,
        check_company=True,
    )
    company_id = fields.Many2one(
        "res.company",
        related="handler_id.company_id",
        store=True,
        readonly=True,
        index=True,
    )
    result_status = fields.Selection(selection=OUTBOUND_RULE_STATUS_SELECTION, required=True, default="send")
    note = fields.Text()
    retry_seconds = fields.Integer(default=0)
    condition_ids = fields.One2many("bwt.webhook.outbound.handler.rule.condition", "rule_id", string="Conditions")
    assignment_ids = fields.One2many("bwt.webhook.outbound.handler.rule.assignment", "rule_id", string="Assignments")

    @api.constrains("result_status", "retry_seconds")
    def _check_outbound_rule_configuration(self):
        for rule in self:
            if rule.result_status == "retry" and rule.retry_seconds < 0:
                raise ValidationError(self.env._("Retry delay must be zero or greater."))
