"""Inbound webhook endpoint configuration model.

This module owns all the runtime helpers used by the inbound delivery
pipeline: header/payload value extraction, semantic binding lookup,
signature verification, freshness checks, and identity resolution.

The implementation is deliberately split into small helpers that are
either pure (module-level) or strictly scoped to a single endpoint
record (``ensure_one``-guarded methods). Sibling models, controllers,
and the test suite consume these helpers, so their names and
signatures form a stable internal API.
"""

from typing import Optional

from odoo import api, fields, models
from odoo.exceptions import ValidationError

from odoo.addons.bwt_webhooks_core.exceptions import (
    WebhookFreshnessValidationError,
    WebhookPayloadValidationError,
    WebhookProcessingConfigurationError,
    WebhookSignatureValidationError,
    WebhookValidationError,
)
from odoo.addons.bwt_webhooks_core.services.constants import (
    BLANK_VALUES,
    DELIVERY_IDENTITY_POLICY_SELECTION,
    DELIVERY_POLICY_LABELS,
    ENDPOINT_STATE_SELECTION,
    PAYLOAD_CONTRACT_SELECTION,
    REPLAY_IDENTITY_POLICY_SELECTION,
    REPLAY_POLICY_LABELS,
    SIGNATURE_DIGEST_SELECTION,
    SIGNATURE_ENCODING_SELECTION,
    SIGNATURE_MODE_SELECTION,
    TIMESTAMP_FORMAT_SELECTION,
)
from odoo.addons.bwt_webhooks_core.services.identity import (
    IdentityNotResolvable,
    resolve_delivery_identity,
    resolve_replay_identity,
)
from odoo.addons.bwt_webhooks_core.services.signature import (
    compute_expected_signature,
    parse_signature_timestamp,
    strip_signature_prefix,
    validate_signature_freshness,
    verify_signature_against_secrets,
)
from odoo.addons.bwt_webhooks_core.services.value_extraction import (
    extract_header,
    extract_header_parameters,
    normalize_headers,
    walk_payload_path,
)
from odoo.addons.bwt_webhooks_core.services.value_objects import InboundMetadata  # noqa: F401  (re-exported)
from .webhook_inbound_endpoint_semantic_binding import WEBHOOK_SEMANTIC_NAMES

# ---------------------------------------------------------------------------
# Backward-compatible re-exports
# ---------------------------------------------------------------------------

# These aliases keep imports such as ``from ..models.webhook_inbound_endpoint
# import SIGNATURE_MODE_SELECTION`` working after the constants moved into
# the services package. New code should import from
# ``..services.constants`` directly.
_DELIVERY_POLICY_LABELS = DELIVERY_POLICY_LABELS
_REPLAY_POLICY_LABELS = REPLAY_POLICY_LABELS
_BLANK_VALUES = BLANK_VALUES

# ---------------------------------------------------------------------------
# Model
# ---------------------------------------------------------------------------


