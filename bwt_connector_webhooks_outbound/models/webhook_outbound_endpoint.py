"""Reference field linking outbound webhook endpoints to connector backends."""

from odoo import api, fields, models
from odoo.exceptions import ValidationError

from odoo.addons.bwt_connector_webhooks_core.services.naming import (
    slugify_identifier,
)


class WebhookOutboundEndpoint(models.Model):
    _inherit = "bwt.webhook.outbound.endpoint"

    connector_backend_ref = fields.Reference(
        selection=lambda self: self.env["connector.backend"]._selection_connector_webhook_backend_models(),
        string="Connector Backend",
        copy=False,
        help=("Optional connector backend record that owns this outbound webhook endpoint."),
    )
    code_suffix = fields.Char(
        copy=False,
        help=("Stable per-spec identifier shipped by connector addon XML data (e.g. ``customer-create``). When the endpoint is linked to a connector backend the effective ``code`` is derived as ``<backend-prefix>-<code_suffix>`` so multiple backends of the same connector can coexist in one database."),
    )

    _sql_constraints = [
        (
            "connector_backend_code_suffix_uniq",
            "unique(connector_backend_ref, code_suffix)",
            "An outbound endpoint code suffix must be unique per connector backend.",
        ),
    ]

    @api.constrains("connector_backend_ref", "company_id")
    def _check_connector_backend_company(self):
        for endpoint in self:
            backend = endpoint.connector_backend_ref
            if not backend:
                continue
            if backend.company_id and backend.company_id != endpoint.company_id:
                raise ValidationError(self.env._("The linked connector backend company must match the outbound endpoint company."))

    # ------------------------------------------------------------------
    # Backend-scoped ``code`` derivation
    # ------------------------------------------------------------------
    @api.model
    def _derive_connector_endpoint_code(self, vals):
        """Return ``code`` from ``code_suffix`` + ``connector_backend_ref``.

        Returns ``None`` when no derivation applies (no suffix, or no
        backend ref). The caller keeps the explicit ``code`` from
        ``vals`` in that case.
        """
        suffix = vals.get("code_suffix")
        ref = vals.get("connector_backend_ref")
        if not suffix or not ref:
            return None
        if isinstance(ref, str):
            model_name, _, raw_id = ref.partition(",")
            backend = self.env[model_name].browse(int(raw_id)) if model_name and raw_id else None
        else:
            backend = ref
        if not backend or not backend.exists():
            return None
        return backend._build_backend_scoped_technical_name(suffix)

    @api.model
    def _prepare_connector_endpoint_vals(self, vals):
        prepared = dict(vals)
        derived = self._derive_connector_endpoint_code(prepared)
        if derived is not None:
            prepared["code"] = derived
        elif prepared.get("code_suffix") and "code" not in prepared:
            # Pre-link state: use the suffix as a placeholder slug so the
            # ``unique(code)`` base constraint is satisfied at install
            # time. The operator's backend-ref assignment recomputes a
            # backend-scoped code via :meth:`write`.
            prepared["code"] = slugify_identifier(prepared["code_suffix"])
        return prepared

    @api.model_create_multi
    def create(self, vals_list):
        prepared_list = [self._prepare_connector_endpoint_vals(vals) for vals in vals_list]
        return super().create(prepared_list)

    def write(self, vals):
        if "connector_backend_ref" in vals or "code_suffix" in vals:
            for endpoint in self:
                merged = {
                    "code_suffix": endpoint.code_suffix,
                    "connector_backend_ref": endpoint._get_connector_backend_ref_string(),
                    **vals,
                }
                derived = self._derive_connector_endpoint_code(merged)
                if derived is not None:
                    super(WebhookOutboundEndpoint, endpoint).write({**vals, "code": derived})
                else:
                    super(WebhookOutboundEndpoint, endpoint).write(vals)
            return True
        return super().write(vals)

    def _get_connector_backend_ref_string(self):
        self.ensure_one()
        ref = self.connector_backend_ref
        return f"{ref._name},{ref.id}" if ref else False

    # ------------------------------------------------------------------
    # Hostname resolution
    # ------------------------------------------------------------------
    def _outbound_hostname_resolved_externally(self):
        """Connector-linked endpoints get their hostname from the backend."""
        self.ensure_one()
        if self.connector_backend_ref:
            return True
        return super()._outbound_hostname_resolved_externally()

    def _get_outbound_target_hostname(self, delivery=None):
        self.ensure_one()
        backend = self.connector_backend_ref
        if backend:
            resolver = getattr(backend, "_get_outbound_api_base_url", None)
            if resolver:
                resolved = resolver(delivery)
                if resolved:
                    return resolved
        return super()._get_outbound_target_hostname(delivery=delivery)
