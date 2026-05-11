"""Private shared base for connector backends that own webhook endpoints.

This abstract model is **not** inherited directly by concrete backends.
Backends opt in by inheriting one (or both) of the side mixins shipped
by ``bwt_connector_webhooks_inbound`` and ``bwt_connector_webhooks_outbound``;
both side mixins extend this base via Odoo ``_inherit``.

Responsibilities:

* class-level integration contract (canonical webhook fields, marker
  for the reference selection);
* scoping primitives (company / partner / technical prefix / scoped
  display name and code);
* code normalization, defaulting and validation hooks consumed by
  concrete backend constraints.

Endpoint records are owned independently of the backend record (they
are seeded as XML data by concrete connector addons such as
``bwt_stripe_core``); this base does not auto-create handlers,
endpoints, signature parts, sources, or semantic bindings.
"""

from odoo import api, models, _
from odoo.exceptions import ValidationError

from odoo.addons.bwt_connector_webhooks_core.services.naming import (
    slugify_identifier,
)


class ConnectorWebhookBackendBase(models.AbstractModel):
    _name = "bwt.connector.webhook.backend.base"
    _description = "Connector Webhook Backend Base"

    # ------------------------------------------------------------------
    # Integration contract
    # ------------------------------------------------------------------

    #: Marker consumed by
    #: :meth:`connector.backend._selection_connector_webhook_backend_models`
    #: to enumerate concrete backends that opt into the framework.
    _is_connector_webhook_backend = True

    #: Canonical technical-code field on the concrete backend.
    _webhook_code_field = "code"
    #: Canonical display-name field.
    _webhook_name_field = "name"

    # ------------------------------------------------------------------
    # Cross-model reference identity
    # ------------------------------------------------------------------
    def _get_connector_backend_reference(self):
        """Return the ``"model,id"`` reference string for this backend record."""
        self.ensure_one()
        return f"{self._name},{self.id}" if self.id else False

    # ------------------------------------------------------------------
    # Scoping primitives
    # ------------------------------------------------------------------
    def _get_backend_scope_company_id(self):
        self.ensure_one()
        if "company_id" not in self._fields or not self.company_id:
            return False
        return self.company_id.id

    def _get_technical_prefix(self):
        """Connector-specific technical prefix used for handler/endpoint codes.

        Concrete backends override to return e.g. ``stripe-1-acme``; the
        default returns ``<model-token>-<id>``.
        """
        self.ensure_one()
        model_token = slugify_identifier(self._name.replace(".", "-"))
        return f"{model_token or 'backend'}-{self.id}"

    def _build_backend_scoped_technical_name(self, suffix=False):
        self.ensure_one()
        prefix = slugify_identifier(self._get_technical_prefix())
        suffix_token = slugify_identifier(suffix)
        return f"{prefix}-{suffix_token}" if suffix_token else prefix

    def _build_backend_scoped_display_name(self, suffix=False):
        self.ensure_one()
        text = str(suffix or "").strip()
        return f"{self.display_name} {text}" if text else self.display_name

    # ------------------------------------------------------------------
    # Code normalization & validation
    # ------------------------------------------------------------------
    @api.model
    def _get_webhook_backend_default_code(self, prepared_vals):
        name = prepared_vals.get(self._webhook_name_field)
        return slugify_identifier(name) or "backend"

    def _prepare_webhook_backend_vals(self, vals, *, for_create=False):
        """Slugify the technical-code field in ``vals``."""
        prepared = dict(vals)
        code_field = self._webhook_code_field
        if prepared.get(code_field) is not None:
            prepared[code_field] = slugify_identifier(prepared[code_field])
        elif for_create:
            prepared[code_field] = self._get_webhook_backend_default_code(prepared)
        return prepared

    def _validate_webhook_backend_configuration(self):
        """Entry point called from ``@api.constrains`` on concrete backends."""
        for backend in self:
            backend._validate_webhook_backend_code()

    def _validate_webhook_backend_code(self):
        self.ensure_one()
        value = getattr(self, self._webhook_code_field)
        if not value:
            raise ValidationError(
                _(
                    "%(model)s requires a technical code.",
                    model=self._description or self._name,
                )
            )
        if value != slugify_identifier(value):
            raise ValidationError(
                _(
                    "%(model)s codes may contain only letters, digits, and separators.",
                    model=self._description or self._name,
                )
            )

    # ------------------------------------------------------------------
    # Lifecycle: create / write
    # ------------------------------------------------------------------
    @api.model_create_multi
    def create(self, vals_list):
        prepared_list = [self._prepare_webhook_backend_vals(vals, for_create=True) for vals in vals_list]
        return super().create(prepared_list)

    def write(self, vals):
        prepared = self._prepare_webhook_backend_vals(vals)
        return super().write(prepared)
