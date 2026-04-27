import base64
import hashlib
import hmac
import json
import re
from datetime import datetime, timezone

from odoo import _, api, fields, models

from ..exceptions import (
    WebhookFreshnessValidationError,
    WebhookPayloadValidationError,
    WebhookProcessingConfigurationError,
    WebhookSignatureValidationError,
    WebhookValidationError,
)
from .webhook_endpoint_semantic_binding import WEBHOOK_SEMANTIC_NAMES


class WebhookEndpoint(models.Model):
    _name = 'webhook.endpoint'
    _description = 'Webhook Endpoint'
    _order = 'name, id'

    _SIGNATURE_MODE_SELECTION = [
        ('none', 'None'),
        ('hmac', 'Shared Secret HMAC'),
    ]
    _SIGNATURE_DIGEST_SELECTION = [
        ('sha1', 'SHA1'),
        ('sha256', 'SHA256'),
        ('sha512', 'SHA512'),
    ]
    _SIGNATURE_ENCODING_SELECTION = [
        ('hex', 'Hex'),
        ('base64', 'Base64'),
    ]
    _TIMESTAMP_FORMAT_SELECTION = [
        ('unix', 'Unix Seconds'),
        ('unix_ms', 'Unix Milliseconds'),
        ('iso8601', 'ISO 8601'),
    ]
    _ACCEPTANCE_KEY_POLICY_SELECTION = [
        ('legacy_fallback', 'Legacy Fallback Chain'),
        ('idempotency_key', 'Explicit Idempotency Key'),
        ('delivery_id', 'Delivery Identity'),
        ('event_id', 'Business Event Identity'),
        ('body_sha256', 'Raw Body SHA256'),
    ]

    _code_uniq = models.Constraint(
        'unique(code)',
        'The webhook endpoint code must be unique.',
    )

    name = fields.Char(required=True)
    code = fields.Char(
        required=True,
        copy=False,
        index=True,
        help='Unique identifier used in the public inbound webhook URL. Changing this value changes the route path consumed by upstream providers.',
    )
    active = fields.Boolean(
        default=True,
        help='Archived endpoints are not matched by the public inbound webhook route.',
    )
    is_paused = fields.Boolean(
        string='Paused',
        default=False,
        help='Paused endpoints keep their configuration but reject new webhook deliveries.',
    )
    company_id = fields.Many2one(
        'res.company',
        required=True,
        default=lambda self: self.env.company,
        index=True,
    )
    route_path = fields.Char(
        compute='_compute_route_path',
        string='Public Route',
        help='Computed public path derived from the endpoint code.',
    )
    handler_id = fields.Many2one(
        'webhook.handler',
        string='Default Handler',
        domain="[('inbound_enabled', '=', True)]",
        help='Fallback handler used when no handler selector resolves another handler. If this is empty and no selector resolves, the event is stored only.',
    )
    source_ids = fields.One2many(
        'webhook.endpoint.source',
        'endpoint_id',
        string='Value Resolution Rules',
        help='Ordered rules used to resolve built-in semantics and custom values from headers, payload, literals, hashes, or computed methods.',
        copy=True,
    )
    semantic_binding_ids = fields.One2many(
        'webhook.endpoint.semantic.binding',
        'endpoint_id',
        string='Semantic Bindings',
        copy=True,
        help='Maps built-in webhook semantics such as signature, delivery identity, and handler selector to resolved keys from the Value Resolution rules.',
    )
    acceptance_key_policy = fields.Selection(
        selection=_ACCEPTANCE_KEY_POLICY_SELECTION,
        required=True,
        default='legacy_fallback',
        string='Acceptance Key Policy',
        help='Select which semantic determines accepted-delivery deduplication. Legacy fallback keeps the previous idempotency_key -> delivery_id -> event_id -> body hash behavior.',
    )
    signature_verification_mode = fields.Selection(
        selection=_SIGNATURE_MODE_SELECTION,
        required=True,
        default='none',
        help='Enable shared-secret HMAC verification for incoming requests.',
    )
    signature_secret = fields.Char(
        copy=False,
        groups='base.group_system',
        help='Primary shared secret used to compute the expected webhook signature.',
    )
    signature_secondary_secret = fields.Char(
        string='Secondary Signature Secret',
        copy=False,
        groups='base.group_system',
        help='Optional secondary secret used during rotation windows.',
    )
    signature_digest_algorithm = fields.Selection(
        selection=_SIGNATURE_DIGEST_SELECTION,
        required=True,
        default='sha256',
    )
    signature_encoding = fields.Selection(
        selection=_SIGNATURE_ENCODING_SELECTION,
        required=True,
        default='hex',
    )
    signature_prefix = fields.Char(
        help='Optional prefix stripped from extracted signature values before comparison, such as v1=.',
    )
    signature_message_joiner = fields.Char(
        string='Join Signature Parts With',
        default='',
        help='Text inserted between signature message parts. If no parts are configured, the raw request body is used.',
    )
    signature_timestamp_format = fields.Selection(
        selection=_TIMESTAMP_FORMAT_SELECTION,
        required=True,
        default='unix',
        help='How the extracted signature_timestamp value should be parsed when freshness checks are enabled.',
    )
    signature_max_age_seconds = fields.Integer(
        default=300,
        help='Maximum allowed signature age in seconds. Set to 0 to disable the age check.',
    )
    signature_max_future_skew_seconds = fields.Integer(
        default=300,
        help='Maximum allowed future clock skew in seconds. Set to 0 to disable the future-skew check.',
    )
    signature_part_ids = fields.One2many(
        'webhook.endpoint.signature.part',
        'endpoint_id',
        string='Signature Message Parts',
        copy=True,
    )
    inbound_event_ids = fields.One2many('webhook.inbound.event', 'endpoint_id', string='Inbound Events')
    inbound_event_count = fields.Integer(compute='_compute_related_counts')
    rejected_event_count = fields.Integer(compute='_compute_related_counts')
    operational_state = fields.Selection(
        selection=[
            ('live', 'Live'),
            ('paused', 'Paused'),
            ('archived', 'Archived'),
        ],
        compute='_compute_admin_guidance',
        string='Operational State',
    )
    configuration_warning = fields.Text(
        compute='_compute_admin_guidance',
        string='Configuration Guidance',
        help='Human-readable guidance about the current endpoint configuration.',
    )

    @api.depends('code')
    def _compute_route_path(self):
        for endpoint in self:
            endpoint.route_path = f'/webhooks/in/{endpoint.code}' if endpoint.code else False

    def _compute_related_counts(self):
        event_model = self.env['webhook.inbound.event']
        for endpoint in self:
            endpoint.inbound_event_count = event_model.search_count([
                ('endpoint_id', '=', endpoint.id),
                ('state', '!=', 'rejected'),
            ])
            endpoint.rejected_event_count = event_model.search_count([
                ('endpoint_id', '=', endpoint.id),
                ('state', '=', 'rejected'),
            ])

    @api.depends(
        'active',
        'is_paused',
        'handler_id',
        'handler_id.execution_mode',
        'signature_verification_mode',
        'signature_secret',
        'signature_max_age_seconds',
        'signature_max_future_skew_seconds',
        'acceptance_key_policy',
        'source_ids.active',
        'source_ids.field_name',
        'semantic_binding_ids.semantic_name',
        'semantic_binding_ids.value_key',
        'signature_part_ids.active',
    )
    def _compute_admin_guidance(self):
        for endpoint in self:
            if not endpoint.active:
                endpoint.operational_state = 'archived'
            elif endpoint.is_paused:
                endpoint.operational_state = 'paused'
            else:
                endpoint.operational_state = 'live'

            messages = []
            if not endpoint.active:
                messages.append(_('Archived endpoints are not matched by the public inbound webhook route.'))
            elif endpoint.is_paused:
                messages.append(_('Paused endpoints keep their configuration but reject new deliveries.'))

            if not endpoint.handler_id:
                messages.append(_('No default handler is configured. Requests without a resolved handler selector will be stored only.'))
            elif endpoint.handler_id.execution_mode == 'low_code':
                messages.append(_('The selected default handler uses model-driven execution, which is still a placeholder in this version.'))

            binding_map = endpoint._get_semantic_binding_map()
            if endpoint.acceptance_key_policy == 'legacy_fallback':
                messages.append(_('Accepted-delivery deduplication is still using the legacy fallback chain. Bind semantics explicitly and choose a dedicated acceptance key policy when the provider contract is known.'))
            elif endpoint.acceptance_key_policy != 'body_sha256':
                acceptance_key = binding_map.get(endpoint.acceptance_key_policy)
                if not acceptance_key:
                    messages.append(
                        _('Acceptance key policy %s needs a semantic binding before deduplication becomes explicit.')
                        % dict(self._ACCEPTANCE_KEY_POLICY_SELECTION)[endpoint.acceptance_key_policy]
                    )
                elif not endpoint._has_active_source_for_key(acceptance_key):
                    messages.append(
                        _('Acceptance key policy %s is bound to %s, but no active value resolution rule currently produces that key.')
                        % (dict(self._ACCEPTANCE_KEY_POLICY_SELECTION)[endpoint.acceptance_key_policy], acceptance_key)
                    )

            if endpoint.signature_verification_mode == 'hmac':
                signature_key = binding_map.get('signature')
                timestamp_key = binding_map.get('signature_timestamp')
                if not endpoint.signature_secret:
                    messages.append(_('HMAC verification needs a primary signature secret.'))
                if not signature_key:
                    messages.append(_('HMAC verification needs a semantic binding for Signature.'))
                elif not endpoint._has_active_source_for_key(signature_key):
                    messages.append(
                        _('HMAC verification is bound to %s for Signature, but no active value resolution rule currently produces that key.')
                        % signature_key
                    )
                if (
                    (endpoint.signature_max_age_seconds > 0 or endpoint.signature_max_future_skew_seconds > 0)
                    and not timestamp_key
                ):
                    messages.append(_('Freshness checks are enabled, so add a semantic binding for Signature Timestamp or set both freshness windows to 0.'))
                elif timestamp_key and not endpoint._has_active_source_for_key(timestamp_key):
                    messages.append(
                        _('Signature Timestamp is bound to %s, but no active value resolution rule currently produces that key.')
                        % timestamp_key
                    )
                if not endpoint.signature_part_ids.filtered('active'):
                    messages.append(_('No signature message parts are configured. The raw request body will be used as the signed message.'))

            endpoint.configuration_warning = '\n'.join(messages) or False

    @api.constrains(
        'signature_verification_mode',
        'signature_secret',
        'signature_max_age_seconds',
        'signature_max_future_skew_seconds',
        'source_ids',
        'semantic_binding_ids',
        'acceptance_key_policy',
    )
    def _check_signature_configuration(self):
        for endpoint in self:
            binding_map = endpoint._get_semantic_binding_map()
            if endpoint.signature_verification_mode != 'hmac':
                if endpoint.acceptance_key_policy == 'body_sha256':
                    continue
            if endpoint.acceptance_key_policy not in ('legacy_fallback', 'body_sha256'):
                acceptance_key = binding_map.get(endpoint.acceptance_key_policy)
                if not acceptance_key:
                    raise WebhookProcessingConfigurationError(
                        _('Acceptance key policy %s requires a semantic binding.')
                        % dict(self._ACCEPTANCE_KEY_POLICY_SELECTION)[endpoint.acceptance_key_policy]
                    )
                if not endpoint._has_active_source_for_key(acceptance_key):
                    raise WebhookProcessingConfigurationError(
                        _('Acceptance key policy %s is bound to %s, but no active value resolution rule produces that key.')
                        % (dict(self._ACCEPTANCE_KEY_POLICY_SELECTION)[endpoint.acceptance_key_policy], acceptance_key)
                    )
            if endpoint.signature_verification_mode != 'hmac':
                continue
            if not endpoint.signature_secret:
                raise WebhookProcessingConfigurationError(_('HMAC verification requires a primary signature secret.'))
            signature_key = binding_map.get('signature')
            if not signature_key:
                raise WebhookProcessingConfigurationError(_('HMAC verification requires a semantic binding for Signature.'))
            if not endpoint._has_active_source_for_key(signature_key):
                raise WebhookProcessingConfigurationError(
                    _('HMAC verification is bound to %s for Signature, but no active value resolution rule produces that key.')
                    % signature_key
                )
            if endpoint.signature_max_age_seconds > 0 or endpoint.signature_max_future_skew_seconds > 0:
                timestamp_key = binding_map.get('signature_timestamp')
                if not timestamp_key:
                    raise WebhookProcessingConfigurationError(_('Freshness checks require a semantic binding for Signature Timestamp.'))
                if not endpoint._has_active_source_for_key(timestamp_key):
                    raise WebhookProcessingConfigurationError(
                        _('Freshness checks are bound to %s for Signature Timestamp, but no active value resolution rule produces that key.')
                        % timestamp_key
                    )

    def action_view_inbound_events(self):
        self.ensure_one()
        action = self.env.ref('webhooks.action_webhook_inbound_event').read()[0]
        action['domain'] = [('endpoint_id', '=', self.id), ('state', '!=', 'rejected')]
        action['context'] = {'default_endpoint_id': self.id}
        return action

    def action_view_rejected_events(self):
        self.ensure_one()
        action = self.env.ref('webhooks.action_webhook_inbound_event').read()[0]
        action['domain'] = [('endpoint_id', '=', self.id), ('state', '=', 'rejected')]
        action['context'] = {'default_endpoint_id': self.id}
        return action

    @api.model
    def _find_active_endpoint_by_code(self, code):
        return self.search([('code', '=', code), ('active', '=', True)], limit=1)

    def _normalize_headers(self, headers):
        normalized = {}
        for key, value in headers.items():
            normalized[str(key).lower()] = value
        return normalized

    def _extract_header_value(self, headers, header_name):
        if not header_name:
            return False
        normalized = self._normalize_headers(headers)
        return normalized.get(header_name.lower())

    def _extract_header_parameter_values(self, headers, header_name, parameter_name):
        if not header_name or not parameter_name:
            return []
        raw_value = self._extract_header_value(headers, header_name)
        if not raw_value:
            return []
        matches = []
        for part in re.split(r'[;,]', str(raw_value)):
            token = part.strip()
            if not token or '=' not in token:
                continue
            key, value = token.split('=', 1)
            if key.strip().lower() != parameter_name.lower():
                continue
            matches.append(value.strip().strip('"'))
        return matches

    def _extract_payload_path_value(self, payload, path):
        if not path or payload in (False, None):
            return False
        current = payload
        for segment in path.split('.'):
            if isinstance(current, list):
                if not segment.isdigit():
                    return False
                index = int(segment)
                if index >= len(current):
                    return False
                current = current[index]
                continue
            if isinstance(current, dict):
                if segment not in current:
                    return False
                current = current[segment]
                continue
            return False
        if isinstance(current, (dict, list)):
            return json.dumps(current, sort_keys=True)
        return current

    def _compute_source_value(self, source_line, body, headers, payload):
        self.ensure_one()
        method_name = source_line.computed_method or ''
        method = getattr(self, method_name, None)
        if not method:
            raise WebhookProcessingConfigurationError(
                _('Computed source method %s is not implemented on endpoint %s.')
                % (method_name, self.display_name)
            )
        return method(source_line, body, headers, payload)

    def _compute_signature_part_value(self, signature_part, body, headers, payload):
        self.ensure_one()
        method_name = signature_part.computed_method or ''
        method = getattr(self, method_name, None)
        if not method:
            raise WebhookProcessingConfigurationError(
                _('Computed signature part method %s is not implemented on endpoint %s.')
                % (method_name, self.display_name)
            )
        return method(signature_part, body, headers, payload)

    def _get_semantic_binding_map(self):
        self.ensure_one()
        return {
            binding.semantic_name: (binding.value_key or '').strip()
            for binding in self.semantic_binding_ids
            if (binding.value_key or '').strip()
        }

    def _get_bound_value_key(self, semantic_name):
        self.ensure_one()
        return self._get_semantic_binding_map().get(semantic_name)

    def _has_active_source_for_key(self, value_key):
        self.ensure_one()
        if not value_key:
            return False
        return bool(self.source_ids.filtered(lambda line: line.active and line.field_name == value_key))

    def _extract_field_candidates(self, field_name, body, headers, payload, *, allow_multiple=False):
        self.ensure_one()
        candidates = []
        field_lines = self.source_ids.filtered(
            lambda line: line.active and line.field_name == field_name
        ).sorted(key=lambda line: (line.candidate_sequence, line.sequence, line.id))
        candidate_sequences = sorted(set(field_lines.mapped('candidate_sequence')))
        for candidate_sequence in candidate_sequences:
            lines = field_lines.filtered(
                lambda line: line.candidate_sequence == candidate_sequence
            ).sorted(key=lambda line: (line.sequence, line.id))
            values = []
            multi_values = None
            candidate_invalid = False
            joiner = next((line.joiner for line in lines if line.joiner), '')
            for line in lines:
                raw_value = line._resolve_value(
                    self,
                    body,
                    headers,
                    payload,
                    return_all=allow_multiple and line.source_kind == 'header_param',
                )
                if isinstance(raw_value, list):
                    transformed = [
                        item for item in line._apply_transforms(raw_value)
                        if item not in (False, None, '')
                    ]
                    if not transformed and line.required:
                        candidate_invalid = True
                        break
                    if transformed:
                        multi_values = transformed
                    continue
                transformed = line._apply_transforms(raw_value)
                if transformed in (False, None, ''):
                    if line.required:
                        candidate_invalid = True
                        break
                    continue
                values.append(str(transformed))
            if candidate_invalid:
                continue
            if multi_values is not None:
                candidates.extend(multi_values)
                continue
            if values:
                candidates.append(joiner.join(values))
        return candidates

    def _extract_field_value(self, field_name, body, headers, payload):
        candidates = self._extract_field_candidates(field_name, body, headers, payload)
        return candidates[0] if candidates else False

    def _get_configured_field_names(self):
        self.ensure_one()
        field_names = {
            (line.field_name or '').strip()
            for line in self.source_ids.filtered('active')
            if (line.field_name or '').strip()
        }
        return sorted(field_names)

    def _extract_resolved_values(self, body, headers, payload):
        self.ensure_one()
        resolved_values = {}
        for field_name in self._get_configured_field_names():
            resolved_values[field_name] = self._extract_field_value(field_name, body, headers, payload)
        return resolved_values

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
            allow_multiple=semantic_name == 'signature',
        )

    def _extract_semantic_value(self, semantic_name, body, headers, payload, *, resolved_values=None):
        self.ensure_one()
        value_key = self._get_bound_value_key(semantic_name)
        if not value_key:
            return False
        if semantic_name != 'signature' and resolved_values is not None:
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

    def _resolve_acceptance_key(self, body_sha256, metadata):
        self.ensure_one()
        policy = self.acceptance_key_policy or 'legacy_fallback'
        if policy == 'legacy_fallback':
            for semantic_name in ('idempotency_key', 'delivery_id', 'event_id'):
                candidate = metadata.get(semantic_name)
                if candidate:
                    return candidate, semantic_name
            return body_sha256, 'body_sha256'
        if policy == 'body_sha256':
            return body_sha256, 'body_sha256'
        candidate = metadata.get(policy)
        if candidate:
            return candidate, policy
        return body_sha256, 'body_sha256'

    def _get_signature_secrets(self):
        self.ensure_one()
        return [secret for secret in [self.signature_secret, self.signature_secondary_secret] if secret]

    def _build_signature_message(self, body, headers, payload):
        self.ensure_one()
        parts = self.signature_part_ids.filtered('active').sorted(key=lambda part: (part.sequence, part.id))
        if not parts:
            return body.decode('utf-8', errors='replace')
        values = []
        for part in parts:
            value = part._resolve_value(self, body, headers, payload)
            if value in (False, None, ''):
                if part.required:
                    raise WebhookSignatureValidationError(_('A required signature message part could not be resolved.'))
                continue
            values.append(str(value))
        return (self.signature_message_joiner or '').join(values)

    def _compute_expected_signature(self, secret, message):
        self.ensure_one()
        digest = hmac.new(
            secret.encode('utf-8'),
            message.encode('utf-8'),
            getattr(hashlib, self.signature_digest_algorithm),
        ).digest()
        if self.signature_encoding == 'hex':
            return digest.hex()
        return base64.b64encode(digest).decode('utf-8')

    def _parse_signature_timestamp(self, raw_value):
        self.ensure_one()
        if raw_value in (False, None, ''):
            return False
        if self.signature_timestamp_format == 'unix':
            return datetime.fromtimestamp(int(raw_value), timezone.utc)
        if self.signature_timestamp_format == 'unix_ms':
            return datetime.fromtimestamp(int(raw_value) / 1000.0, timezone.utc)
        parsed = datetime.fromisoformat(str(raw_value).replace('Z', '+00:00'))
        if parsed.tzinfo is None:
            parsed = parsed.replace(tzinfo=timezone.utc)
        return parsed.astimezone(timezone.utc)

    def _validate_signature_freshness(self, raw_timestamp):
        self.ensure_one()
        if self.signature_max_age_seconds <= 0 and self.signature_max_future_skew_seconds <= 0:
            return
        if not raw_timestamp:
            raise WebhookFreshnessValidationError(_('A signature timestamp is required for freshness validation.'))
        received_at = self._parse_signature_timestamp(raw_timestamp)
        now = datetime.now(timezone.utc)
        age_seconds = (now - received_at).total_seconds()
        if self.signature_max_age_seconds > 0 and age_seconds > self.signature_max_age_seconds:
            raise WebhookFreshnessValidationError(_('The webhook signature timestamp is too old.'))
        if self.signature_max_future_skew_seconds > 0 and age_seconds < (-1 * self.signature_max_future_skew_seconds):
            raise WebhookFreshnessValidationError(_('The webhook signature timestamp is too far in the future.'))

    def _verify_signature(self, body, headers, payload, metadata):
        self.ensure_one()
        if self.signature_verification_mode != 'hmac':
            return
        incoming_values = self._extract_semantic_candidates('signature', body, headers, payload)
        if not incoming_values:
            raise WebhookSignatureValidationError(_('The webhook signature could not be resolved.'))
        message = self._build_signature_message(body, headers, payload)
        secrets = self._get_signature_secrets()
        if not secrets:
            raise WebhookProcessingConfigurationError(_('No signature secrets are configured for endpoint %s.') % self.display_name)
        cleaned_values = []
        for value in incoming_values:
            candidate = str(value)
            if self.signature_prefix and candidate.startswith(self.signature_prefix):
                candidate = candidate[len(self.signature_prefix):]
            cleaned_values.append(candidate)
        for secret in secrets:
            expected = self._compute_expected_signature(secret, message)
            for candidate in cleaned_values:
                if hmac.compare_digest(candidate, expected):
                    self._validate_signature_freshness(metadata.get('signature_timestamp'))
                    return
        raise WebhookSignatureValidationError(_('The webhook signature could not be verified.'))

    def _validate_inbound_request(self, body, headers, payload, metadata):
        self.ensure_one()
        if self.is_paused:
            raise WebhookValidationError(_('Endpoint %s is paused and cannot accept webhook deliveries.') % self.display_name)
        if not isinstance(payload, dict):
            raise WebhookPayloadValidationError(_('The webhook payload must be a JSON object.'))
        self._verify_signature(body, headers, payload, metadata)

    def _resolve_handler(self, metadata):
        self.ensure_one()
        selector = metadata.get('handler_selector')
        if selector:
            handler = self.env['webhook.handler'].search([
                ('code', '=', selector),
                ('inbound_enabled', '=', True),
                ('active', '=', True),
                ('company_id', '=', self.company_id.id),
            ], limit=1)
            if handler:
                return handler
        return self.handler_id