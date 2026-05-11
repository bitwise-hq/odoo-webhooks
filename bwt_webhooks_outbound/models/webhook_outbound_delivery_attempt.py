from odoo import fields, models

from odoo.addons.bwt_webhooks_core.models.const import (
    HTTP_METHOD_SELECTION,
    OUTBOUND_REQUEST_BODY_MODE_SELECTION,
)


class WebhookOutboundDeliveryAttempt(models.Model):
    _name = "bwt.webhook.outbound.delivery.attempt"
    _description = "Outbound Webhook Delivery Attempt"
    _order = "attempt_number desc, id desc"
    _check_company_auto = True

    _sql_constraints = [
        (
            "delivery_attempt_number_uniq",
            "unique(delivery_id, attempt_number)",
            "Each outbound delivery attempt number must be unique within the delivery.",
        ),
    ]

    name = fields.Char(
        required=True,
        default=lambda self: self.env._("Outbound Delivery Attempt"),
    )
    delivery_id = fields.Many2one(
        "bwt.webhook.outbound.delivery",
        required=True,
        ondelete="cascade",
        index=True,
        check_company=True,
    )
    endpoint_id = fields.Many2one(
        "bwt.webhook.outbound.endpoint",
        related="delivery_id.endpoint_id",
        store=True,
        readonly=True,
        index=True,
    )
    company_id = fields.Many2one(
        "res.company",
        related="delivery_id.company_id",
        store=True,
        readonly=True,
        index=True,
    )
    attempt_number = fields.Integer(required=True, index=True)
    started_at = fields.Datetime(required=True, default=fields.Datetime.now, index=True)
    finished_at = fields.Datetime(index=True)
    state = fields.Selection(
        selection=[
            ("processing", "Processing"),
            ("done", "Done"),
            ("error", "Error"),
            ("dead_letter", "Dead Letter"),
            ("canceled", "Canceled"),
        ],
        required=True,
        default="processing",
        index=True,
    )
    http_method = fields.Selection(selection=HTTP_METHOD_SELECTION, required=True, string="HTTP Method")
    request_body_mode = fields.Selection(
        selection=OUTBOUND_REQUEST_BODY_MODE_SELECTION,
        required=True,
        default="json",
    )
    multipart_file_keys = fields.Char()
    target_url = fields.Char(required=True, string="Target URL")
    request_headers_json = fields.Text(required=True, string="Request Headers")
    payload_json = fields.Text(required=True, string="Payload JSON")
    response_status_code = fields.Integer(index=True, string="Response Status")
    response_headers_json = fields.Text(string="Response Headers")
    response_body = fields.Text()
    processing_note = fields.Text()
    processing_error = fields.Text()
