from odoo import fields, models

from .webhook_outbound_rule_common import OUTBOUND_RULE_CONDITION_OPERATOR_SELECTION, OUTBOUND_RULE_SOURCE_SELECTION


class WebhookHandlerOutboundRuleCondition(models.Model):
    _name = 'webhook.handler.outbound.rule.condition'
    _description = 'Webhook Handler Outbound Rule Condition'
    _order = 'sequence, id'
    _check_company_auto = True

    rule_id = fields.Many2one('webhook.handler.outbound.rule', required=True, ondelete='cascade', index=True, check_company=True)
    company_id = fields.Many2one('res.company', related='rule_id.company_id', store=True, readonly=True, index=True)
    sequence = fields.Integer(required=True, default=10)
    source_kind = fields.Selection(selection=OUTBOUND_RULE_SOURCE_SELECTION, required=True, default='delivery_field')
    source_expression = fields.Char(required=True, string='Source Key')
    operator = fields.Selection(selection=OUTBOUND_RULE_CONDITION_OPERATOR_SELECTION, required=True, default='equals')
    expected_value = fields.Char()