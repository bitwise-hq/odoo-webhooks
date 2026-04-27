from odoo import _, api, fields, models
from odoo.exceptions import ValidationError


OUTBOUND_RULE_STATUS_SELECTION = [
    ('send', 'Send'),
    ('cancel', 'Cancel'),
    ('dead_letter', 'Dead Letter'),
    ('retry', 'Retry'),
]

OUTBOUND_RULE_SOURCE_SELECTION = [
    ('literal', 'Literal'),
    ('delivery_field', 'Delivery Field'),
    ('endpoint_field', 'Endpoint Field'),
    ('company_field', 'Company Field'),
    ('partner_field', 'Partner Field'),
    ('context_key', 'Context Key'),
    ('request_field', 'Request Field'),
]

OUTBOUND_CONTEXT_SOURCE_SELECTION = [
    ('literal', 'Literal'),
    ('delivery_field', 'Delivery Field'),
    ('endpoint_field', 'Endpoint Field'),
    ('company_field', 'Company Field'),
    ('partner_field', 'Partner Field'),
]

RULE_CONDITION_OPERATOR_SELECTION = [
    ('equals', 'Equals'),
    ('not_equals', 'Does Not Equal'),
    ('is_set', 'Is Set'),
    ('not_set', 'Is Not Set'),
    ('contains', 'Contains'),
]


class WebhookOutboundEndpointHeaderRule(models.Model):
    _name = 'webhook.outbound.endpoint.header.rule'
    _description = 'Webhook Outbound Endpoint Header Rule'
    _order = 'sequence, id'
    _check_company_auto = True

    endpoint_id = fields.Many2one('webhook.outbound.endpoint', required=True, ondelete='cascade', index=True, check_company=True)
    company_id = fields.Many2one('res.company', related='endpoint_id.company_id', store=True, readonly=True, index=True)
    partner_id = fields.Many2one('res.partner', related='endpoint_id.partner_id', store=True, readonly=True, index=True)
    sequence = fields.Integer(required=True, default=10)
    active = fields.Boolean(default=True)
    header_name = fields.Char(required=True)
    source_kind = fields.Selection(selection=OUTBOUND_RULE_SOURCE_SELECTION, required=True, default='literal')
    source_expression = fields.Char(string='Source Key')
    literal_value = fields.Text()

    @api.constrains('source_kind', 'source_expression')
    def _check_header_rule_configuration(self):
        for rule in self:
            if rule.source_kind != 'literal' and not rule.source_expression:
                raise ValidationError(_('Header rules require Source Key unless the source kind is Literal.'))


class WebhookOutboundEndpointPayloadRule(models.Model):
    _name = 'webhook.outbound.endpoint.payload.rule'
    _description = 'Webhook Outbound Endpoint Payload Rule'
    _order = 'sequence, id'
    _check_company_auto = True

    endpoint_id = fields.Many2one('webhook.outbound.endpoint', required=True, ondelete='cascade', index=True, check_company=True)
    company_id = fields.Many2one('res.company', related='endpoint_id.company_id', store=True, readonly=True, index=True)
    partner_id = fields.Many2one('res.partner', related='endpoint_id.partner_id', store=True, readonly=True, index=True)
    sequence = fields.Integer(required=True, default=10)
    active = fields.Boolean(default=True)
    target_path = fields.Char(required=True)
    source_kind = fields.Selection(selection=OUTBOUND_RULE_SOURCE_SELECTION, required=True, default='literal')
    source_expression = fields.Char(string='Source Key')
    literal_value = fields.Text()

    @api.constrains('source_kind', 'source_expression')
    def _check_payload_rule_configuration(self):
        for rule in self:
            if rule.source_kind != 'literal' and not rule.source_expression:
                raise ValidationError(_('Payload rules require Source Key unless the source kind is Literal.'))


