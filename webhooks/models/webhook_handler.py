from odoo import _, api, fields, models
from odoo.exceptions import ValidationError


class WebhookHandler(models.Model):
    _name = 'webhook.handler'
    _description = 'Webhook Handler'
    _order = 'name, id'

    _code_uniq = models.Constraint(
        'unique(code)',
        'The webhook handler code must be unique.',
    )

    name = fields.Char(required=True)
    code = fields.Char(required=True, copy=False, index=True)
    active = fields.Boolean(default=True)
    company_id = fields.Many2one(
        'res.company',
        required=True,
        default=lambda self: self.env.company,
        index=True,
    )
    inbound_enabled = fields.Boolean(default=True)
    outbound_enabled = fields.Boolean(default=False)
    execution_mode = fields.Selection(
        selection=[
            ('low_code', 'Model Driven'),
            ('python', 'Python Callback'),
        ],
        required=True,
        default='low_code',
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