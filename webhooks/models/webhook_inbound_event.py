import hashlib
import json
import traceback

from psycopg2 import IntegrityError

from odoo import _, api, fields, models
from odoo.addons.queue_job.exception import RetryableJobError
from odoo.exceptions import ValidationError

from ..exceptions import WebhookPayloadValidationError


class WebhookInboundEvent(models.Model):
    _name = 'webhook.inbound.event'
    _description = 'Inbound Webhook Event'
    _order = 'received_at desc, id desc'

    _endpoint_dedupe_uniq = models.Constraint(
        'unique(endpoint_id, delivery_identity_key)',
        'The webhook delivery has already been stored for this endpoint.',
    )

    name = fields.Char(required=True, default=lambda self: _('Inbound Webhook Event'))
    endpoint_id = fields.Many2one('webhook.endpoint', required=True, ondelete='cascade', index=True)
    handler_id = fields.Many2one('webhook.handler', ondelete='set null', index=True)
    company_id = fields.Many2one('res.company', required=True, index=True)
    received_at = fields.Datetime(required=True, default=fields.Datetime.now, index=True)
    processed_at = fields.Datetime(index=True)
    state = fields.Selection(
        selection=[
            ('received', 'Received'),
            ('processing', 'Processing'),
            ('done', 'Done'),
            ('error', 'Error'),
            ('dead_letter', 'Dead Letter'),
            ('rejected', 'Rejected'),
        ],
        required=True,
        default='received',
        index=True,
    )
    topic = fields.Char(index=True)
    event_type = fields.Char(index=True)
    event_id = fields.Char(index=True)
    delivery_id = fields.Char(index=True)
    notification_id = fields.Char(index=True)
    idempotency_key = fields.Char(
        index=True,
        help='Resolved explicit idempotency key semantic, when configured by the endpoint.',
    )
    delivery_identity_key = fields.Char(index=True, help='Internal exact-delivery identity key used for duplicate detection.')
    delivery_identity_source = fields.Selection(
        selection=[
            ('delivery_id', 'Delivery Identity'),
            ('idempotency_key', 'Explicit Idempotency Key'),
            ('body_sha256', 'Raw Body SHA256'),
        ],
        index=True,
        help='Which semantic actually supplied the exact-delivery identity for this record.',
    )
    replay_identity_key = fields.Char(index=True, help='Business-event identity used to link distinct deliveries of the same event.')
    replay_identity_source = fields.Selection(
        selection=[
            ('event_id', 'Business Event Identity'),
            ('idempotency_key', 'Explicit Idempotency Key'),
        ],
        index=True,
        help='Which semantic supplied the replay identity for this record, when replay linking is enabled.',
    )
    delivery_kind = fields.Selection(
        selection=[
            ('primary', 'Primary Delivery'),
            ('replay', 'Replay Delivery'),
        ],
        required=True,
        default='primary',
        index=True,
        help='Whether this record is the first stored delivery for its replay identity or a later replay/redelivery.',
    )
    replayed_from_event_id = fields.Many2one('webhook.inbound.event', string='Replay Of', ondelete='set null', index=True)
    signature = fields.Char()
    signature_timestamp_raw = fields.Char(string='Signature Timestamp')
    occurred_at_raw = fields.Char(string='Occurred At')
    tenant_key = fields.Char(index=True)
    version = fields.Char()
    resource_reference = fields.Char(index=True)
    handler_selector = fields.Char()
    resolved_values_json = fields.Text(
        required=True,
        default='{}',
        help='Serialized snapshot of all resolved built-in and custom values extracted during intake.',
    )
    body_sha256 = fields.Char(required=True, index=True)
    request_body = fields.Text(required=True)
    request_headers_json = fields.Text(required=True)
    payload_json = fields.Text(required=True)
    processing_note = fields.Text()
    processing_error = fields.Text()
    rejection_category = fields.Char(index=True)
    rejection_reason = fields.Text()
    operator_action_hint = fields.Text(
        compute='_compute_operator_action_hint',
        string='Operator Guidance',
    )

    @api.depends('state', 'handler_id', 'delivery_kind', 'replayed_from_event_id', 'processing_note', 'processing_error', 'rejection_reason')
    def _compute_operator_action_hint(self):
        for event in self:
            if event.state == 'received' and event.delivery_kind == 'replay' and event.replayed_from_event_id:
                event.operator_action_hint = _(
                    'This delivery is a replay or redelivery of event %s. Queue processing only if reprocessing is safe for the downstream handler.'
                ) % event.replayed_from_event_id.display_name
            elif event.state == 'received':
                event.operator_action_hint = _('Queue processing to hand this delivery to the background worker.')
            elif event.state == 'processing':
                event.operator_action_hint = _('This delivery is currently being processed by the queue worker.')
            elif event.state == 'error':
                event.operator_action_hint = _('Review the processing error, correct the handler or endpoint configuration, then replay if it is safe to do so.')
            elif event.state == 'dead_letter':
                event.operator_action_hint = _('The handler explicitly moved this delivery to dead letter. Confirm replay is safe before resetting it.')
            elif event.state == 'rejected':
                event.operator_action_hint = _('This request was rejected during intake validation. Replay is intentionally unavailable until the endpoint configuration is fixed.')
            elif event.state == 'done' and not event.handler_id:
                event.operator_action_hint = _('This delivery was stored successfully, but no handler was resolved so no business action ran.')
            else:
                event.operator_action_hint = False

    @api.model
    def _parse_payload(self, body_text, *, raise_on_invalid=False):
        if not body_text:
            return {}
        try:
            return json.loads(body_text)
        except json.JSONDecodeError as err:
            if raise_on_invalid:
                raise WebhookPayloadValidationError(_('The webhook payload must be valid JSON.')) from err
            return False

    @api.model
    def _serialize_headers(self, headers):
        return json.dumps(dict(headers.items()), indent=2, sort_keys=True)

    @api.model
    def _serialize_payload(self, payload):
        return json.dumps(payload, indent=2, sort_keys=True)

    @api.model
    def _serialize_resolved_values(self, metadata):
        return json.dumps(metadata or {}, indent=2, sort_keys=True)

    def get_resolved_values(self):
        self.ensure_one()
        if not self.resolved_values_json:
            return {}
        try:
            return json.loads(self.resolved_values_json)
        except json.JSONDecodeError:
            return {}

    def get_resolved_value(self, field_key, default=False):
        self.ensure_one()
        return self.get_resolved_values().get(field_key, default)

    @api.model
    def _prepare_create_values_from_request(
        self,
        endpoint,
        handler,
        body,
        headers,
        payload,
        resolved_values,
        metadata,
        *,
        delivery_identity_key,
        delivery_identity_source,
        replay_identity_key,
        replay_identity_source,
        delivery_kind,
        replayed_from_event,
    ):
        body_text = body.decode('utf-8', errors='replace')
        body_sha256 = hashlib.sha256(body).hexdigest()
        return {
            'name': metadata.get('event_type') or metadata.get('topic') or endpoint.display_name or _('Inbound Webhook Event'),
            'endpoint_id': endpoint.id,
            'handler_id': handler.id if handler else False,
            'company_id': endpoint.company_id.id,
            'topic': metadata.get('topic'),
            'event_type': metadata.get('event_type'),
            'event_id': metadata.get('event_id'),
            'delivery_id': metadata.get('delivery_id'),
            'notification_id': metadata.get('notification_id'),
            'idempotency_key': metadata.get('idempotency_key'),
            'delivery_identity_key': delivery_identity_key,
            'delivery_identity_source': delivery_identity_source,
            'replay_identity_key': replay_identity_key,
            'replay_identity_source': replay_identity_source,
            'delivery_kind': delivery_kind,
            'replayed_from_event_id': replayed_from_event.id if replayed_from_event else False,
            'signature': metadata.get('signature'),
            'signature_timestamp_raw': metadata.get('signature_timestamp'),
            'occurred_at_raw': metadata.get('occurred_at'),
            'tenant_key': metadata.get('tenant_key'),
            'version': metadata.get('version'),
            'resource_reference': metadata.get('resource_reference'),
            'handler_selector': metadata.get('handler_selector'),
            'resolved_values_json': self._serialize_resolved_values(resolved_values),
            'body_sha256': body_sha256,
            'request_body': body_text,
            'request_headers_json': self._serialize_headers(headers),
            'payload_json': self._serialize_payload(payload),
            'state': 'received',
        }

    @api.model
    def _log_rejected_request(self, endpoint, body, headers, *, payload=None, rejection_category='validation', rejection_reason=None):
        body_text = body.decode('utf-8', errors='replace')
        body_sha256 = hashlib.sha256(body).hexdigest()
        payload = payload if payload is not None else self._parse_payload(body_text)
        payload_context = payload if isinstance(payload, dict) else {}
        resolved_values = endpoint._extract_resolved_values(body, headers, payload_context) if endpoint else {}
        metadata = endpoint._extract_inbound_metadata(body, headers, payload_context, resolved_values=resolved_values) if endpoint else {}
        delivery_identity_key = False
        delivery_identity_source = False
        replay_identity_key = False
        replay_identity_source = False
        if endpoint:
            try:
                delivery_identity_key, delivery_identity_source = endpoint._resolve_delivery_identity(body_sha256, metadata)
            except ValidationError:
                delivery_identity_key = False
                delivery_identity_source = False
            try:
                replay_identity_key, replay_identity_source = endpoint._resolve_replay_identity(metadata)
            except ValidationError:
                replay_identity_key = False
                replay_identity_source = False
        values = {
            'name': _('Rejected Webhook Request'),
            'endpoint_id': endpoint.id if endpoint else False,
            'handler_id': False,
            'company_id': endpoint.company_id.id if endpoint else self.env.company.id,
            'topic': metadata.get('topic'),
            'event_type': metadata.get('event_type'),
            'event_id': metadata.get('event_id'),
            'delivery_id': metadata.get('delivery_id'),
            'notification_id': metadata.get('notification_id'),
            'idempotency_key': metadata.get('idempotency_key'),
            'delivery_identity_key': delivery_identity_key,
            'delivery_identity_source': delivery_identity_source,
            'replay_identity_key': replay_identity_key,
            'replay_identity_source': replay_identity_source,
            'delivery_kind': 'primary',
            'replayed_from_event_id': False,
            'signature': metadata.get('signature'),
            'signature_timestamp_raw': metadata.get('signature_timestamp'),
            'occurred_at_raw': metadata.get('occurred_at'),
            'tenant_key': metadata.get('tenant_key'),
            'version': metadata.get('version'),
            'resource_reference': metadata.get('resource_reference'),
            'handler_selector': metadata.get('handler_selector'),
            'resolved_values_json': self._serialize_resolved_values(resolved_values),
            'body_sha256': body_sha256,
            'request_body': body_text,
            'request_headers_json': self._serialize_headers(headers),
            'payload_json': self._serialize_payload(payload or {}),
            'state': 'rejected',
            'rejection_category': rejection_category,
            'rejection_reason': rejection_reason,
        }
        return self.create(values)

    @api.model
    def _receive_webhook_request(self, endpoint, body, headers):
        endpoint.ensure_one()
        payload = False
        try:
            payload = self._parse_payload(body.decode('utf-8', errors='replace'), raise_on_invalid=True)
            if not isinstance(payload, dict):
                raise WebhookPayloadValidationError(_('The webhook payload must be a JSON object.'))
            resolved_values = endpoint._extract_resolved_values(body, headers, payload)
            metadata = endpoint._extract_inbound_metadata(body, headers, payload, resolved_values=resolved_values)
            endpoint._validate_inbound_request(body, headers, payload, metadata)

            body_sha256 = hashlib.sha256(body).hexdigest()
            delivery_identity_key, delivery_identity_source = endpoint._resolve_delivery_identity(body_sha256, metadata)
            replay_identity_key, replay_identity_source = endpoint._resolve_replay_identity(metadata)
            existing = self.search([
                ('endpoint_id', '=', endpoint.id),
                ('delivery_identity_key', '=', delivery_identity_key),
            ], limit=1)
            if existing:
                if existing.state in ('received', 'error'):
                    existing._queue_processing()
                return existing

            replayed_from_event = False
            delivery_kind = 'primary'
            if replay_identity_key:
                replayed_from_event = self.search([
                    ('endpoint_id', '=', endpoint.id),
                    ('replay_identity_key', '=', replay_identity_key),
                    ('state', '!=', 'rejected'),
                ], order='received_at asc, id asc', limit=1)
                if replayed_from_event:
                    delivery_kind = 'replay'

            handler = endpoint._resolve_handler(metadata)
            values = self._prepare_create_values_from_request(
                endpoint,
                handler,
                body,
                headers,
                payload,
                resolved_values,
                metadata,
                delivery_identity_key=delivery_identity_key,
                delivery_identity_source=delivery_identity_source,
                replay_identity_key=replay_identity_key,
                replay_identity_source=replay_identity_source,
                delivery_kind=delivery_kind,
                replayed_from_event=replayed_from_event,
            )
            try:
                with self.env.cr.savepoint():
                    event = self.create(values)
            except IntegrityError:
                event = self.search([
                    ('endpoint_id', '=', endpoint.id),
                    ('delivery_identity_key', '=', delivery_identity_key),
                ], limit=1)

            if event and event.state in ('received', 'error'):
                event._queue_processing()
            return event
        except ValidationError as err:
            self._log_rejected_request(
                endpoint,
                body,
                headers,
                payload=payload if isinstance(payload, dict) else None,
                rejection_category=getattr(err, 'rejection_category', 'validation'),
                rejection_reason=str(err),
            )
            raise

    def _queue_processing(self):
        for event in self:
            if event.state not in ('received', 'error'):
                continue
            event.with_delay(identity_key=f'webhook_inbound_event_process:{event.id}').process_event()

    def action_queue_processing(self):
        self._queue_processing()
        return True

    def action_reset_to_received(self):
        for event in self:
            if event.state == 'rejected':
                raise ValidationError(_('Rejected webhook events cannot be reset to received.'))
            event.write({
                'state': 'received',
                'processing_error': False,
                'processing_note': False,
                'processed_at': False,
            })
        return True

    def _execute_low_code_handler(self, handler):
        self.ensure_one()
        self.write({
            'processing_note': _('Low-code handler %s is configured but action execution is not implemented yet.') % handler.display_name,
        })
        return {'status': 'done'}

    def process_event(self):
        for event in self:
            if event.state in ('done', 'rejected', 'dead_letter'):
                continue
            if not event.handler_id:
                event.write({
                    'state': 'done',
                    'processed_at': fields.Datetime.now(),
                    'processing_note': _('No handler was resolved. The event was stored only.'),
                    'processing_error': False,
                })
                continue
            try:
                event.write({'state': 'processing', 'processing_error': False})
                result = event.handler_id.execute_inbound(event)
                if isinstance(result, dict):
                    status = result.get('status', 'done')
                    note = result.get('note') or result.get('message')
                    if status == 'retry':
                        event.write({
                            'state': 'received',
                            'processing_note': note or False,
                        })
                        raise RetryableJobError(note or _('Retry requested by handler.'), seconds=result.get('seconds'))
                    if status == 'dead_letter':
                        event.write({
                            'state': 'dead_letter',
                            'processed_at': fields.Datetime.now(),
                            'processing_note': note or False,
                        })
                        continue
                    if status == 'received':
                        event.write({
                            'state': 'received',
                            'processing_note': note or False,
                        })
                        continue
                    event.write({
                        'state': 'done',
                        'processed_at': fields.Datetime.now(),
                        'processing_note': note or False,
                    })
                    continue
                if result is False:
                    event.write({'state': 'received'})
                    continue
                event.write({
                    'state': 'done',
                    'processed_at': fields.Datetime.now(),
                    'processing_note': False,
                })
            except RetryableJobError:
                raise
            except Exception:
                event.write({
                    'state': 'error',
                    'processing_error': traceback.format_exc(),
                })
                raise
        return True