class WebhookOutboundDeliveryContextLine(models.Model):
    _name = 'webhook.outbound.delivery.context.line'
    _description = 'Webhook Outbound Delivery Context Line'
    _order = 'sequence, id'
    _check_company_auto = True

    delivery_id = fields.Many2one('webhook.outbound.delivery', required=True, ondelete='cascade', index=True, check_company=True)
    company_id = fields.Many2one('res.company', related='delivery_id.company_id', store=True, readonly=True, index=True)
    partner_id = fields.Many2one('res.partner', related='delivery_id.partner_id', store=True, readonly=True, index=True)
    sequence = fields.Integer(required=True, default=10)
    active = fields.Boolean(default=True)
    key_name = fields.Char(required=True, string='Context Key')
    source_kind = fields.Selection(selection=OUTBOUND_CONTEXT_SOURCE_SELECTION, required=True, default='literal')
    source_expression = fields.Char(string='Source Key')
    literal_value = fields.Text()

    @api.constrains('source_kind', 'source_expression')
    def _check_context_line_configuration(self):
        for line in self:
            if line.source_kind != 'literal' and not line.source_expression:
                raise ValidationError(_('Context lines require Source Key unless the source kind is Literal.'))


class WebhookHandlerOutboundRule(models.Model):
    _name = 'webhook.handler.outbound.rule'
    _description = 'Webhook Handler Outbound Rule'
    _order = 'sequence, id'
    _check_company_auto = True

    name = fields.Char(required=True, default=lambda self: _('Outbound Rule'))
    sequence = fields.Integer(required=True, default=10)
    active = fields.Boolean(default=True)
    handler_id = fields.Many2one('webhook.handler', required=True, ondelete='cascade', index=True, check_company=True)
    company_id = fields.Many2one('res.company', related='handler_id.company_id', store=True, readonly=True, index=True)
    result_status = fields.Selection(selection=OUTBOUND_RULE_STATUS_SELECTION, required=True, default='send')
    note = fields.Text()
    retry_seconds = fields.Integer(default=0)
    condition_ids = fields.One2many('webhook.handler.outbound.rule.condition', 'rule_id', string='Conditions')
    assignment_ids = fields.One2many('webhook.handler.outbound.assignment', 'rule_id', string='Assignments')

    @api.constrains('result_status', 'retry_seconds')
    def _check_outbound_rule_configuration(self):
        for rule in self:
            if rule.result_status == 'retry' and rule.retry_seconds < 0:
                raise ValidationError(_('Retry delay must be zero or greater.'))


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
    operator = fields.Selection(selection=RULE_CONDITION_OPERATOR_SELECTION, required=True, default='equals')
    expected_value = fields.Char()


class WebhookHandlerOutboundAssignment(models.Model):
    _name = 'webhook.handler.outbound.assignment'
    _description = 'Webhook Handler Outbound Assignment'
    _order = 'sequence, id'
    _check_company_auto = True

    rule_id = fields.Many2one('webhook.handler.outbound.rule', required=True, ondelete='cascade', index=True, check_company=True)
    company_id = fields.Many2one('res.company', related='rule_id.company_id', store=True, readonly=True, index=True)
    sequence = fields.Integer(required=True, default=10)
    target_scope = fields.Selection(
        selection=[
            ('request', 'Request'),
            ('header', 'Header'),
            ('payload', 'Payload'),
        ],
        required=True,
        default='payload',
    )
    target_expression = fields.Char(required=True, string='Target')
    source_kind = fields.Selection(selection=OUTBOUND_RULE_SOURCE_SELECTION, required=True, default='literal')
    source_expression = fields.Char(string='Source Key')
    literal_value = fields.Text()

    @api.constrains('source_kind', 'source_expression')
    def _check_assignment_configuration(self):
        for assignment in self:
            if assignment.source_kind != 'literal' and not assignment.source_expression:
                raise ValidationError(_('Outbound assignments require Source Key unless the source kind is Literal.'))