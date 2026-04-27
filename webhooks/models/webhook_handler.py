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
        help='Python callbacks are executable today. Model-driven execution is visible for the upcoming low-code engine but is still a placeholder in this version.',
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

    @api.depends('execution_mode', 'python_model_name', 'python_method_name', 'inbound_enabled', 'outbound_enabled')
    def _compute_configuration_warning(self):
        for handler in self:
            messages = []
            if handler.execution_mode == 'low_code':
                messages.append(_('Model-driven execution is not implemented yet. Inbound events handled here will be stored and completed with a processing note.'))
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

    def execute_outbound(self, delivery):
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
        return delivery._execute_low_code_handler(self)