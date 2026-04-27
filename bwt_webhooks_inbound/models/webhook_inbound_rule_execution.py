from odoo import fields, models


class WebhookInboundRuleExecution(models.Model):
    _name = "bwt.webhook.inbound.rule.execution"
    _description = "Webhook Inbound Rule Execution"
    _order = "create_date desc, id desc"
    _check_company_auto = True

    name = fields.Char(
        required=True,
        default=lambda self: self.env._("Inbound Rule Execution"),
    )
    event_id = fields.Many2one(
        "bwt.webhook.inbound.event",
        required=True,
        ondelete="cascade",
        index=True,
        check_company=True,
    )
    rule_id = fields.Many2one(
        "bwt.webhook.inbound.handler.rule",
        ondelete="set null",
        index=True,
        check_company=True,
    )
    company_id = fields.Many2one(
        "res.company",
        related="event_id.company_id",
        store=True,
        readonly=True,
        index=True,
    )
    state = fields.Selection(
        selection=[
            ("matched", "Matched"),
            ("done", "Done"),
            ("error", "Error"),
            ("skipped", "Skipped"),
        ],
        required=True,
        default="matched",
        index=True,
    )
    note = fields.Text()
    error = fields.Text()
    record_reference = fields.Char()
