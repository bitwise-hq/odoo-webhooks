from odoo import fields, models


class WebhookHandler(models.Model):
    _inherit = "bwt.webhook.handler"

    outbound_rule_ids = fields.One2many(
        "bwt.webhook.outbound.handler.rule",
        "handler_id",
        string="Outbound Rules",
        help=("Active outbound rules are evaluated in sequence when this handler runs in Model Driven mode."),
    )
