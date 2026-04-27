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
    target_model_name = fields.Char(string='Target Model')
    outbound_endpoint_id = fields.Many2one('webhook.outbound.endpoint', string='Outbound Endpoint', check_company=True)
    condition_ids = fields.One2many('webhook.handler.inbound.rule.condition', 'rule_id', string='Conditions')
    lookup_ids = fields.One2many('webhook.handler.inbound.rule.lookup', 'rule_id', string='Lookup Keys')
    assignment_ids = fields.One2many('webhook.handler.inbound.rule.assignment', 'rule_id', string='Assignments')
    execution_ids = fields.One2many('webhook.inbound.rule.execution', 'rule_id', string='Executions')
    configuration_warning = fields.Text(compute='_compute_configuration_warning')

    @api.depends('action_type', 'target_model_name', 'outbound_endpoint_id', 'assignment_ids', 'lookup_ids')
    def _compute_configuration_warning(self):
        for rule in self:
            messages = []
            if rule.action_type in ('create_record', 'update_record', 'upsert_record') and not rule.target_model_name:
                messages.append(_('Target Model is required for record-creation and record-update rules.'))
            if rule.action_type in ('update_record', 'upsert_record') and not rule.lookup_ids:
                messages.append(_('At least one Lookup Key is recommended for update and upsert rules.'))
            if rule.action_type == 'queue_outbound' and not rule.outbound_endpoint_id:
                messages.append(_('Outbound Endpoint is required for queue-outbound rules.'))
            if rule.action_type in ('create_record', 'update_record', 'upsert_record', 'queue_outbound') and not rule.assignment_ids:
                messages.append(_('This rule has no Assignments yet. It will not produce a useful payload or record update.'))
            rule.configuration_warning = '\n'.join(messages) or False

    @api.constrains('action_type', 'retry_seconds', 'target_model_name', 'outbound_endpoint_id')
    def _check_rule_configuration(self):
        for rule in self:
            if rule.action_type == 'retry' and rule.retry_seconds < 0:
                raise ValidationError(_('Retry delay must be zero or greater.'))
            if rule.action_type in ('create_record', 'update_record', 'upsert_record') and not rule.target_model_name:
                raise ValidationError(_('Target Model is required for record-creation and record-update rules.'))
            if rule.action_type == 'queue_outbound' and not rule.outbound_endpoint_id:
                raise ValidationError(_('Outbound Endpoint is required for queue-outbound rules.'))