from odoo import _, api, fields, models
from odoo.exceptions import ValidationError

from .const import OUTBOUND_ASSIGNMENT_TARGET_SCOPE_SELECTION, OUTBOUND_RULE_SOURCE_SELECTION


class WebhookHandlerOutboundAssignment(models.Model):
    _name = 'webhook.handler.outbound.assignment'
    _description = 'Webhook Handler Outbound Assignment'
    _order = 'sequence, id'
    _check_company_auto = True

    rule_id = fields.Many2one('webhook.handler.outbound.rule', required=True, ondelete='cascade', index=True, check_company=True)
    company_id = fields.Many2one('res.company', related='rule_id.company_id', store=True, readonly=True, index=True)
    sequence = fields.Integer(required=True, default=10)
    target_scope = fields.Selection(selection=OUTBOUND_ASSIGNMENT_TARGET_SCOPE_SELECTION, required=True, default='payload')
    target_expression = fields.Char(required=True, string='Target')
    source_kind = fields.Selection(selection=OUTBOUND_RULE_SOURCE_SELECTION, required=True, default='literal')
    source_expression = fields.Char(string='Source Key')
    literal_value = fields.Text()

    @api.constrains('source_kind', 'source_expression')
    def _check_assignment_configuration(self):
        for assignment in self:
            if assignment.source_kind != 'literal' and not assignment.source_expression:
                raise ValidationError(_('Outbound assignments require Source Key unless the source kind is Literal.'))