class WebhookInboundEndpoint(models.Model):
    _name = "bwt.webhook.inbound.endpoint"
    _table = "webhook_endpoint"
    _inherit = ["mail.thread", "mail.activity.mixin"]
    _description = "Inbound Webhook Endpoint"
    _order = "name, id"
    _check_company_auto = True

    # Class-level mirrors kept for legacy lookups via ``self._...``.
    _SIGNATURE_MODE_SELECTION = SIGNATURE_MODE_SELECTION
    _SIGNATURE_DIGEST_SELECTION = SIGNATURE_DIGEST_SELECTION
    _SIGNATURE_ENCODING_SELECTION = SIGNATURE_ENCODING_SELECTION
    _TIMESTAMP_FORMAT_SELECTION = TIMESTAMP_FORMAT_SELECTION
    _PAYLOAD_CONTRACT_SELECTION = PAYLOAD_CONTRACT_SELECTION
    _DELIVERY_IDENTITY_POLICY_SELECTION = DELIVERY_IDENTITY_POLICY_SELECTION
    _REPLAY_IDENTITY_POLICY_SELECTION = REPLAY_IDENTITY_POLICY_SELECTION
    _STATE_SELECTION = ENDPOINT_STATE_SELECTION

    _sql_constraints = [
        ("path_uniq", "unique(path)", "The inbound webhook path must be unique."),
    ]

    # -- Fields --------------------------------------------------------------

    name = fields.Char(required=True)
    path = fields.Char(
        required=True,
        copy=False,
        index=True,
        help=("Unique public inbound webhook path segment. This value becomes part of the route URL and cannot be changed after the endpoint is created."),
    )
    state = fields.Selection(
        selection=ENDPOINT_STATE_SELECTION,
        required=True,
        default="active",
        index=True,
        tracking=True,
        help=("Draft endpoints keep their configuration without accepting traffic. Archived endpoints stay available for audit history but are not matched by the public route."),
    )
    company_id = fields.Many2one(
        "res.company",
        required=True,
        default=lambda self: self.env.company,
        index=True,
    )
    route_path = fields.Char(
        compute="_compute_route_path",
        string="Public Route",
        help="Computed public path derived from the immutable endpoint path.",
    )
    handler_id = fields.Many2one(
        "bwt.webhook.handler",
        string="Default Handler",
        check_company=True,
        domain="[('direction', '=', 'inbound')]",
        tracking=True,
        help=("Fallback handler used when no handler selector resolves another handler. If this is empty and no selector resolves, the event is stored only. When the selected handler uses Model Driven execution, its inbound rules control what business action runs."),
    )
    source_ids = fields.One2many(
        "bwt.webhook.inbound.endpoint.source",
        "endpoint_id",
        string="Value Resolution Rules",
        help=("Ordered rules used to resolve built-in semantics and custom values from headers, payload, literals, hashes, or computed methods."),
        copy=True,
    )
    semantic_binding_ids = fields.One2many(
        "bwt.webhook.inbound.endpoint.semantic.binding",
        "endpoint_id",
        string="Semantic Bindings",
        copy=True,
        help=("Maps built-in webhook semantics such as signature, delivery identity, and handler selector to resolved keys from the Value Resolution rules."),
    )
    delivery_identity_policy = fields.Selection(
        selection=DELIVERY_IDENTITY_POLICY_SELECTION,
        required=True,
        default="delivery_id",
        tracking=True,
        help="Select which semantic identifies an exact delivery for duplicate detection.",
    )
    replay_identity_policy = fields.Selection(
        selection=REPLAY_IDENTITY_POLICY_SELECTION,
        required=True,
        default="none",
        tracking=True,
        help="Optionally select which semantic links distinct deliveries of the same business event.",
    )
    payload_contract = fields.Selection(
        selection=PAYLOAD_CONTRACT_SELECTION,
        required=True,
        default="json_object",
        tracking=True,
        help=("JSON Object accepts only top-level JSON objects. Any JSON Value also allows arrays, scalars, booleans, and null."),
    )
    signature_verification_mode = fields.Selection(
        selection=SIGNATURE_MODE_SELECTION,
        required=True,
        default="none",
        tracking=True,
        help="Enable shared-secret HMAC verification for incoming requests.",
    )
    signature_secret = fields.Char(
        copy=False,
        groups="base.group_system",
        help="Primary shared secret used to compute the expected webhook signature.",
    )
    signature_secondary_secret = fields.Char(
        string="Secondary Signature Secret",
        copy=False,
        groups="base.group_system",
        help="Optional secondary secret used during rotation windows.",
    )
    signature_digest_algorithm = fields.Selection(
        selection=SIGNATURE_DIGEST_SELECTION,
        required=True,
        default="sha256",
    )
    signature_encoding = fields.Selection(
        selection=SIGNATURE_ENCODING_SELECTION,
        required=True,
        default="hex",
    )
    signature_prefix = fields.Char(
        help="Optional prefix stripped from extracted signature values before comparison, such as v1=.",
    )
    signature_message_joiner = fields.Char(
        string="Join Signature Parts With",
        default="",
        help=("Text inserted between signature message parts. If no parts are configured, the raw request body is used."),
    )
    signature_timestamp_format = fields.Selection(
        selection=TIMESTAMP_FORMAT_SELECTION,
        required=True,
        default="unix",
        help=("How the extracted signature_timestamp value should be parsed when freshness checks are enabled."),
    )
    signature_max_age_seconds = fields.Integer(
        default=300,
        help="Maximum allowed signature age in seconds. Set to 0 to disable the age check.",
    )
    signature_max_future_skew_seconds = fields.Integer(
        default=300,
        help="Maximum allowed future clock skew in seconds. Set to 0 to disable the future-skew check.",
    )
    signature_part_ids = fields.One2many(
        "bwt.webhook.inbound.endpoint.signature.part",
        "endpoint_id",
        string="Signature Message Parts",
        copy=True,
        help=("Optional ordered signature parts used to assemble the signed message. If no parts are configured, the raw request body is used as the signed message."),
    )
    inbound_event_ids = fields.One2many("bwt.webhook.inbound.event", "endpoint_id", string="Inbound Events")
    inbound_event_count = fields.Integer(compute="_compute_related_counts")
    rejected_event_count = fields.Integer(compute="_compute_related_counts")

    # -- Computes -----------------------------------------------------------

    @api.depends("path")
    def _compute_route_path(self):
        for endpoint in self:
            endpoint.route_path = f"/webhooks/in/{endpoint.path}" if endpoint.path else False

    def _compute_related_counts(self):
        event_model = self.env["bwt.webhook.inbound.event"]
        for endpoint in self:
            base_domain = [("endpoint_id", "=", endpoint.id)]
            endpoint.inbound_event_count = event_model.search_count(base_domain + [("state", "!=", "rejected")])
            endpoint.rejected_event_count = event_model.search_count(base_domain + [("state", "=", "rejected")])

    # -- Path normalization & validation ------------------------------------

    @api.model
    def _normalize_webhook_path_segment(self, value):
        return str(value or "").strip().strip("/")

    @api.model
    def _validate_webhook_path_segment(self, value, *, required=True, label=False):
        normalized = self._normalize_webhook_path_segment(value)
        error_label = label or self.env._("Inbound endpoint paths")
        if not normalized:
            if required:
                raise ValidationError(
                    self.env._(
                        "%(error_label)s require a single URL path segment.",
                        error_label=error_label,
                    )
                )
            return normalized
        if "/" in normalized:
            raise ValidationError(
                self.env._(
                    "%(error_label)s must be a single URL path segment without slashes.",
                    error_label=error_label,
                )
            )
        if any(character.isspace() for character in normalized):
            raise ValidationError(
                self.env._(
                    "%(error_label)s cannot contain whitespace.",
                    error_label=error_label,
                )
            )
        return normalized

    @api.model
    def _normalize_path_vals(self, vals):
        if "path" not in vals or vals.get("path") is False:
            return dict(vals)
        normalized = dict(vals)
        normalized["path"] = self._normalize_webhook_path_segment(normalized["path"])
        return normalized

    @api.constrains("path")
    def _check_path_configuration(self):
        for endpoint in self:
            endpoint._validate_webhook_path_segment(endpoint.path)

    # -- ORM overrides ------------------------------------------------------

    @api.model_create_multi
    def create(self, vals_list):
        return super().create([self._normalize_path_vals(vals) for vals in vals_list])

    def write(self, vals):
        normalized = self._normalize_path_vals(vals)
        new_path = normalized.get("path")
        if new_path:
            changed = self.filtered(lambda endpoint: endpoint.id and endpoint.path and endpoint.path != new_path)
            if changed:
                raise ValidationError(self.env._("Inbound endpoint paths cannot be changed after the endpoint is created."))
        return super().write(normalized)

    # -- Configuration constraints ------------------------------------------

    @api.constrains(
        "signature_verification_mode",
        "signature_secret",
        "signature_max_age_seconds",
        "signature_max_future_skew_seconds",
        "source_ids",
        "semantic_binding_ids",
        "delivery_identity_policy",
        "replay_identity_policy",
    )
    def _check_signature_configuration(self):
        for endpoint in self:
            endpoint._validate_identity_and_signature_policies()

    def _validate_identity_and_signature_policies(self):
        self.ensure_one()
        if self.state == "draft":
            # Draft endpoints are not operational; skip completeness checks so
            # XML data records can be created before their semantic bindings and
            # signature parts are fully wired up.
            return
        binding_map = self._get_semantic_binding_map()

        if self.delivery_identity_policy != "body_sha256":
            self._require_policy_binding(
                policy=self.delivery_identity_policy,
                semantic_name=self.delivery_identity_policy,
                binding_map=binding_map,
                policy_label=_DELIVERY_POLICY_LABELS[self.delivery_identity_policy],
                kind="delivery",
            )

        if self.replay_identity_policy != "none":
            self._require_policy_binding(
                policy=self.replay_identity_policy,
                semantic_name=self.replay_identity_policy,
                binding_map=binding_map,
                policy_label=_REPLAY_POLICY_LABELS[self.replay_identity_policy],
                kind="replay",
            )

        if self.signature_verification_mode != "hmac":
            return

        if not self.signature_secret:
            raise WebhookProcessingConfigurationError(self.env._("HMAC verification requires a primary signature secret."))

        signature_key = binding_map.get("signature")
        if not signature_key:
            raise WebhookProcessingConfigurationError(self.env._("HMAC verification requires a semantic binding for Signature."))
        if not self._has_active_source_for_key(signature_key):
            raise WebhookProcessingConfigurationError(
                self.env._(
                    "HMAC verification is bound to %(key)s for Signature, but no active value resolution rule produces that key.",
                    key=signature_key,
                )
            )

        if self.signature_max_age_seconds > 0 or self.signature_max_future_skew_seconds > 0:
            timestamp_key = binding_map.get("signature_timestamp")
            if not timestamp_key:
                raise WebhookProcessingConfigurationError(self.env._("Freshness checks require a semantic binding for Signature Timestamp."))
            if not self._has_active_source_for_key(timestamp_key):
                raise WebhookProcessingConfigurationError(
                    self.env._(
                        "Freshness checks are bound to %(key)s for Signature Timestamp, but no active value resolution rule produces that key.",
                        key=timestamp_key,
                    )
                )

    def _require_policy_binding(self, *, policy, semantic_name, binding_map, policy_label, kind):
        """Validate that an identity ``policy`` resolves to an active source key."""
        self.ensure_one()
        # ``kind`` distinguishes the wording but the structural check is identical.
        bound_key = binding_map.get(semantic_name)
        if not bound_key:
            raise WebhookProcessingConfigurationError(
                self.env._(
                    "%(kind_label)s identity policy %(policy)s requires a semantic binding.",
                    kind_label=self.env._("Delivery") if kind == "delivery" else self.env._("Replay"),
                    policy=policy_label,
                )
            )
        if not self._has_active_source_for_key(bound_key):
            raise WebhookProcessingConfigurationError(
                self.env._(
                    "%(kind_label)s identity policy %(policy)s is bound to %(key)s, but no active value resolution rule produces that key.",
                    kind_label=self.env._("Delivery") if kind == "delivery" else self.env._("Replay"),
                    policy=policy_label,
                    key=bound_key,
                )
            )

    # -- Window actions -----------------------------------------------------

    def action_view_inbound_events(self):
        self.ensure_one()
        action = self.env.ref("bwt_webhooks_inbound.action_webhook_inbound_event").read()[0]
        action["domain"] = [
            ("endpoint_id", "=", self.id),
            ("state", "!=", "rejected"),
        ]
        action["context"] = {"default_endpoint_id": self.id}
        return action

    def action_view_rejected_events(self):
        self.ensure_one()
        action = self.env.ref("bwt_webhooks_inbound.action_webhook_inbound_event").read()[0]
        action["domain"] = [
            ("endpoint_id", "=", self.id),
            ("state", "=", "rejected"),
        ]
        action["context"] = {"default_endpoint_id": self.id}
        return action

    def _transition_state(self, *, target, allowed_from, error_message):
        if self.filtered(lambda endpoint: endpoint.state not in allowed_from):
            raise ValidationError(self.env._(error_message))
        self.write({"state": target})
        return True

    def action_activate(self):
        return self._transition_state(
            target="active",
            allowed_from=("draft",),
            error_message="Only draft inbound endpoints can be activated.",
        )

    def action_set_draft(self):
        return self._transition_state(
            target="draft",
            allowed_from=("active", "archived"),
            error_message="Only active or archived inbound endpoints can be moved to draft.",
        )

    def action_archive(self):
        return self._transition_state(
            target="archived",
            allowed_from=("draft", "active"),
            error_message="Only draft or active inbound endpoints can be archived.",
        )

    # -- Lookup -------------------------------------------------------------

    @api.model
    def _find_active_endpoint_by_path(self, path):
        return self.search([("path", "=", path), ("state", "=", "active")], limit=1)

    # -- Header / payload helpers (instance shims over module functions) ---

    def _normalize_headers(self, headers):
        return normalize_headers(headers)

    def _extract_header_value(self, headers, header_name):
        return extract_header(headers, header_name)

    def _extract_header_parameter_values(self, headers, header_name, parameter_name):
        return extract_header_parameters(headers, header_name, parameter_name)

    def _extract_payload_path_value(self, payload, path):
        return walk_payload_path(payload, path)

    # -- Computed source dispatch ------------------------------------------

    def _dispatch_computed_method(self, method_name, owner_label, *args):
        self.ensure_one()
        method = getattr(self, method_name or "", None)
        if not method:
            raise WebhookProcessingConfigurationError(
                self.env._(
                    "Computed %(owner)s method %(method)s is not implemented on endpoint %(endpoint)s.",
                    owner=owner_label,
                    method=method_name,
                    endpoint=self.display_name,
                )
            )
        return method(*args)

    def _compute_source_value(self, source_line, body, headers, payload):
        return self._dispatch_computed_method(
            source_line.computed_method,
            self.env._("source"),
            source_line,
            body,
            headers,
            payload,
        )

    def _compute_signature_part_value(self, signature_part, body, headers, payload):
        return self._dispatch_computed_method(
            signature_part.computed_method,
            self.env._("signature part"),
            signature_part,
            body,
            headers,
            payload,
        )

    # -- Semantic binding helpers -----------------------------------------

    def _get_semantic_binding_map(self):
        self.ensure_one()
        return {binding.semantic_name: (binding.value_key or "").strip() for binding in self.semantic_binding_ids if (binding.value_key or "").strip()}

    def _get_bound_value_key(self, semantic_name):
        self.ensure_one()
        return self._get_semantic_binding_map().get(semantic_name)

    def _has_active_source_for_key(self, value_key):
        self.ensure_one()
        return bool(self.source_ids.filtered(lambda line: line.active and line.field_name == value_key))

    # -- Field candidate extraction ----------------------------------------

    def _get_field_lines(self, field_name):
        """Active source lines bound to ``field_name``, sorted deterministically."""
        return self.source_ids.filtered(lambda line: line.active and line.field_name == field_name).sorted(key=lambda line: (line.candidate_sequence, line.sequence, line.id))

    def _resolve_candidate_lines(self, lines, body, headers, payload, *, allow_multiple):
        """Resolve a single candidate group (one ``candidate_sequence``).

        Returns one of:
        - ``None`` if a required line failed to produce a value.
        - A list of strings if any line produced a multi-value (header_param
          with ``allow_multiple``).
        - A single concatenated string built from the line joiner.
        """
        ordered = lines.sorted(key=lambda line: (line.sequence, line.id))
        joiner = next((line.joiner for line in ordered if line.joiner), "")
        single_values = []
        multi_values: Optional[list] = None

        for line in ordered:
            return_all = allow_multiple and line.source_kind == "header_param"
            raw = line._resolve_value(self, body, headers, payload, return_all=return_all)
            if isinstance(raw, list):
                transformed = [item for item in line._apply_transforms(raw) if item not in _BLANK_VALUES]
                if transformed:
                    multi_values = transformed
                elif line.required:
                    return None
                continue

            transformed = line._apply_transforms(raw)
            if transformed in _BLANK_VALUES:
                if line.required:
                    return None
                continue
            single_values.append(str(transformed))

        if multi_values is not None:
            return multi_values
        if single_values:
            return joiner.join(single_values)
        return ""  # All optional, no values: contributes nothing.

    def _extract_field_candidates(self, field_name, body, headers, payload, *, allow_multiple=False):
        self.ensure_one()
        lines = self._get_field_lines(field_name)
        if not lines:
            return []

        candidates: list = []
        for candidate_sequence in sorted(set(lines.mapped("candidate_sequence"))):
            group = lines.filtered(lambda line, seq=candidate_sequence: line.candidate_sequence == seq)
            resolved = self._resolve_candidate_lines(group, body, headers, payload, allow_multiple=allow_multiple)
            if resolved is None:
                continue
            if isinstance(resolved, list):
                candidates.extend(resolved)
            elif resolved != "":
                candidates.append(resolved)
        return candidates

    def _extract_field_value(self, field_name, body, headers, payload):
        candidates = self._extract_field_candidates(field_name, body, headers, payload)
        return candidates[0] if candidates else False

    def _get_configured_field_names(self):
        self.ensure_one()
        names = {(line.field_name or "").strip() for line in self.source_ids.filtered("active") if (line.field_name or "").strip()}
        return sorted(names)

    def _extract_resolved_values(self, body, headers, payload):
        self.ensure_one()
        return {field_name: self._extract_field_value(field_name, body, headers, payload) for field_name in self._get_configured_field_names()}

    # -- Semantic value extraction -----------------------------------------

    def _extract_semantic_candidates(self, semantic_name, body, headers, payload):
        self.ensure_one()
        value_key = self._get_bound_value_key(semantic_name)
        if not value_key:
            return []
        return self._extract_field_candidates(
            value_key,
            body,
            headers,
            payload,
            allow_multiple=semantic_name == "signature",
        )

    def _extract_semantic_value(self, semantic_name, body, headers, payload, *, resolved_values=None):
        self.ensure_one()
        value_key = self._get_bound_value_key(semantic_name)
        if not value_key:
            return False
        # The signature semantic always re-extracts so that multi-valued
        # ``header_param`` candidates are preserved; everything else can
        # reuse a precomputed resolved-values map.
        if semantic_name != "signature" and resolved_values is not None:
            return resolved_values.get(value_key, False)
        candidates = self._extract_semantic_candidates(semantic_name, body, headers, payload)
        return candidates[0] if candidates else False

    def _extract_inbound_metadata(self, body, headers, payload, *, resolved_values=None):
        self.ensure_one()
        if resolved_values is None:
            resolved_values = self._extract_resolved_values(body, headers, payload)
        return {
            semantic_name: self._extract_semantic_value(
                semantic_name,
                body,
                headers,
                payload,
                resolved_values=resolved_values,
            )
            for semantic_name in WEBHOOK_SEMANTIC_NAMES
        }

    # -- Identity resolution -----------------------------------------------

    def _resolve_delivery_identity(self, body_sha256, metadata):
        self.ensure_one()
        try:
            return resolve_delivery_identity(body_sha256, metadata, policy=self.delivery_identity_policy)
        except IdentityNotResolvable as exc:
            raise WebhookValidationError(
                self.env._(
                    "The configured delivery identity %(policy)s could not be resolved.",
                    policy=_DELIVERY_POLICY_LABELS[exc.policy],
                )
            ) from exc

    def _resolve_replay_identity(self, metadata):
        self.ensure_one()
        try:
            return resolve_replay_identity(metadata, policy=self.replay_identity_policy)
        except IdentityNotResolvable as exc:
            raise WebhookValidationError(
                self.env._(
                    "The configured replay identity %(policy)s could not be resolved.",
                    policy=_REPLAY_POLICY_LABELS[exc.policy],
                )
            ) from exc

    # -- Signature ----------------------------------------------------------

    def _get_signature_secrets(self):
        self.ensure_one()
        return [secret for secret in (self.signature_secret, self.signature_secondary_secret) if secret]

    def _build_signature_message(self, body, headers, payload):
        self.ensure_one()
        parts = self.signature_part_ids.filtered("active").sorted(key=lambda part: (part.sequence, part.id))
        if not parts:
            return body.decode("utf-8", errors="replace")
        values: list = []
        for part in parts:
            value = part._resolve_value(self, body, headers, payload)
            if value in _BLANK_VALUES:
                if part.required:
                    raise WebhookSignatureValidationError(self.env._("A required signature message part could not be resolved."))
                continue
            values.append(str(value))
        return (self.signature_message_joiner or "").join(values)

    def _compute_expected_signature(self, secret, message):
        self.ensure_one()
        return compute_expected_signature(
            secret,
            message,
            digest_algorithm=self.signature_digest_algorithm,
            encoding=self.signature_encoding,
        )

    def _parse_signature_timestamp(self, raw_value):
        self.ensure_one()
        return parse_signature_timestamp(raw_value, timestamp_format=self.signature_timestamp_format)

    def _validate_signature_freshness(self, raw_timestamp):
        self.ensure_one()
        if self.signature_max_age_seconds <= 0 and self.signature_max_future_skew_seconds <= 0:
            return
        if not raw_timestamp:
            raise WebhookFreshnessValidationError(self.env._("A signature timestamp is required for freshness validation."))
        received_at = self._parse_signature_timestamp(raw_timestamp)
        verdict = validate_signature_freshness(
            received_at,
            max_age_seconds=self.signature_max_age_seconds,
            max_future_skew_seconds=self.signature_max_future_skew_seconds,
        )
        if verdict == "too_old":
            raise WebhookFreshnessValidationError(self.env._("The webhook signature timestamp is too old."))
        if verdict == "too_future":
            raise WebhookFreshnessValidationError(self.env._("The webhook signature timestamp is too far in the future."))

    def _strip_signature_prefix(self, candidates) -> list:
        return strip_signature_prefix(candidates, self.signature_prefix)

    def _verify_signature(self, body, headers, payload, metadata):
        self.ensure_one()
        if self.signature_verification_mode != "hmac":
            return

        incoming = self._extract_semantic_candidates("signature", body, headers, payload)
        if not incoming:
            raise WebhookSignatureValidationError(self.env._("The webhook signature could not be resolved."))

        secrets = self._get_signature_secrets()

        message = self._build_signature_message(body, headers, payload)
        cleaned_candidates = self._strip_signature_prefix(incoming)

        if verify_signature_against_secrets(
            message,
            cleaned_candidates,
            secrets,
            digest_algorithm=self.signature_digest_algorithm,
            encoding=self.signature_encoding,
        ):
            self._validate_signature_freshness(metadata.get("signature_timestamp"))
            return

        raise WebhookSignatureValidationError(self.env._("The webhook signature could not be verified."))

    # -- Top-level inbound request validation ------------------------------

    def _validate_inbound_request(self, body, headers, payload, metadata):
        self.ensure_one()
        if self.state != "active":
            self._raise_inactive_endpoint_error()
        if self.payload_contract == "json_object" and not isinstance(payload, dict):
            raise WebhookPayloadValidationError(self.env._("This endpoint requires a top-level JSON object payload."))
        self._verify_signature(body, headers, payload, metadata)

    def _raise_inactive_endpoint_error(self):
        self.ensure_one()
        if self.state == "draft":
            raise WebhookValidationError(
                self.env._(
                    "Endpoint %(endpoint)s is in draft and cannot accept webhook deliveries.",
                    endpoint=self.display_name,
                )
            )
        raise WebhookValidationError(
            self.env._(
                "Archived endpoint %(endpoint)s cannot accept webhook deliveries.",
                endpoint=self.display_name,
            )
        )

    # -- Handler resolution -------------------------------------------------

    def _resolve_handler(self, metadata):
        self.ensure_one()
        selector = metadata.get("handler_selector")
        if selector:
            handler = self.env["bwt.webhook.handler"].search(
                [
                    ("code", "=", selector),
                    ("direction", "=", "inbound"),
                    ("active", "=", True),
                    ("company_id", "=", self.company_id.id),
                ],
                limit=1,
            )
            if handler:
                return handler
        return self.handler_id
