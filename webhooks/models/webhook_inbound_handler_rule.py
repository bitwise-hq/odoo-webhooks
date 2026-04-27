from odoo import _, api, fields, models
from odoo.exceptions import ValidationError

from .const import INBOUND_ACTION_SELECTION


class WebhookHandlerInboundRule(models.Model):
    _name = 'webhook.handler.inbound.rule'
    _description = 'Webhook Handler Inbound Rule'
    _order = 'sequence, id'
    _check_company_auto = True

    name = fields.Char(required=True, default=lambda self: _('Inbound Rule'))
    sequence = fields.Integer(required=True, default=10)
    active = fields.Boolean(default=True)
    handler_id = fields.Many2one('webhook.handler', required=True, ondelete='cascade', index=True, check_company=True)
    company_id = fields.Many2one('res.company', related='handler_id.company_id', store=True, readonly=True, index=True)
    action_type = fields.Selection(selection=INBOUND_ACTION_SELECTION, required=True, default='done')
    note = fields.Text()
    retry_seconds = fields.Integer(default=0)
    target_model_name = fields.Char(
        string='Target Model',
        help='Technical model name used by create, update, and upsert actions.',
    )
    outbound_endpoint_id = fields.Many2one(
        'webhook.outbound.endpoint',
        string='Outbound Endpoint',
        check_company=True,
        help='Outbound endpoint used when this rule queues an outbound delivery.',
    )
    condition_ids = fields.One2many('webhook.handler.inbound.rule.condition', 'rule_id', string='Conditions')
    lookup_ids = fields.One2many(
        'webhook.handler.inbound.rule.lookup',
        'rule_id',
        string='Lookup Keys',
        help='Lookup keys identify the existing target record for update and upsert actions.',
    )
    assignment_ids = fields.One2many(
        'webhook.handler.inbound.rule.assignment',
        'rule_id',
        string='Assignments',
        help='Assignments define the values written to created or updated records, or to queued outbound payloads.',
    )
    execution_ids = fields.One2many('webhook.inbound.rule.execution', 'rule_id', string='Executions')

    @api.constrains('action_type', 'retry_seconds', 'target_model_name', 'outbound_endpoint_id')
    def _check_rule_configuration(self):
        for rule in self:
            if rule.action_type == 'retry' and rule.retry_seconds < 0:
                raise ValidationError(_('Retry delay must be zero or greater.'))
            if rule.action_type in ('create_record', 'update_record', 'upsert_record') and not rule.target_model_name:
                raise ValidationError(_('Target Model is required for record-creation and record-update rules.'))
            if rule.action_type == 'queue_outbound' and not rule.outbound_endpoint_id:
                raise ValidationError(_('Outbound Endpoint is required for queue-outbound rules.'))