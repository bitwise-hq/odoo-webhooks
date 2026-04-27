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
        'unique(endpoint_id, accepted_idempotency_key)',
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
    idempotency_key = fields.Char(index=True)
    accepted_idempotency_key = fields.Char(index=True)
    signature = fields.Char()
    signature_timestamp_raw = fields.Char(string='Signature Timestamp')
    occurred_at_raw = fields.Char(string='Occurred At')
    tenant_key = fields.Char(index=True)
    version = fields.Char()
    resource_reference = fields.Char(index=True)
    handler_selector = fields.Char()
    resolved_values_json = fields.Text(required=True, default='{}')
    body_sha256 = fields.Char(required=True, index=True)
    request_body = fields.Text(required=True)
    request_headers_json = fields.Text(required=True)
    payload_json = fields.Text(required=True)
    processing_note = fields.Text()
    processing_error = fields.Text()
    rejection_category = fields.Char(index=True)
    rejection_reason = fields.Text()

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
    def _prepare_create_values_from_request(self, endpoint, handler, body, headers, payload, metadata):
        body_text = body.decode('utf-8', errors='replace')
        body_sha256 = hashlib.sha256(body).hexdigest()
        idempotency_key = metadata.get('idempotency_key') or metadata.get('delivery_id') or metadata.get('event_id') or body_sha256
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
            'idempotency_key': idempotency_key,
            'accepted_idempotency_key': idempotency_key,
            'signature': metadata.get('signature'),
            'signature_timestamp_raw': metadata.get('signature_timestamp'),
            'occurred_at_raw': metadata.get('occurred_at'),
            'tenant_key': metadata.get('tenant_key'),
            'version': metadata.get('version'),
            'resource_reference': metadata.get('resource_reference'),
            'handler_selector': metadata.get('handler_selector'),
            'resolved_values_json': self._serialize_resolved_values(metadata),
            'body_sha256': body_sha256,
            'request_body': body_text,
            'request_headers_json': self._serialize_headers(headers),
            'payload_json': self._serialize_payload(payload),
            'state': 'received',
        }

    @api.model
    def _log_rejected_request(self, endpoint, body, headers, *, payload=None, rejection_category='validation', rejection_reason=None):
        body_text = body.decode('utf-8', errors='replace')
        payload = payload if payload is not None else self._parse_payload(body_text)
        metadata = endpoint._extract_inbound_metadata(body, headers, payload or {}) if endpoint and isinstance(payload, dict) else {}
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
            'accepted_idempotency_key': False,
            'signature': metadata.get('signature'),
            'signature_timestamp_raw': metadata.get('signature_timestamp'),
            'occurred_at_raw': metadata.get('occurred_at'),
            'tenant_key': metadata.get('tenant_key'),
            'version': metadata.get('version'),
            'resource_reference': metadata.get('resource_reference'),
            'handler_selector': metadata.get('handler_selector'),
            'resolved_values_json': self._serialize_resolved_values(metadata),
            'body_sha256': hashlib.sha256(body).hexdigest(),
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
            metadata = endpoint._extract_inbound_metadata(body, headers, payload)
            endpoint._validate_inbound_request(body, headers, payload, metadata)

            body_sha256 = hashlib.sha256(body).hexdigest()
            idempotency_key = metadata.get('idempotency_key') or metadata.get('delivery_id') or metadata.get('event_id') or body_sha256
            existing = self.search([
                ('endpoint_id', '=', endpoint.id),
                ('accepted_idempotency_key', '=', idempotency_key),
            ], limit=1)
            if existing:
                if existing.state in ('received', 'error'):
                    existing._queue_processing()
                return existing

            handler = endpoint._resolve_handler(metadata)
            values = self._prepare_create_values_from_request(endpoint, handler, body, headers, payload, metadata)
            try:
                with self.env.cr.savepoint():
                    event = self.create(values)
            except IntegrityError:
                event = self.search([
                    ('endpoint_id', '=', endpoint.id),
                    ('accepted_idempotency_key', '=', idempotency_key),
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