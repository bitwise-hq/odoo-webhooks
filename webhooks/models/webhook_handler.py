from odoo import _, api, fields, models
from odoo.exceptions import ValidationError


class WebhookHandler(models.Model):
    _name = 'webhook.handler'
    _inherit = ['mail.thread', 'mail.activity.mixin']
    _description = 'Webhook Handler'
    _order = 'name, id'
    _check_company_auto = True

    _code_uniq = models.Constraint(
        'unique(code)',
        'The webhook handler code must be unique.',
    )

    def init(self):
        self.env.cr.execute(
            """
            UPDATE webhook_handler
               SET execution_mode = 'model_driven'
             WHERE execution_mode = 'low_code'
            """
        )

    name = fields.Char(required=True)
    code = fields.Char(required=True, copy=False, index=True)
    active = fields.Boolean(default=True, tracking=True, help='Archived handlers stay available for audit history but are no longer selectable for new work.')
    company_id = fields.Many2one(
        'res.company',
        required=True,
        default=lambda self: self.env.company,
        index=True,
    )
    inbound_enabled = fields.Boolean(default=True, tracking=True, help='Allow this handler to be selected for inbound webhook processing.')
    outbound_enabled = fields.Boolean(default=False, tracking=True, help='Reserve this handler for future outbound webhook processing.')
    execution_mode = fields.Selection(
        selection=[
            ('model_driven', 'Model Driven'),
            ('python', 'Python Callback'),
        ],
        required=True,
        default='model_driven',
        tracking=True,
        help='Python callbacks execute custom model methods. Model-driven handlers use inbound and outbound rule rows instead of authored JSON configuration.',
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
    inbound_rule_ids = fields.One2many('webhook.handler.inbound.rule', 'handler_id', string='Inbound Rules')
    outbound_rule_ids = fields.One2many('webhook.handler.outbound.rule', 'handler_id', string='Outbound Rules')
    configuration_warning = fields.Text(
        compute='_compute_configuration_warning',
        string='Configuration Guidance',
    )

    @api.depends(
        'execution_mode',
        'python_model_name',
        'python_method_name',
        'inbound_enabled',
        'outbound_enabled',
        'inbound_rule_ids.active',
        'inbound_rule_ids.action_type',
        'outbound_rule_ids.active',
        'outbound_rule_ids.result_status',
    )
    def _compute_configuration_warning(self):
        for handler in self:
            messages = []
            if handler.execution_mode == 'model_driven':
                inbound_rule_count = len(handler.inbound_rule_ids.filtered('active'))
                outbound_rule_count = len(handler.outbound_rule_ids.filtered('active'))
                if handler.inbound_enabled:
                    if inbound_rule_count:
                        messages.append(_('Inbound model-driven execution is configured through %s active inbound rule(s).') % inbound_rule_count)
                    else:
                        messages.append(_('Inbound model-driven execution is enabled but no active inbound rules are configured yet.'))
                if handler.outbound_enabled:
                    if outbound_rule_count:
                        messages.append(_('Outbound model-driven execution is configured through %s active outbound rule(s).') % outbound_rule_count)
                    else:
                        messages.append(_('Outbound model-driven execution is enabled but no active outbound rules are configured yet.'))
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
        return event._execute_model_driven_handler(self)

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
        return delivery._execute_model_driven_handler(self, request_data=request_data)