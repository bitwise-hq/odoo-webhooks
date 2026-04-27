from odoo import SUPERUSER_ID, _, api, fields, models

from ..exceptions import WebhookProcessingConfigurationError


class WebhookOutboundEndpoint(models.Model):
    _name = 'webhook.outbound.endpoint'
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
        help='Archived outbound endpoints stay available for audit history but can no longer queue new deliveries.',
    )
    is_paused = fields.Boolean(
        string='Paused',
        default=False,
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
        help='Optional handler that can adjust or veto outbound deliveries before the HTTP request is sent.',
    )
    http_method = fields.Selection(
        selection=_HTTP_METHOD_SELECTION,
        required=True,
        default='post',
        string='HTTP Method',
    )
    target_url = fields.Char(
        required=True,
        string='Target URL',
        help='Absolute URL that will receive the outbound webhook delivery.',
    )
    timeout_seconds = fields.Integer(
        default=30,
        help='Request timeout in seconds for outbound deliveries.',
    )
    note = fields.Text()
    header_rule_ids = fields.One2many('webhook.outbound.endpoint.header.rule', 'endpoint_id', string='Header Rules')
    payload_rule_ids = fields.One2many('webhook.outbound.endpoint.payload.rule', 'endpoint_id', string='Payload Rules')
    outbound_delivery_ids = fields.One2many('webhook.outbound.delivery', 'endpoint_id', string='Outbound Deliveries')
    outbound_delivery_count = fields.Integer(compute='_compute_related_counts')
    failed_delivery_count = fields.Integer(compute='_compute_related_counts')
    operational_state = fields.Selection(
        selection=[
            ('live', 'Live'),
            ('paused', 'Paused'),
            ('archived', 'Archived'),
        ],
        compute='_compute_admin_guidance',
        string='Operational State',
    )
    configuration_warning = fields.Text(
        compute='_compute_admin_guidance',
        string='Configuration Guidance',
    )
    template_guidance = fields.Text(
        compute='_compute_template_guidance',
        string='Template Guidance',
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

    @api.depends(
        'active',
        'is_paused',
        'partner_id',
        'execution_user_id',
        'handler_id',
        'handler_id.execution_mode',
        'http_method',
        'target_url',
        'timeout_seconds',
        'header_rule_ids.active',
        'payload_rule_ids.active',
    )
    def _compute_admin_guidance(self):
        for endpoint in self:
            if not endpoint.active:
                endpoint.operational_state = 'archived'
            elif endpoint.is_paused:
                endpoint.operational_state = 'paused'
            else:
                endpoint.operational_state = 'live'

            messages = []
            if not endpoint.active:
                messages.append(_('Archived outbound endpoints stay available for audit history but do not send new deliveries.'))
            elif endpoint.is_paused:
                messages.append(_('Paused outbound endpoints keep their configuration but do not queue or send deliveries.'))

            if endpoint.partner_id:
                messages.append(
                    _('This outbound endpoint is scoped to partner %s. Deliveries inherit that scope from the endpoint.')
                    % endpoint._get_scoped_partner().display_name
                )
            else:
                messages.append(_('This outbound endpoint is company-scoped only. Deliveries do not store a partner from endpoint scope.'))

            if endpoint.handler_id and endpoint.handler_id.execution_mode == 'low_code':
                messages.append(_('The selected outbound handler uses relational low-code rules and can mutate, cancel, dead-letter, or retry deliveries without authored JSON.'))

            if not endpoint.header_rule_ids.filtered('active'):
                messages.append(_('No active Header Rules are configured on this endpoint yet.'))
            if not endpoint.payload_rule_ids.filtered('active'):
                messages.append(_('No active Payload Rules are configured on this endpoint yet.'))

            if endpoint.timeout_seconds <= 0:
                messages.append(_('Outbound timeout should be greater than zero seconds.'))

            endpoint.configuration_warning = '\n'.join(messages) or False

    @api.depends('partner_id', 'handler_id', 'handler_id.execution_mode', 'header_rule_ids.active', 'payload_rule_ids.active')
    def _compute_template_guidance(self):
        for endpoint in self:
            messages = [
                _('Header Rules build the outbound headers one row at a time from literals, delivery fields, endpoint fields, company fields, partner fields, and delivery context keys.'),
                _('Payload Rules build nested payload structures through free-form target paths such as order.id or meta.source.')
            ]
            if not endpoint.partner_id:
                messages.append(_('Partner-derived rule values resolve false when the endpoint is company-scoped only.'))
            if endpoint.handler_id and endpoint.handler_id.execution_mode == 'low_code':
                messages.append(_('Low-code outbound handler rules can inspect delivery fields, endpoint fields, delivery context keys, and the pre-send request snapshot built from these endpoint rules.'))
            endpoint.template_guidance = '\n'.join(messages)

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