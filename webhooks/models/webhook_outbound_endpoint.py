from urllib.parse import urlsplit

from odoo import SUPERUSER_ID, _, api, fields, models
from odoo.exceptions import ValidationError

from ..exceptions import WebhookProcessingConfigurationError
from .const import HTTP_METHOD_SELECTION


class WebhookOutboundEndpoint(models.Model):
    _name = "webhook.outbound.endpoint"
    _inherit = ["mail.thread", "mail.activity.mixin"]
    _description = "Outbound Webhook Endpoint"
    _order = "name, id"
    _check_company_auto = True

    _STATE_SELECTION = [
        ("draft", "Draft"),
        ("active", "Active"),
        ("archived", "Archived"),
    ]

    _code_uniq = models.Constraint(
        "unique(code)",
        "The outbound webhook endpoint code must be unique.",
    )

    name = fields.Char(required=True)
    code = fields.Char(required=True, copy=False, index=True)
    state = fields.Selection(
        selection=_STATE_SELECTION,
        required=True,
        default="active",
        index=True,
        tracking=True,
        help="Draft outbound endpoints keep their configuration without queueing deliveries. Archived endpoints remain available for audit history but cannot be used for new work.",
    )
    company_id = fields.Many2one(
        "res.company",
        required=True,
        default=lambda self: self.env.company,
        index=True,
    )
    partner_id = fields.Many2one(
        "res.partner",
        string="Partner",
        index=True,
        check_company=True,
        domain="[('is_company', '=', True)]",
        tracking=True,
        help="Optional endpoint-level tenant/account partner. Outbound deliveries inherit this scope from the endpoint.",
    )
    execution_user_id = fields.Many2one(
        "res.users",
        required=True,
        default=lambda self: self.env.user,
        check_company=True,
        domain="[('share', '=', False), ('active', '=', True)]",
        string="Execution User",
        help="Queued outbound deliveries run as this internal user. Use a dedicated technical user with Webhook Administrator access.",
    )
    handler_id = fields.Many2one(
        "webhook.handler",
        string="Default Handler",
        check_company=True,
        domain="[('direction', '=', 'outbound')]",
        tracking=True,
        help="Optional handler that can adjust or veto outbound deliveries before the HTTP request is sent. When the selected handler uses Model Driven execution, its outbound rules can mutate, retry, cancel, or dead-letter deliveries.",
    )
    http_method = fields.Selection(
        selection=HTTP_METHOD_SELECTION,
        required=True,
        default="post",
        string="HTTP Method",
        tracking=True,
    )
    target_hostname = fields.Char(
        required=True,
        string="Target Hostname",
        tracking=True,
        help="Absolute target hostname, including the URL scheme and optional port, for example https://api.example.com.",
    )
    target_path = fields.Char(
        required=True,
        default="/",
        string="Target Path",
        tracking=True,
        help="Request path appended to the target hostname. Query parameters may be included here when needed.",
    )
    target_url = fields.Char(
        compute="_compute_target_url",
        store=True,
        string="Target URL",
        help="Absolute URL that will receive the outbound webhook delivery.",
    )
    timeout_seconds = fields.Integer(
        default=30,
        tracking=True,
        help="Request timeout in seconds for outbound deliveries.",
    )
    note = fields.Text()
    header_rule_ids = fields.One2many(
        "webhook.outbound.endpoint.header.rule",
        "endpoint_id",
        string="Header Rules",
        help="Ordered rules that build the outbound request headers from literals and delivery, endpoint, company, partner, or context values.",
    )
    payload_rule_ids = fields.One2many(
        "webhook.outbound.endpoint.payload.rule",
        "endpoint_id",
        string="Payload Rules",
        help="Ordered rules that build the outbound JSON payload through target paths such as order.id or meta.source.",
    )
    outbound_delivery_ids = fields.One2many(
        "webhook.outbound.delivery", "endpoint_id", string="Outbound Deliveries"
    )
    outbound_delivery_count = fields.Integer(compute="_compute_related_counts")
    failed_delivery_count = fields.Integer(compute="_compute_related_counts")

    def _compute_related_counts(self):
        delivery_model = self.env["webhook.outbound.delivery"]
        for endpoint in self:
            endpoint.outbound_delivery_count = delivery_model.search_count(
                [
                    ("endpoint_id", "=", endpoint.id),
                ]
            )
            endpoint.failed_delivery_count = delivery_model.search_count(
                [
                    ("endpoint_id", "=", endpoint.id),
                    ("state", "in", ("error", "dead_letter")),
                ]
            )

    @api.model
    def _normalize_target_path(self, target_path):
        target_path = str(target_path or "").strip()
        if not target_path:
            return "/"
        if target_path.startswith("?"):
            return f"/{target_path}"
        if not target_path.startswith("/"):
            return f"/{target_path}"
        return target_path

    @api.model
    def _join_target_url(self, target_hostname, target_path):
        target_hostname = str(target_hostname or "").strip().rstrip("/")
        if not target_hostname:
            return False
        return f"{target_hostname}{self._normalize_target_path(target_path)}"

    @api.model
    def _normalize_target_vals(self, vals):
        normalized_vals = dict(vals)
        if "target_hostname" in normalized_vals and normalized_vals.get(
            "target_hostname"
        ):
            normalized_vals["target_hostname"] = (
                str(normalized_vals["target_hostname"]).strip().rstrip("/")
            )
        if "target_path" in normalized_vals:
            normalized_vals["target_path"] = self._normalize_target_path(
                normalized_vals.get("target_path")
            )
        return normalized_vals

    @api.depends("target_hostname", "target_path")
    def _compute_target_url(self):
        for endpoint in self:
            endpoint.target_url = endpoint._join_target_url(
                endpoint.target_hostname, endpoint.target_path
            )

    @api.constrains("execution_user_id", "company_id")
    def _check_execution_user_configuration(self):
        for endpoint in self:
            user = endpoint.execution_user_id
            if not user:
                continue
            if user.id == SUPERUSER_ID:
                raise WebhookProcessingConfigurationError(
                    _(
                        "Superuser cannot be used as the outbound endpoint execution user."
                    )
                )
            if user.share or not user.active:
                raise WebhookProcessingConfigurationError(
                    _("Execution user must be an active internal user.")
                )
            if not user.has_group("webhooks.group_webhooks_admin"):
                raise WebhookProcessingConfigurationError(
                    _("Execution user must belong to the Webhook Administrator group.")
                )
            if endpoint.company_id and endpoint.company_id not in user.company_ids:
                raise WebhookProcessingConfigurationError(
                    _(
                        "Execution user must have access to the outbound endpoint company."
                    )
                )

    @api.constrains("target_hostname", "target_path", "timeout_seconds")
    def _check_outbound_configuration(self):
        for endpoint in self:
            if (
                not endpoint.target_hostname
                or not str(endpoint.target_hostname).strip()
            ):
                raise WebhookProcessingConfigurationError(
                    _("Outbound endpoints require a target hostname.")
                )
            parsed_hostname = urlsplit(str(endpoint.target_hostname).strip())
            if not parsed_hostname.scheme or not parsed_hostname.netloc:
                raise WebhookProcessingConfigurationError(
                    _(
                        "Outbound endpoint hostnames must include a URL scheme and hostname."
                    )
                )
            if parsed_hostname.query or parsed_hostname.fragment:
                raise WebhookProcessingConfigurationError(
                    _(
                        "Outbound endpoint hostnames cannot include query parameters or URL fragments."
                    )
                )
            hostname_path = parsed_hostname.path or ""
            if hostname_path not in ("", "/"):
                raise WebhookProcessingConfigurationError(
                    _(
                        "Store the outbound request path separately from the target hostname."
                    )
                )
            if "#" in (endpoint.target_path or ""):
                raise WebhookProcessingConfigurationError(
                    _("Outbound endpoint target paths cannot include URL fragments.")
                )
            if not endpoint.target_url or not str(endpoint.target_url).strip():
                raise WebhookProcessingConfigurationError(
                    _("Outbound endpoints require a target URL.")
                )
            if endpoint.timeout_seconds <= 0:
                raise WebhookProcessingConfigurationError(
                    _("Outbound endpoint timeout must be greater than zero seconds.")
                )

    @api.model_create_multi
    def create(self, vals_list):
        normalized_vals_list = [self._normalize_target_vals(vals) for vals in vals_list]
        return super().create(normalized_vals_list)

    def write(self, vals):
        return super().write(self._normalize_target_vals(vals))

    def _get_scoped_partner(self):
        self.ensure_one()
        return (
            self.partner_id.commercial_partner_id
            if self.partner_id
            else self.env["res.partner"]
        )

    def action_view_outbound_deliveries(self):
        self.ensure_one()
        action = self.env.ref("webhooks.action_webhook_outbound_delivery").read()[0]
        action["domain"] = [("endpoint_id", "=", self.id)]
        action["context"] = {"default_endpoint_id": self.id}
        return action

    def action_view_failed_outbound_deliveries(self):
        self.ensure_one()
        action = self.env.ref("webhooks.action_webhook_outbound_delivery").read()[0]
        action["domain"] = [
            ("endpoint_id", "=", self.id),
            ("state", "in", ("error", "dead_letter")),
        ]
        action["context"] = {"default_endpoint_id": self.id}
        return action

    def action_activate(self):
        if self.filtered(lambda endpoint: endpoint.state != "draft"):
            raise ValidationError(_("Only draft outbound endpoints can be activated."))
        self.write({"state": "active"})
        return True

    def action_set_draft(self):
        if self.filtered(lambda endpoint: endpoint.state not in ("active", "archived")):
            raise ValidationError(
                _("Only active or archived outbound endpoints can be moved to draft.")
            )
        self.write({"state": "draft"})
        return True

    def action_archive(self):
        if self.filtered(lambda endpoint: endpoint.state not in ("draft", "active")):
            raise ValidationError(
                _("Only draft or active outbound endpoints can be archived.")
            )
        self.write({"state": "archived"})
        return True
