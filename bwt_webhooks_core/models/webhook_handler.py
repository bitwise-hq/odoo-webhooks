from odoo import api, fields, models
from odoo.exceptions import ValidationError


class WebhookHandler(models.Model):
    _name = "bwt.webhook.handler"
    _inherit = ["mail.thread", "mail.activity.mixin"]
    _description = "Webhook Handler"
    _order = "name, id"
    _check_company_auto = True

    _code_uniq = models.Constraint(
        "unique(code)",
        "The webhook handler code must be unique.",
    )

    _DIRECTION_SELECTION = [
        ("inbound", "Inbound"),
        ("outbound", "Outbound"),
    ]

    name = fields.Char(required=True)
    code = fields.Char(required=True, copy=False, index=True)
    active = fields.Boolean(default=True, tracking=True, help="Archived handlers stay available for audit history but are no longer selectable for new work.")
    company_id = fields.Many2one("res.company", required=True, default=lambda self: self.env.company, index=True)
    direction = fields.Selection(selection=_DIRECTION_SELECTION, required=True, default="inbound", tracking=True, help="Choose whether this handler processes inbound webhook events or outbound webhook deliveries.")
    execution_mode = fields.Selection(selection=[("model_driven", "Model Driven"), ("python", "Python Callback")], required=True, default="model_driven", tracking=True, help="Python callbacks execute custom model methods. Model-driven handlers use inbound and outbound rule rows instead of authored JSON configuration.")
    python_model_name = fields.Char(string="Python Model", help="Technical model name called when execution mode is Python Callback.")
    python_method_name = fields.Char(string="Python Method", help="Method called on the configured model when execution mode is Python Callback.")
    note = fields.Text()

    @api.constrains("execution_mode", "python_model_name", "python_method_name")
    def _check_python_callback_configuration(self):
        for handler in self:
            if handler.execution_mode != "python":
                continue
            if not handler.python_model_name or not handler.python_method_name:
                raise ValidationError(self.env._("Python callback handlers require both a model name and a method name."))

    def execute_inbound(self, event):
        self.ensure_one()
        if self.direction != "inbound":
            raise ValidationError(self.env._("Outbound handlers cannot process inbound webhook events."))
        if self.execution_mode == "python":
            model = self.env[self.python_model_name]
            callback = getattr(model, self.python_method_name, None)
            if not callback:
                raise ValidationError(
                    self.env._(
                        "Python callback %(model)s.%(method)s could not be found.",
                        model=self.python_model_name,
                        method=self.python_method_name,
                    )
                )
            return callback(event)
        return event._execute_model_driven_handler(self)

    def execute_outbound(self, delivery, request_data=None):
        self.ensure_one()
        if self.direction != "outbound":
            raise ValidationError(self.env._("Inbound handlers cannot process outbound webhook deliveries."))
        if self.execution_mode == "python":
            model = self.env[self.python_model_name]
            callback = getattr(model, self.python_method_name, None)
            if not callback:
                raise ValidationError(
                    self.env._(
                        "Python callback %(model)s.%(method)s could not be found.",
                        model=self.python_model_name,
                        method=self.python_method_name,
                    )
                )
            return callback(delivery)
        return delivery._execute_model_driven_handler(self, request_data=request_data)
