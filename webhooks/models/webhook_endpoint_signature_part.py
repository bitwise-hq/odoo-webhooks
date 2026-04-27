from odoo import api, fields, models
from odoo.exceptions import ValidationError


class WebhookEndpointSignaturePart(models.Model):
    _name = "webhook.endpoint.signature.part"
    _description = "Webhook Endpoint Signature Part"
    _order = "sequence, id"
    _check_company_auto = True

    _SOURCE_KIND_SELECTION = [
        ("raw_body", "Raw Body"),
        ("header", "Header"),
        ("header_param", "Structured Header Parameter"),
        ("payload_path", "Payload Path"),
        ("literal", "Literal"),
        ("computed", "Computed"),
    ]

    endpoint_id = fields.Many2one(
        "webhook.endpoint",
        required=True,
        ondelete="cascade",
        index=True,
        check_company=True,
    )
    company_id = fields.Many2one(
        "res.company",
        related="endpoint_id.company_id",
        store=True,
        readonly=True,
        index=True,
    )
    partner_id = fields.Many2one(
        "res.partner",
        related="endpoint_id.partner_id",
        store=True,
        readonly=True,
        index=True,
    )
    active = fields.Boolean(default=True)
    sequence = fields.Integer(default=10, required=True, string="Part Order")
    source_kind = fields.Selection(
        selection=_SOURCE_KIND_SELECTION,
        required=True,
        default="raw_body",
        string="Part Source",
    )
    header_name = fields.Char()
    header_param_name = fields.Char(string="Header Parameter")
    payload_path = fields.Char()
    literal_value = fields.Char()
    computed_method = fields.Char(string="Compute Method")
    required = fields.Boolean(
        default=False,
        help="If enabled, the entire signature message is invalid when this part cannot be resolved.",
    )

    def _resolve_value(self, endpoint, body, headers, payload):
        self.ensure_one()
        if self.source_kind == "raw_body":
            return body.decode("utf-8", errors="replace")
        if self.source_kind == "header":
            return endpoint._extract_header_value(headers, self.header_name)
        if self.source_kind == "header_param":
            values = endpoint._extract_header_parameter_values(
                headers, self.header_name, self.header_param_name
            )
            return values[0] if values else False
        if self.source_kind == "payload_path":
            return endpoint._extract_payload_path_value(payload, self.payload_path)
        if self.source_kind == "literal":
            return self.literal_value
        if self.source_kind == "computed":
            return endpoint._compute_signature_part_value(self, body, headers, payload)
        return False

    def _check_part_configuration(self):
        for line in self:
            if line.source_kind in ("header", "header_param") and not line.header_name:
                raise ValidationError(
                    self.env._("Header-based signature parts require a header name.")
                )
            if line.source_kind == "header_param" and not line.header_param_name:
                raise ValidationError(
                    self.env._(
                        "Structured header signature parts require a parameter name."
                    )
                )
            if line.source_kind == "payload_path" and not line.payload_path:
                raise ValidationError(
                    self.env._("Payload-path signature parts require a payload path.")
                )
            if line.source_kind == "literal" and line.literal_value in (False, None):
                raise ValidationError(
                    self.env._("Literal signature parts require a literal value.")
                )
            if line.source_kind == "computed" and not line.computed_method:
                raise ValidationError(
                    self.env._(
                        "Computed signature parts require a computed method name."
                    )
                )

    @api.model_create_multi
    def create(self, vals_list):
        records = super().create(vals_list)
        records._check_part_configuration()
        return records

    def write(self, vals):
        result = super().write(vals)
        self._check_part_configuration()
        return result
