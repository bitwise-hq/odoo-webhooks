import hashlib

from odoo import _, api, fields, models
from odoo.exceptions import ValidationError


BUILTIN_METADATA_FIELD_NAMES = (
    'topic',
    'event_type',
    'event_id',
    'delivery_id',
    'notification_id',
    'idempotency_key',
    'signature',
    'signature_timestamp',
    'occurred_at',
    'tenant_key',
    'version',
    'resource_reference',
    'handler_selector',
)


class WebhookEndpointSource(models.Model):
    _name = 'webhook.endpoint.source'
    _description = 'Webhook Endpoint Source'
    _order = 'field_name, candidate_sequence, sequence, id'
    _SOURCE_KIND_SELECTION = [
        ('header', 'Header'),
        ('header_param', 'Structured Header Parameter'),
        ('payload_path', 'Payload Path'),
        ('literal', 'Literal'),
        ('body_sha256', 'Raw Body SHA256'),
        ('computed', 'Computed'),
    ]
    _NORMALIZE_SELECTION = [
        ('none', 'None'),
        ('strip', 'Trim Whitespace'),
        ('lower', 'Lowercase'),
        ('upper', 'Uppercase'),
    ]
    _HASH_SELECTION = [
        ('none', 'None'),
        ('sha1', 'SHA1'),
        ('sha256', 'SHA256'),
        ('sha512', 'SHA512'),
    ]

    endpoint_id = fields.Many2one('webhook.endpoint', required=True, ondelete='cascade', index=True)
    active = fields.Boolean(default=True)
    field_name = fields.Char(
        required=True,
        index=True,
        string='Field Key',
        help=(
            'Free-form key for the resolved value. Built-in keys used by the framework are: '
            'topic, event_type, event_id, delivery_id, notification_id, idempotency_key, '
            'signature, signature_timestamp, occurred_at, tenant_key, version, '
            'resource_reference, and handler_selector. Any other key is also allowed and '
            'will be stored with the inbound event.'
        ),
    )
    candidate_sequence = fields.Integer(
        default=10,
        required=True,
        help='Lines with the same field and candidate sequence are combined into one candidate value before fallback continues to the next candidate sequence.',
    )
    sequence = fields.Integer(default=10, required=True)
    joiner = fields.Char(
        default='',
        help='Text inserted between non-empty line values when multiple lines are combined for the same candidate sequence.',
    )
    source_kind = fields.Selection(selection=_SOURCE_KIND_SELECTION, required=True, default='header')
    header_name = fields.Char(help='Case-insensitive HTTP header name.')
    header_param_name = fields.Char(help='Parameter name inside a structured header such as Stripe-Signature or Paddle-Signature.')
    payload_path = fields.Char(help='Dotted path such as data.object.id or items.0.sku.')
    literal_value = fields.Char()
    computed_method = fields.Char(help='Endpoint method name used for computed sources.')
    normalize_mode = fields.Selection(selection=_NORMALIZE_SELECTION, required=True, default='none')
    hash_algorithm = fields.Selection(selection=_HASH_SELECTION, required=True, default='none')
    required = fields.Boolean(
        default=False,
        help='If enabled, a missing value invalidates this candidate sequence and fallback continues to the next candidate sequence.',
    )
    note = fields.Char()

    def _resolve_value(self, endpoint, body, headers, payload, *, return_all=False):
        self.ensure_one()
        value = False
        if self.source_kind == 'header':
            value = endpoint._extract_header_value(headers, self.header_name)
        elif self.source_kind == 'header_param':
            values = endpoint._extract_header_parameter_values(headers, self.header_name, self.header_param_name)
            value = values if return_all else (values[0] if values else False)
        elif self.source_kind == 'payload_path':
            value = endpoint._extract_payload_path_value(payload, self.payload_path)
        elif self.source_kind == 'literal':
            value = self.literal_value
        elif self.source_kind == 'body_sha256':
            value = hashlib.sha256(body).hexdigest()
        elif self.source_kind == 'computed':
            value = endpoint._compute_source_value(self, body, headers, payload)
        if return_all and not isinstance(value, list):
            return [value] if value not in (False, None, '') else []
        return value

    def _apply_transforms(self, value):
        self.ensure_one()
        if value in (False, None):
            return value
        if isinstance(value, list):
            return [self._apply_transforms(item) for item in value]
        text = str(value)
        if self.normalize_mode == 'strip':
            text = text.strip()
        elif self.normalize_mode == 'lower':
            text = text.lower()
        elif self.normalize_mode == 'upper':
            text = text.upper()
        if self.hash_algorithm != 'none':
            text = hashlib.new(self.hash_algorithm, text.encode('utf-8')).hexdigest()
        return text

    def _check_source_configuration(self):
        for line in self:
            if not (line.field_name or '').strip():
                raise ValidationError(_('Source lines require a field key.'))
            if line.source_kind in ('header', 'header_param') and not line.header_name:
                raise ValidationError(_('Header-based source lines require a header name.'))
            if line.source_kind == 'header_param' and not line.header_param_name:
                raise ValidationError(_('Structured header parameter lines require a parameter name.'))
            if line.source_kind == 'payload_path' and not line.payload_path:
                raise ValidationError(_('Payload path source lines require a payload path.'))
            if line.source_kind == 'literal' and line.literal_value in (False, None):
                raise ValidationError(_('Literal source lines require a literal value.'))
            if line.source_kind == 'computed' and not line.computed_method:
                raise ValidationError(_('Computed source lines require a computed method name.'))

    @api.model
    def _normalize_vals(self, vals):
        normalized_vals = dict(vals)
        field_name = normalized_vals.get('field_name')
        if field_name is not None:
            normalized_vals['field_name'] = field_name.strip()
        return normalized_vals

    @api.model_create_multi
    def create(self, vals_list):
        vals_list = [self._normalize_vals(vals) for vals in vals_list]
        records = super().create(vals_list)
        records._check_source_configuration()
        return records

    def write(self, vals):
        result = super().write(self._normalize_vals(vals))
        self._check_source_configuration()
        return result