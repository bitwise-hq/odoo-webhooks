from odoo import fields, models

from .const import INBOUND_RULE_CONDITION_OPERATOR_SELECTION, INBOUND_SOURCE_KIND_SELECTION


class WebhookHandlerInboundRuleCondition(models.Model):
    _name = 'webhook.handler.inbound.rule.condition'
    _description = 'Webhook Handler Inbound Rule Condition'
    _order = 'sequence, id'
    _check_company_auto = True

    rule_id = fields.Many2one('webhook.handler.inbound.rule', required=True, ondelete='cascade', index=True, check_company=True)
    company_id = fields.Many2one('res.company', related='rule_id.company_id', store=True, readonly=True, index=True)
    sequence = fields.Integer(required=True, default=10)
    source_kind = fields.Selection(selection=INBOUND_SOURCE_KIND_SELECTION, required=True, default='semantic_field')
    source_expression = fields.Char(required=True, string='Source Key')
    operator = fields.Selection(selection=INBOUND_RULE_CONDITION_OPERATOR_SELECTION, required=True, default='equals')
    expected_value = fields.Char()