import json

from odoo import _, api, fields, models
from odoo.exceptions import ValidationError


class WebhookHandler(models.Model):
    _name = 'webhook.handler'
    _description = 'Webhook Handler'
    _order = 'name, id'
    _check_company_auto = True

    _code_uniq = models.Constraint(
        'unique(code)',
        'The webhook handler code must be unique.',
    )

    name = fields.Char(required=True)
    code = fields.Char(required=True, copy=False, index=True)
    active = fields.Boolean(default=True, help='Archived handlers stay available for audit history but are no longer selectable for new work.')
    company_id = fields.Many2one(
        'res.company',
        required=True,
        default=lambda self: self.env.company,
        index=True,
    )
    inbound_enabled = fields.Boolean(default=True, help='Allow this handler to be selected for inbound webhook processing.')
    outbound_enabled = fields.Boolean(default=False, help='Reserve this handler for future outbound webhook processing.')
    execution_mode = fields.Selection(
        selection=[
            ('low_code', 'Model Driven'),
            ('python', 'Python Callback'),
        ],
        required=True,
        default='low_code',
        help='Python callbacks execute custom model methods. Model-driven handlers use Low-Code Configuration JSON to drive outbound behavior without custom Python.',
    )
    low_code_config_json = fields.Text(
        required=True,
        default='{}',
        string='Low-Code Configuration',
        help='JSON object for low-code behavior. Today the supported section is `outbound`, with keys such as status, note, target_url, http_method, headers, headers_update, payload, payload_update, and seconds.',
    )
    python_model_name = fields.Char(
        string='Python Model',
        help='Technical model name called when execution mode is Python Callback.',
    )
    python_method_name = fields.Char(
        string='Python Method',
        help='Method called on the configured model when execution mode is Python Callback.',
    )
    note = fields.Text()
    endpoint_ids = fields.One2many('webhook.endpoint', 'handler_id', string='Endpoints')
    configuration_warning = fields.Text(
        compute='_compute_configuration_warning',
        string='Configuration Guidance',
    )

    @api.depends('execution_mode', 'low_code_config_json', 'python_model_name', 'python_method_name', 'inbound_enabled', 'outbound_enabled')
    def _compute_configuration_warning(self):
        for handler in self:
            messages = []
            if handler.execution_mode == 'low_code':
                try:
                    handler._get_low_code_config_dict()
                except ValidationError as err:
                    messages.append(str(err))
                if handler.inbound_enabled:
                    messages.append(_('Inbound low-code execution is still store-and-complete only. Use Python Callback mode when inbound business logic must run.'))
                if handler.outbound_enabled:
                    messages.append(_('Outbound low-code execution can send, cancel, dead-letter, or retry deliveries and can mutate request data with the outbound JSON config section.'))
            else:
                if not handler.python_model_name or not handler.python_method_name:
                    messages.append(_('Python callback mode requires both a technical model name and a method name.'))
                else:
                    messages.append(_('Python callbacks are resolved at runtime. Use a technical model name such as integration.webhook and a method name such as handle_event.'))
            if not handler.inbound_enabled and not handler.outbound_enabled:
                messages.append(_('This handler is disabled for both inbound and outbound flows.'))
            handler.configuration_warning = '\n'.join(messages) or False

    @api.constrains('execution_mode', 'python_model_name', 'python_method_name')
    def _check_python_callback_configuration(self):
        for handler in self:
            if handler.execution_mode != 'python':
                continue
            if not handler.python_model_name or not handler.python_method_name:
                raise ValidationError(_('Python callback handlers require both a model name and a method name.'))

    @api.constrains('execution_mode', 'low_code_config_json')
    def _check_low_code_configuration(self):
        allowed_statuses = {'send', 'cancel', 'dead_letter', 'retry'}
        for handler in self:
            if handler.execution_mode != 'low_code':
                continue
            config = handler._get_low_code_config_dict()
            outbound_config = config.get('outbound') or {}
            if not isinstance(outbound_config, dict):
                raise ValidationError(_('Low-Code Configuration outbound section must be a JSON object.'))
            status = outbound_config.get('status')
            if status and status not in allowed_statuses:
                raise ValidationError(_('Low-Code Configuration outbound.status must be one of: send, cancel, dead_letter, retry.'))
            for key in ('headers', 'headers_update'):
                if key in outbound_config and outbound_config.get(key) is not None and not isinstance(outbound_config.get(key), dict):
                    raise ValidationError(_('Low-Code Configuration outbound.%s must be a JSON object.') % key)
            if 'payload_update' in outbound_config and outbound_config.get('payload_update') is not None and not isinstance(outbound_config.get('payload_update'), dict):
                raise ValidationError(_('Low-Code Configuration outbound.payload_update must be a JSON object.'))

    def _get_low_code_config_dict(self):
        self.ensure_one()
        try:
            config = json.loads(self.low_code_config_json or '{}')
        except json.JSONDecodeError as err:
            raise ValidationError(_('Low-Code Configuration must be valid JSON.')) from err
        if not isinstance(config, dict):
            raise ValidationError(_('Low-Code Configuration must be a JSON object.'))
        return config

    def _get_low_code_outbound_config(self):
        self.ensure_one()
        config = self._get_low_code_config_dict()
        outbound_config = config.get('outbound') or {}
        if not isinstance(outbound_config, dict):
            raise ValidationError(_('Low-Code Configuration outbound section must be a JSON object.'))
        return outbound_config

    def execute_inbound(self, event):
        self.ensure_one()
        if self.execution_mode == 'python':
            model = self.env[self.python_model_name]
            callback = getattr(model, self.python_method_name, None)
            if not callback:
                raise ValidationError(
                    _('Python callback %s.%s could not be found.')
                    % (self.python_model_name, self.python_method_name)
                )
            return callback(event)
        return event._execute_low_code_handler(self)

    def execute_outbound(self, delivery, request_data=None):
        self.ensure_one()
        if self.execution_mode == 'python':
            model = self.env[self.python_model_name]
            callback = getattr(model, self.python_method_name, None)
            if not callback:
                raise ValidationError(
                    _('Python callback %s.%s could not be found.')
                    % (self.python_model_name, self.python_method_name)
                )
            return callback(delivery)
        return delivery._execute_low_code_handler(self, request_data=request_data)