import hashlib
import json
import traceback

from psycopg2 import IntegrityError

from odoo import SUPERUSER_ID, _, api, fields, models
from odoo.addons.queue_job.exception import RetryableJobError
from odoo.exceptions import ValidationError

from ..exceptions import WebhookPayloadValidationError


class WebhookInboundEvent(models.Model):
    _name = 'webhook.inbound.event'
    _inherit = ['mail.thread', 'mail.activity.mixin']
    _description = 'Inbound Webhook Event'
    _order = 'received_at desc, id desc'
    _check_company_auto = True

    _endpoint_dedupe_uniq = models.Constraint(
        'unique(endpoint_id, delivery_identity_key)',
        'The webhook delivery has already been stored for this endpoint.',
    )

    name = fields.Char(required=True, default=lambda self: _('Inbound Webhook Event'))
    endpoint_id = fields.Many2one('webhook.endpoint', required=True, ondelete='cascade', index=True, check_company=True)
    execution_user_id = fields.Many2one(
        'res.users',
        required=True,
        ondelete='restrict',
        index=True,
        check_company=True,
        string='Execution User',
        help='Accepted request creation and queued processing run as this user.',
    )
    handler_id = fields.Many2one('webhook.handler', ondelete='set null', index=True, check_company=True, tracking=True)
    company_id = fields.Many2one('res.company', required=True, index=True)
    partner_id = fields.Many2one(
        'res.partner',
        index=True,
        check_company=True,
        help='Resolved tenant/account partner for this webhook event, when the endpoint scope is partner-aware.',
    )
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
        tracking=True,
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
    replayed_from_event_id = fields.Many2one(
        'webhook.inbound.event',
        string='Replay Of',
        ondelete='set null',
        index=True,
        check_company=True,
        tracking=True,
    )
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
    matched_inbound_rule_id = fields.Many2one('webhook.handler.inbound.rule', string='Matched Rule', ondelete='set null', index=True, tracking=True)
    rule_execution_ids = fields.One2many('webhook.inbound.rule.execution', 'event_id', string='Rule Executions')
    rejection_category = fields.Char(index=True)
    rejection_reason = fields.Text()
    operator_action_hint = fields.Text(
        compute='_compute_operator_action_hint',
        string='Operator Guidance',
    )
    queue_job_identity_key = fields.Char(
        compute='_compute_queue_job_identity_key',
        string='Queue Job Identity Key',
        help='Identity key used when enqueuing background processing for this event.',
    )
    queue_job_ids = fields.Many2many('queue.job', compute='_compute_queue_job_observability', string='Queue Jobs')
    queue_job_count = fields.Integer(compute='_compute_queue_job_observability', string='Queue Jobs')
    latest_queue_job_id = fields.Many2one('queue.job', compute='_compute_queue_job_observability', string='Latest Queue Job')
    latest_queue_job_state = fields.Char(compute='_compute_queue_job_observability', string='Latest Queue Job State')

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

    def _compute_queue_job_identity_key(self):
        for event in self:
            event.queue_job_identity_key = event._get_queue_job_identity_key() if event.id else False

    @api.depends('queue_job_identity_key')
    def _compute_queue_job_observability(self):
        job_model = self.env['queue.job']
        jobs_by_key = {}
        identity_keys = [key for key in self.mapped('queue_job_identity_key') if key]
        if identity_keys:
            jobs = job_model.search([
                ('identity_key', 'in', identity_keys),
                ('model_name', '=', 'webhook.inbound.event'),
                ('method_name', '=', 'process_event'),
            ], order='date_created desc, id desc')
            for job in jobs:
                jobs_by_key.setdefault(job.identity_key, job_model.browse())
                jobs_by_key[job.identity_key] |= job
        for event in self:
            jobs = jobs_by_key.get(event.queue_job_identity_key, job_model.browse())
            event.queue_job_ids = jobs
            event.queue_job_count = len(jobs)
            event.latest_queue_job_id = jobs[:1]
            event.latest_queue_job_state = jobs[:1].state if jobs else False

    @api.model
    def _get_runtime_execution_user_id(self):
        if self.env.uid == SUPERUSER_ID or self.env.context.get('webhook_automated_execution'):
            return SUPERUSER_ID
        return self.env.user.id

    def _get_queue_job_identity_key(self):
        self.ensure_one()
        return f'webhook_inbound_event_process:{self.id}' if self.id else False

    def _get_queue_job_action_domain(self):
        self.ensure_one()
        if not self.queue_job_identity_key:
            return [('id', '=', 0)]
        return [
            ('identity_key', '=', self.queue_job_identity_key),
            ('model_name', '=', 'webhook.inbound.event'),
            ('method_name', '=', 'process_event'),
        ]

    def action_view_queue_jobs(self):
        self.ensure_one()
        action = self.env.ref('queue_job.action_queue_job').read()[0]
        action['name'] = _('Inbound Queue Jobs')
        action['domain'] = self._get_queue_job_action_domain()
        return action

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
        partner = endpoint._get_scoped_partner()
        return {
            'name': metadata.get('event_type') or metadata.get('topic') or endpoint.display_name or _('Inbound Webhook Event'),
            'endpoint_id': endpoint.id,
            'execution_user_id': self._get_runtime_execution_user_id(),
            'handler_id': handler.id if handler else False,
            'company_id': endpoint.company_id.id,
            'partner_id': partner.id if partner else False,
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
    def _log_rejected_request(
        self,
        endpoint,
        body,
        headers,
        *,
        payload=None,
        payload_parse_failed=False,
        rejection_category='validation',
        rejection_reason=None,
    ):
        body_text = body.decode('utf-8', errors='replace')
        body_sha256 = hashlib.sha256(body).hexdigest()
        if payload_parse_failed:
            stored_payload = {}
            payload_context = {}
        else:
            payload = payload if payload is not None else self._parse_payload(body_text)
            stored_payload = payload if payload is not None else {}
            payload_context = payload if payload is not None else {}
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
            'execution_user_id': self._get_runtime_execution_user_id(),
            'handler_id': False,
            'company_id': endpoint.company_id.id if endpoint else self.env.company.id,
            'partner_id': endpoint._get_scoped_partner().id if endpoint else False,
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
            'payload_json': self._serialize_payload(stored_payload),
            'state': 'rejected',
            'rejection_category': rejection_category,
            'rejection_reason': rejection_reason,
        }
        return self.create(values)

    @api.model
    def _receive_webhook_request(self, endpoint, body, headers):
        endpoint.ensure_one()
        payload = None
        payload_was_parsed = False
        try:
            payload = self._parse_payload(body.decode('utf-8', errors='replace'), raise_on_invalid=True)
            payload_was_parsed = True
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
                payload=payload if payload_was_parsed else None,
                payload_parse_failed=not payload_was_parsed,
                rejection_category=getattr(err, 'rejection_category', 'validation'),
                rejection_reason=str(err),
            )
            raise

    def _queue_processing(self):
        for event in self:
            if event.state not in ('received', 'error'):
                continue
            runtime_user_id = event._get_runtime_execution_user_id()
            write_vals = {'processing_error': False}
            if event.execution_user_id.id != runtime_user_id:
                write_vals['execution_user_id'] = runtime_user_id
            event.write(write_vals)
            event.with_user(runtime_user_id).with_delay(identity_key=event._get_queue_job_identity_key()).process_event()

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
                'matched_inbound_rule_id': False,
            })
        return True

    def _execute_model_driven_handler(self, handler):
        self.ensure_one()
        rules = handler.inbound_rule_ids.filtered('active').sorted(key=lambda record: (record.sequence, record.id))
        matched_rule = False
        for rule in rules:
            if all(self._inbound_condition_matches(condition) for condition in rule.condition_ids.sorted(key=lambda record: (record.sequence, record.id))):
                matched_rule = rule
                break

        if not matched_rule:
            return {
                'status': 'done',
                'note': _('No inbound model-driven rule matched on handler %s. The event was stored only.') % handler.display_name,
            }

        execution = self.env['webhook.inbound.rule.execution'].create({
            'name': '%s / %s' % (self.display_name, matched_rule.display_name),
            'event_id': self.id,
            'rule_id': matched_rule.id,
            'state': 'matched',
            'note': matched_rule.note or False,
        })

        try:
            if matched_rule.action_type == 'done':
                execution.write({'state': 'done'})
                return {
                    'status': 'done',
                    'note': matched_rule.note or False,
                    'matched_rule_id': matched_rule.id,
                }
            if matched_rule.action_type == 'dead_letter':
                execution.write({'state': 'done'})
                return {
                    'status': 'dead_letter',
                    'note': matched_rule.note or False,
                    'matched_rule_id': matched_rule.id,
                }
            if matched_rule.action_type == 'retry':
                execution.write({'state': 'done'})
                return {
                    'status': 'retry',
                    'note': matched_rule.note or False,
                    'seconds': matched_rule.retry_seconds or False,
                    'matched_rule_id': matched_rule.id,
                }
            if matched_rule.action_type in ('create_record', 'update_record', 'upsert_record'):
                model = self.env[matched_rule.target_model_name]
                values = self._build_inbound_assignment_values(matched_rule, target_kind='field')
                target_record = False
                if matched_rule.action_type in ('update_record', 'upsert_record'):
                    domain = self._build_inbound_lookup_domain(matched_rule)
                    target_record = model.search(domain, limit=1)
                if matched_rule.action_type == 'create_record':
                    target_record = model.create(values)
                elif matched_rule.action_type == 'update_record':
                    if not target_record:
                        raise ValidationError(_('No target record matched inbound update rule %s.') % matched_rule.display_name)
                    target_record.write(values)
                elif target_record:
                    target_record.write(values)
                else:
                    target_record = model.create(values)
                record_reference = '%s:%s' % (target_record._name, target_record.id)
                execution.write({
                    'state': 'done',
                    'record_reference': record_reference,
                })
                return {
                    'status': 'done',
                    'note': matched_rule.note or record_reference,
                    'matched_rule_id': matched_rule.id,
                }
            if matched_rule.action_type == 'queue_outbound':
                endpoint = matched_rule.outbound_endpoint_id
                delivery = self.env['webhook.outbound.delivery'].create({
                    'name': '%s / %s' % (endpoint.display_name, self.display_name),
                    'endpoint_id': endpoint.id,
                })
                context_values = self._build_inbound_assignment_values(matched_rule, target_kind='context_key')
                for key_name, value in context_values.items():
                    self.env['webhook.outbound.delivery.context.line'].create({
                        'delivery_id': delivery.id,
                        'key_name': key_name,
                        'source_kind': 'literal',
                        'literal_value': json.dumps(value) if not isinstance(value, str) else value,
                    })
                delivery.action_queue_delivery()
                record_reference = '%s:%s' % (delivery._name, delivery.id)
                execution.write({
                    'state': 'done',
                    'record_reference': record_reference,
                })
                return {
                    'status': 'done',
                    'note': matched_rule.note or record_reference,
                    'matched_rule_id': matched_rule.id,
                }
            execution.write({'state': 'skipped'})
            return {
                'status': 'done',
                'note': _('Inbound rule %s is defined but its action is not executable yet.') % matched_rule.display_name,
                'matched_rule_id': matched_rule.id,
            }
        except Exception:
            execution.write({
                'state': 'error',
                'error': traceback.format_exc(),
            })
            raise

    def _decode_literal_value(self, value):
        if value in (False, None, '') or not isinstance(value, str):
            return value
        try:
            return json.loads(value)
        except json.JSONDecodeError:
            return value

    def _resolve_inbound_source_value(self, source_kind, source_expression=False, literal_value=False):
        self.ensure_one()
        if source_kind == 'literal':
            return self._decode_literal_value(literal_value)
        if source_kind == 'resolved_value':
            return self.get_resolved_value(source_expression)
        if source_kind in ('semantic_field', 'event_field'):
            return getattr(self, source_expression)
        return False

    def _inbound_condition_matches(self, condition):
        actual_value = self._resolve_inbound_source_value(condition.source_kind, condition.source_expression)
        if condition.operator == 'is_set':
            return actual_value not in (False, None, '')
        if condition.operator == 'not_set':
            return actual_value in (False, None, '')
        actual_text = '' if actual_value in (False, None) else str(actual_value)
        expected_text = condition.expected_value or ''
        if condition.operator == 'equals':
            return actual_text == expected_text
        if condition.operator == 'not_equals':
            return actual_text != expected_text
        if condition.operator == 'contains':
            return expected_text in actual_text
        raise ValidationError(_('Unsupported inbound rule condition operator %s.') % condition.operator)

    def _build_inbound_lookup_domain(self, rule):
        self.ensure_one()
        domain = []
        for lookup in rule.lookup_ids.sorted(key=lambda record: (record.sequence, record.id)):
            value = self._resolve_inbound_source_value(lookup.source_kind, lookup.source_expression, lookup.literal_value)
            domain.append((lookup.target_field_name, '=', value))
        return domain

    def _build_inbound_assignment_values(self, rule, *, target_kind):
        self.ensure_one()
        values = {}
        for assignment in rule.assignment_ids.filtered(lambda record: record.target_kind == target_kind).sorted(key=lambda record: (record.sequence, record.id)):
            values[assignment.target_expression] = self._resolve_inbound_source_value(
                assignment.source_kind,
                assignment.source_expression,
                assignment.literal_value,
            )
        return values

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
                    matched_rule_id = result.get('matched_rule_id') or False
                    if status == 'retry':
                        event.write({
                            'state': 'received',
                            'processing_note': note or False,
                            'matched_inbound_rule_id': matched_rule_id,
                        })
                        raise RetryableJobError(note or _('Retry requested by handler.'), seconds=result.get('seconds'))
                    if status == 'dead_letter':
                        event.write({
                            'state': 'dead_letter',
                            'processed_at': fields.Datetime.now(),
                            'processing_note': note or False,
                            'matched_inbound_rule_id': matched_rule_id,
                        })
                        continue
                    if status == 'received':
                        event.write({
                            'state': 'received',
                            'processing_note': note or False,
                            'matched_inbound_rule_id': matched_rule_id,
                        })
                        continue
                    event.write({
                        'state': 'done',
                        'processed_at': fields.Datetime.now(),
                        'processing_note': note or False,
                        'matched_inbound_rule_id': matched_rule_id,
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