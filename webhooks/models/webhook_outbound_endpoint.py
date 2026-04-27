from odoo import SUPERUSER_ID, _, api, fields, models

from ..exceptions import WebhookProcessingConfigurationError


class WebhookOutboundEndpoint(models.Model):
    _name = 'webhook.outbound.endpoint'
    _inherit = ['mail.thread', 'mail.activity.mixin']
    _description = 'Outbound Webhook Endpoint'
    _order = 'name, id'
    _check_company_auto = True

    _HTTP_METHOD_SELECTION = [
        ('post', 'POST'),
        ('put', 'PUT'),
        ('patch', 'PATCH'),
    ]

    _code_uniq = models.Constraint(
        'unique(code)',
        'The outbound webhook endpoint code must be unique.',
    )

    name = fields.Char(required=True)
    code = fields.Char(required=True, copy=False, index=True)
    active = fields.Boolean(
        default=True,
        tracking=True,
        help='Archived outbound endpoints stay available for audit history but can no longer queue new deliveries.',
    )
    is_paused = fields.Boolean(
        string='Paused',
        default=False,
        tracking=True,
        help='Paused outbound endpoints keep their configuration but will not queue or send deliveries.',
    )
    company_id = fields.Many2one(
        'res.company',
        required=True,
        default=lambda self: self.env.company,
        index=True,
    )
    partner_id = fields.Many2one(
        'res.partner',
        string='Partner',
        index=True,
        check_company=True,
        domain="[('is_company', '=', True)]",
        tracking=True,
        help='Optional endpoint-level tenant/account partner. Outbound deliveries inherit this scope from the endpoint.',
    )
    execution_user_id = fields.Many2one(
        'res.users',
        required=True,
        default=lambda self: self.env.user,
        check_company=True,
        domain="[('share', '=', False), ('active', '=', True)]",
        string='Execution User',
        help='Queued outbound deliveries run as this internal user. Use a dedicated technical user with Webhook Administrator access.',
    )
    handler_id = fields.Many2one(
        'webhook.handler',
        string='Default Handler',
        check_company=True,
        domain="[('outbound_enabled', '=', True)]",
        tracking=True,
        help='Optional handler that can adjust or veto outbound deliveries before the HTTP request is sent. When the selected handler uses Model Driven execution, its outbound rules can mutate, retry, cancel, or dead-letter deliveries.',
    )
    http_method = fields.Selection(
        selection=_HTTP_METHOD_SELECTION,
        required=True,
        default='post',
        string='HTTP Method',
        tracking=True,
    )
    target_url = fields.Char(
        required=True,
        string='Target URL',
        tracking=True,
        help='Absolute URL that will receive the outbound webhook delivery.',
    )
    timeout_seconds = fields.Integer(
        default=30,
        tracking=True,
        help='Request timeout in seconds for outbound deliveries.',
    )
    note = fields.Text()
    header_rule_ids = fields.One2many(
        'webhook.outbound.endpoint.header.rule',
        'endpoint_id',
        string='Header Rules',
        help='Ordered rules that build the outbound request headers from literals and delivery, endpoint, company, partner, or context values.',
    )
    payload_rule_ids = fields.One2many(
        'webhook.outbound.endpoint.payload.rule',
        'endpoint_id',
        string='Payload Rules',
        help='Ordered rules that build the outbound JSON payload through target paths such as order.id or meta.source.',
    )
    outbound_delivery_ids = fields.One2many('webhook.outbound.delivery', 'endpoint_id', string='Outbound Deliveries')
    outbound_delivery_count = fields.Integer(compute='_compute_related_counts')
    failed_delivery_count = fields.Integer(compute='_compute_related_counts')
    operational_state = fields.Selection(
        selection=[
            ('live', 'Live'),
            ('paused', 'Paused'),
            ('archived', 'Archived'),
        ],
        compute='_compute_operational_state',
        string='Operational State',
    )

    def _compute_related_counts(self):
        delivery_model = self.env['webhook.outbound.delivery']
        for endpoint in self:
            endpoint.outbound_delivery_count = delivery_model.search_count([
                ('endpoint_id', '=', endpoint.id),
            ])
            endpoint.failed_delivery_count = delivery_model.search_count([
                ('endpoint_id', '=', endpoint.id),
                ('state', 'in', ('error', 'dead_letter')),
            ])

    @api.depends('active', 'is_paused')
    def _compute_operational_state(self):
        for endpoint in self:
            if not endpoint.active:
                endpoint.operational_state = 'archived'
            elif endpoint.is_paused:
                endpoint.operational_state = 'paused'
            else:
                endpoint.operational_state = 'live'

    @api.constrains('execution_user_id', 'company_id')
    def _check_execution_user_configuration(self):
        for endpoint in self:
            user = endpoint.execution_user_id
            if not user:
                continue
            if user.id == SUPERUSER_ID:
                raise WebhookProcessingConfigurationError(_('Superuser cannot be used as the outbound endpoint execution user.'))
            if user.share or not user.active:
                raise WebhookProcessingConfigurationError(_('Execution user must be an active internal user.'))
            if not user.has_group('webhooks.group_webhooks_admin'):
                raise WebhookProcessingConfigurationError(_('Execution user must belong to the Webhook Administrator group.'))
            if endpoint.company_id and endpoint.company_id not in user.company_ids:
                raise WebhookProcessingConfigurationError(_('Execution user must have access to the outbound endpoint company.'))

    @api.constrains('target_url', 'timeout_seconds')
    def _check_outbound_configuration(self):
        for endpoint in self:
            if not endpoint.target_url or not str(endpoint.target_url).strip():
                raise WebhookProcessingConfigurationError(_('Outbound endpoints require a target URL.'))
            if endpoint.timeout_seconds <= 0:
                raise WebhookProcessingConfigurationError(_('Outbound endpoint timeout must be greater than zero seconds.'))

    def _get_scoped_partner(self):
        self.ensure_one()
        return self.partner_id.commercial_partner_id if self.partner_id else self.env['res.partner']

    def action_view_outbound_deliveries(self):
        self.ensure_one()
        action = self.env.ref('webhooks.action_webhook_outbound_delivery').read()[0]
        action['domain'] = [('endpoint_id', '=', self.id)]
        action['context'] = {'default_endpoint_id': self.id}
        return action

    def action_view_failed_outbound_deliveries(self):
        self.ensure_one()
        action = self.env.ref('webhooks.action_webhook_outbound_delivery').read()[0]
        action['domain'] = [
            ('endpoint_id', '=', self.id),
            ('state', 'in', ('error', 'dead_letter')),
        ]
        action['context'] = {'default_endpoint_id': self.id}
        return action