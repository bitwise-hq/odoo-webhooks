from odoo import _, api, fields, models
from odoo.exceptions import ValidationError

from .const import (
    INBOUND_ASSIGNMENT_TARGET_KIND_SELECTION,
    INBOUND_SOURCE_KIND_SELECTION,
)


class WebhookHandlerInboundRuleAssignment(models.Model):
    _name = "webhook.handler.inbound.rule.assignment"
    _description = "Webhook Handler Inbound Rule Assignment"
    _order = "sequence, id"
    _check_company_auto = True

    rule_id = fields.Many2one(
        "webhook.handler.inbound.rule",
        required=True,
        ondelete="cascade",
        index=True,
        check_company=True,
    )
    company_id = fields.Many2one(
        "res.company",
        related="rule_id.company_id",
        store=True,
        readonly=True,
        index=True,
    )
    sequence = fields.Integer(required=True, default=10)
    target_kind = fields.Selection(
        selection=INBOUND_ASSIGNMENT_TARGET_KIND_SELECTION,
        required=True,
        default="field",
    )
    target_expression = fields.Char(required=True, string="Target")
    source_kind = fields.Selection(
        selection=INBOUND_SOURCE_KIND_SELECTION, required=True, default="resolved_value"
    )
    source_expression = fields.Char(string="Source Key")
    literal_value = fields.Text()

    @api.constrains("source_kind", "source_expression")
    def _check_assignment_configuration(self):
        for assignment in self:
            if assignment.source_kind != "literal" and not assignment.source_expression:
                raise ValidationError(
                    _(
                        "Assignment rows require Source Key unless the source kind is Literal."
                    )
                )
