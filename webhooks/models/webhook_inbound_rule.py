from odoo import _, api, fields, models
from odoo.exceptions import ValidationError


INBOUND_ACTION_SELECTION = [
    ('done', 'Mark Done'),
    ('dead_letter', 'Dead Letter'),
    ('retry', 'Retry'),
    ('create_record', 'Create Record'),
    ('update_record', 'Update Record'),
    ('upsert_record', 'Upsert Record'),
    ('queue_outbound', 'Queue Outbound'),
]

INBOUND_SOURCE_KIND_SELECTION = [
    ('resolved_value', 'Resolved Value'),
    ('semantic_field', 'Semantic Field'),
    ('event_field', 'Event Field'),
    ('literal', 'Literal'),
]

RULE_CONDITION_OPERATOR_SELECTION = [
    ('equals', 'Equals'),
    ('not_equals', 'Does Not Equal'),
    ('is_set', 'Is Set'),
    ('not_set', 'Is Not Set'),
    ('contains', 'Contains'),
]


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
    operator = fields.Selection(selection=RULE_CONDITION_OPERATOR_SELECTION, required=True, default='equals')
    expected_value = fields.Char()


class WebhookHandlerInboundRuleLookup(models.Model):
    _name = 'webhook.handler.inbound.rule.lookup'
    _description = 'Webhook Handler Inbound Rule Lookup'
    _order = 'sequence, id'
    _check_company_auto = True

    rule_id = fields.Many2one('webhook.handler.inbound.rule', required=True, ondelete='cascade', index=True, check_company=True)
    company_id = fields.Many2one('res.company', related='rule_id.company_id', store=True, readonly=True, index=True)
    sequence = fields.Integer(required=True, default=10)
    target_field_name = fields.Char(required=True, string='Target Field')
    source_kind = fields.Selection(selection=INBOUND_SOURCE_KIND_SELECTION, required=True, default='resolved_value')
    source_expression = fields.Char(string='Source Key')
    literal_value = fields.Char()

    @api.constrains('source_kind', 'source_expression')
    def _check_lookup_configuration(self):
        for lookup in self:
            if lookup.source_kind != 'literal' and not lookup.source_expression:
                raise ValidationError(_('Lookup rows require Source Key unless the source kind is Literal.'))


class WebhookHandlerInboundRuleAssignment(models.Model):
    _name = 'webhook.handler.inbound.rule.assignment'
    _description = 'Webhook Handler Inbound Rule Assignment'
    _order = 'sequence, id'
    _check_company_auto = True

    rule_id = fields.Many2one('webhook.handler.inbound.rule', required=True, ondelete='cascade', index=True, check_company=True)
    company_id = fields.Many2one('res.company', related='rule_id.company_id', store=True, readonly=True, index=True)
    sequence = fields.Integer(required=True, default=10)
    target_kind = fields.Selection(
        selection=[
            ('field', 'Record Field'),
            ('context_key', 'Outbound Context Key'),
        ],
        required=True,
        default='field',
    )
    target_expression = fields.Char(required=True, string='Target')
    source_kind = fields.Selection(selection=INBOUND_SOURCE_KIND_SELECTION, required=True, default='resolved_value')
    source_expression = fields.Char(string='Source Key')
    literal_value = fields.Text()

    @api.constrains('source_kind', 'source_expression')
    def _check_assignment_configuration(self):
        for assignment in self:
            if assignment.source_kind != 'literal' and not assignment.source_expression:
                raise ValidationError(_('Assignment rows require Source Key unless the source kind is Literal.'))


class WebhookInboundRuleExecution(models.Model):
    _name = 'webhook.inbound.rule.execution'
    _description = 'Webhook Inbound Rule Execution'
    _order = 'create_date desc, id desc'
    _check_company_auto = True

    name = fields.Char(required=True, default=lambda self: _('Inbound Rule Execution'))
    event_id = fields.Many2one('webhook.inbound.event', required=True, ondelete='cascade', index=True, check_company=True)
    rule_id = fields.Many2one('webhook.handler.inbound.rule', ondelete='set null', index=True, check_company=True)
    company_id = fields.Many2one('res.company', related='event_id.company_id', store=True, readonly=True, index=True)
    partner_id = fields.Many2one('res.partner', related='event_id.partner_id', store=True, readonly=True, index=True)
    state = fields.Selection(
        selection=[
            ('matched', 'Matched'),
            ('done', 'Done'),
            ('error', 'Error'),
            ('skipped', 'Skipped'),
        ],
        required=True,
        default='matched',
        index=True,
    )
    note = fields.Text()
    error = fields.Text()
    record_reference = fields.Char()