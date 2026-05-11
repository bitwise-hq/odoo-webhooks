import re
from urllib.parse import urlsplit

from odoo import api, fields, models, _
from odoo.exceptions import ValidationError

from odoo.addons.bwt_webhooks_core.exceptions import WebhookProcessingConfigurationError
from odoo.addons.bwt_webhooks_core.models.const import (
    HTTP_METHOD_SELECTION,
    OUTBOUND_REQUEST_BODY_MODE_SELECTION,
)

#: Pattern matching ``{token}`` placeholders in outbound target paths.
#: Token names are restricted to identifier characters so we can
#: validate them against the delivery's resolved context values.
_TARGET_PATH_TOKEN_RE = re.compile(r"\{([A-Za-z_][A-Za-z0-9_]*)\}")


class WebhookOutboundEndpoint(models.Model):
    _name = "bwt.webhook.outbound.endpoint"
    _inherit = ["mail.thread", "mail.activity.mixin"]
    _description = "Outbound Webhook Endpoint"
    _order = "name, id"
    _check_company_auto = True

    _STATE_SELECTION = [
        ("draft", "Draft"),
        ("active", "Active"),
        ("archived", "Archived"),
    ]

    _sql_constraints = [
        ("code_uniq", "unique(code)", "The outbound webhook endpoint code must be unique."),
    ]

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
    handler_id = fields.Many2one(
        "bwt.webhook.handler",
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
    request_body_mode = fields.Selection(
        selection=OUTBOUND_REQUEST_BODY_MODE_SELECTION,
        required=True,
        default="json",
        tracking=True,
        help="Controls how outbound request payloads are encoded. JSON keeps the existing default behavior. Form URL Encoded and Multipart use key-value form serialization.",
    )
    target_hostname = fields.Char(
        tracking=True,
        help=("Absolute target hostname, including the URL scheme and optional port, for example https://api.example.com. Optional when the hostname is resolved at delivery time by an extending addon (see ``_get_outbound_target_hostname``)."),
    )
    target_path = fields.Char(
        required=True,
        default="/",
        tracking=True,
        help=("Request path appended to the target hostname. May contain ``{token}`` placeholders that are interpolated at send time from the delivery's resolved context values, e.g. ``/v1/customers/{customer_id}``."),
    )
    target_url = fields.Char(
        compute="_compute_target_url",
        store=True,
        string="Target URL",
        help=("Configured URL template that will receive the outbound webhook delivery. May contain ``{token}`` placeholders; the rendered URL is computed per delivery from the resolved context values."),
    )
    timeout_seconds = fields.Integer(
        default=30,
        tracking=True,
        help="Request timeout in seconds for outbound deliveries.",
    )
    note = fields.Text()
    header_rule_ids = fields.One2many(
        "bwt.webhook.outbound.endpoint.header.rule",
        "endpoint_id",
        string="Header Rules",
        help="Ordered rules that build the outbound request headers from literals and delivery, endpoint, company, partner, or context values.",
    )
    payload_rule_ids = fields.One2many(
        "bwt.webhook.outbound.endpoint.payload.rule",
        "endpoint_id",
        string="Payload Rules",
        help="Ordered rules that build the outbound JSON payload through target paths such as order.id or meta.source.",
    )
    outbound_delivery_ids = fields.One2many("bwt.webhook.outbound.delivery", "endpoint_id", string="Outbound Deliveries")
    outbound_delivery_count = fields.Integer(compute="_compute_related_counts")
    failed_delivery_count = fields.Integer(compute="_compute_related_counts")

    def _compute_related_counts(self):
        delivery_model = self.env["bwt.webhook.outbound.delivery"]
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

    # ------------------------------------------------------------------
    # Hostname / path hooks
    # ------------------------------------------------------------------
    def _outbound_hostname_resolved_externally(self):
        """Return ``True`` when an extending addon resolves the hostname.

        Extending addons (e.g. ``bwt_connector_webhooks_outbound``) set
        this to ``True`` for endpoints whose hostname is sourced from a
        linked record at delivery time, which relaxes the
        ``target_hostname`` validation in :meth:`_check_outbound_configuration`.
        """
        self.ensure_one()
        return False

    def _get_outbound_target_hostname(self, delivery=None):  # noqa: ARG002
        """Return the absolute hostname to use for an outbound request.

        Default implementation returns the configured
        :attr:`target_hostname`. Extending addons override to source
        the hostname from a linked record (e.g. a connector backend's
        ``api_base_url``).
        """
        self.ensure_one()
        return self.target_hostname or False

    def _render_outbound_target_url(self, context_values, delivery=None):
        """Resolve the absolute URL for a single delivery.

        Joins the hostname returned by
        :meth:`_get_outbound_target_hostname` with the configured
        :attr:`target_path`, then interpolates ``{token}``
        placeholders from ``context_values``. Unknown tokens raise
        :class:`WebhookProcessingConfigurationError` so misconfigured
        endpoints surface a clear error rather than emitting a
        request with literal placeholders.
        """
        self.ensure_one()
        hostname = self._get_outbound_target_hostname(delivery=delivery)
        if not hostname:
            raise WebhookProcessingConfigurationError(
                _(
                    "Outbound endpoint %(name)s has no resolvable target hostname.",
                    name=self.display_name,
                )
            )
        url = f"{str(hostname).strip().rstrip('/')}{self._normalize_target_path(self.target_path)}"
        return self._render_path_tokens(url, context_values or {})

    @api.model
    def _render_path_tokens(self, text, context_values):
        """Replace ``{name}`` placeholders in ``text`` from ``context_values``.

        Raises :class:`WebhookProcessingConfigurationError` when a
        token is missing or resolves to a falsy value, to stop the
        framework from emitting a literal ``/v1/customers/{id}``
        request that would silently 404 against a remote API.
        """
        text = str(text or "")

        def _replace(match):
            token = match.group(1)
            if token not in context_values or context_values[token] in (None, False, ""):
                raise WebhookProcessingConfigurationError(
                    _(
                        "Outbound delivery context is missing value for path token %(token)s.",
                        token=token,
                    )
                )
            return str(context_values[token])

        return _TARGET_PATH_TOKEN_RE.sub(_replace, text)

    @api.model
    def _normalize_target_vals(self, vals):
        normalized_vals = dict(vals)
        if "target_hostname" in normalized_vals and normalized_vals.get("target_hostname"):
            normalized_vals["target_hostname"] = str(normalized_vals["target_hostname"]).strip().rstrip("/")
        if "target_path" in normalized_vals:
            normalized_vals["target_path"] = self._normalize_target_path(normalized_vals.get("target_path"))
        return normalized_vals

    @api.depends("target_hostname", "target_path")
    def _compute_target_url(self):
        for endpoint in self:
            hostname = endpoint._get_outbound_target_hostname()
            endpoint.target_url = endpoint._join_target_url(hostname, endpoint.target_path)

    @api.constrains("target_hostname", "target_path", "timeout_seconds")
    def _check_outbound_configuration(self):
        for endpoint in self:
            hostname = (endpoint.target_hostname or "").strip()
            if not hostname:
                # Missing hostname is acceptable when either:
                # - an extending addon resolves it dynamically at send time, or
                # - the endpoint is still in draft (admins can link a backend later), or
                # - records are being installed from XML (install_mode), where
                #   downstream addons may link a backend afterwards.
                if not endpoint._outbound_hostname_resolved_externally() and endpoint.state != "draft" and not self.env.context.get("install_mode"):
                    raise WebhookProcessingConfigurationError(_("Outbound endpoints require a target hostname."))
            else:
                parsed_hostname = urlsplit(hostname)
                if not parsed_hostname.scheme or not parsed_hostname.netloc:
                    raise WebhookProcessingConfigurationError(_("Outbound endpoint hostnames must include a URL scheme and hostname."))
                if parsed_hostname.query or parsed_hostname.fragment:
                    raise WebhookProcessingConfigurationError(_("Outbound endpoint hostnames cannot include query parameters or URL fragments."))
                hostname_path = parsed_hostname.path or ""
                if hostname_path not in ("", "/"):
                    raise WebhookProcessingConfigurationError(_("Store the outbound request path separately from the target hostname."))
            if "#" in (endpoint.target_path or ""):
                raise WebhookProcessingConfigurationError(_("Outbound endpoint target paths cannot include URL fragments."))
            if endpoint.timeout_seconds <= 0:
                raise WebhookProcessingConfigurationError(_("Outbound endpoint timeout must be greater than zero seconds."))

    @api.model_create_multi
    def create(self, vals_list):
        normalized_vals_list = [self._normalize_target_vals(vals) for vals in vals_list]
        return super().create(normalized_vals_list)

    def write(self, vals):
        return super().write(self._normalize_target_vals(vals))

    def action_view_outbound_deliveries(self):
        self.ensure_one()
        action = self.env.ref("bwt_webhooks_outbound.action_webhook_outbound_delivery").read()[0]
        action["domain"] = [("endpoint_id", "=", self.id)]
        action["context"] = {"default_endpoint_id": self.id}
        return action

    def action_view_failed_outbound_deliveries(self):
        self.ensure_one()
        action = self.env.ref("bwt_webhooks_outbound.action_webhook_outbound_delivery").read()[0]
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
            raise ValidationError(_("Only active or archived outbound endpoints can be moved to draft."))
        self.write({"state": "draft"})
        return True

    def action_archive(self):
        if self.filtered(lambda endpoint: endpoint.state not in ("draft", "active")):
            raise ValidationError(_("Only draft or active outbound endpoints can be archived."))
        self.write({"state": "archived"})
        return True
