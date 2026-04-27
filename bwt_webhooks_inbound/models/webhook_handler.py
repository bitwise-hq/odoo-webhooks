from odoo import fields, models


class WebhookHandler(models.Model):
    _inherit = "bwt.webhook.handler"

    endpoint_ids = fields.One2many("bwt.webhook.inbound.endpoint", "handler_id", string="Endpoints")
    inbound_rule_ids = fields.One2many(
        "bwt.webhook.inbound.handler.rule",
        "handler_id",
        string="Inbound Rules",
        help=("Active inbound rules are evaluated in sequence when this handler runs in Model Driven mode."),
    )
