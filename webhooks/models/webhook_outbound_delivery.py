import json
import traceback

import requests

from odoo import _, api, fields, models
from odoo.addons.queue_job.exception import RetryableJobError
from odoo.exceptions import ValidationError

from ..exceptions import WebhookProcessingConfigurationError


class WebhookOutboundDelivery(models.Model):
    _name = 'webhook.outbound.delivery'
    _description = 'Outbound Webhook Delivery'
    _order = 'create_date desc, id desc'
    _check_company_auto = True

    _HTTP_METHOD_SELECTION = [
        ('post', 'POST'),
        ('put', 'PUT'),
        ('patch', 'PATCH'),
    ]

    name = fields.Char(required=True, default=lambda self: _('Outbound Webhook Delivery'))
    endpoint_id = fields.Many2one('webhook.outbound.endpoint', required=True, ondelete='cascade', index=True, check_company=True)
    execution_user_id = fields.Many2one(
        'res.users',
        required=True,
        ondelete='restrict',
        index=True,
        check_company=True,
        string='Execution User',
        help='Queued outbound delivery processing runs as this user.',
    )
    handler_id = fields.Many2one('webhook.handler', ondelete='set null', index=True, check_company=True)
    company_id = fields.Many2one('res.company', required=True, index=True)
    partner_id = fields.Many2one(
        'res.partner',
        index=True,
        check_company=True,
        help='Endpoint-level tenant/account partner inherited by this outbound delivery.',
    )
    state = fields.Selection(
        selection=[
            ('draft', 'Draft'),
            ('queued', 'Queued'),
            ('processing', 'Processing'),
            ('done', 'Done'),
            ('error', 'Error'),
            ('dead_letter', 'Dead Letter'),
            ('canceled', 'Canceled'),
        ],
        required=True,
        default='draft',
        index=True,
    )
    queued_at = fields.Datetime(index=True)
    processed_at = fields.Datetime(index=True)
    http_method = fields.Selection(selection=_HTTP_METHOD_SELECTION, required=True, default='post', string='HTTP Method')
    target_url = fields.Char(required=True, string='Target URL')
    timeout_seconds = fields.Integer(required=True, default=30)
    request_headers_json = fields.Text(required=True, default='{}', string='Request Headers')
    payload_json = fields.Text(required=True, default='{}', string='Payload JSON')
    response_status_code = fields.Integer(index=True, string='Response Status')
    response_headers_json = fields.Text(string='Response Headers')
    response_body = fields.Text(string='Response Body')
    processing_note = fields.Text()
    processing_error = fields.Text()
    matched_outbound_rule_id = fields.Many2one('webhook.handler.outbound.rule', string='Matched Rule', ondelete='set null', index=True)
    replayed_from_delivery_id = fields.Many2one(
        'webhook.outbound.delivery',
        string='Replay Of',
        ondelete='set null',
        index=True,
        check_company=True,
    )
    replay_delivery_ids = fields.One2many('webhook.outbound.delivery', 'replayed_from_delivery_id', string='Replay Deliveries')
    replay_count = fields.Integer(compute='_compute_replay_count')
    context_line_ids = fields.One2many('webhook.outbound.delivery.context.line', 'delivery_id', string='Context Lines')
    attempt_ids = fields.One2many('webhook.outbound.delivery.attempt', 'delivery_id', string='Attempts')
    attempt_count = fields.Integer(compute='_compute_attempt_count')
    operator_action_hint = fields.Text(compute='_compute_operator_action_hint', string='Operator Guidance')
    template_guidance = fields.Text(compute='_compute_template_guidance', string='Template Guidance')
    queue_job_identity_key = fields.Char(
        compute='_compute_queue_job_identity_key',
        string='Queue Job Identity Key',
        help='Identity key used when enqueuing background delivery processing for this outbound delivery.',
    )

    @api.depends('state', 'handler_id', 'replayed_from_delivery_id', 'processing_note', 'processing_error', 'response_status_code')
    def _compute_operator_action_hint(self):
        for delivery in self:
            if delivery.state == 'draft':
                delivery.operator_action_hint = _('Queue this delivery to send the stored payload to the configured outbound endpoint.')
            elif delivery.state == 'queued':
                delivery.operator_action_hint = _('This delivery is queued and waiting for the background worker.')
            elif delivery.state == 'processing':
                delivery.operator_action_hint = _('This delivery is currently being processed by the queue worker.')
            elif delivery.state == 'error':
                delivery.operator_action_hint = _('Review the delivery error, adjust the endpoint, templates, or low-code handler if needed, then reset to draft or create a replay when the remote system allows another send.')
            elif delivery.state == 'dead_letter':
                delivery.operator_action_hint = _('The remote endpoint returned a non-retryable failure. Confirm replay is safe before resetting this delivery or creating a new replay copy.')
            elif delivery.state == 'canceled':
                delivery.operator_action_hint = _('This delivery was canceled before sending. Reset it to draft or create a replay copy if you need a fresh audited send.')
            elif delivery.state == 'done':
                if delivery.replayed_from_delivery_id:
                    delivery.operator_action_hint = _('This delivery is a replay of %s. Create another replay only if the downstream system accepts duplicates.') % delivery.replayed_from_delivery_id.display_name
                else:
                    delivery.operator_action_hint = _('This delivery completed successfully. Use Create Replay only when the downstream system allows a new audited send of the same business event.')
            else:
                delivery.operator_action_hint = False

    @api.depends('attempt_ids')
    def _compute_attempt_count(self):
        for delivery in self:
            delivery.attempt_count = len(delivery.attempt_ids)

    @api.depends('replay_delivery_ids')
    def _compute_replay_count(self):
        for delivery in self:
            delivery.replay_count = len(delivery.replay_delivery_ids)

    @api.depends(
        'handler_id',
        'handler_id.execution_mode',
        'replayed_from_delivery_id',
        'context_line_ids.active',
        'endpoint_id.header_rule_ids.active',
        'endpoint_id.payload_rule_ids.active',
    )
    def _compute_template_guidance(self):
        for delivery in self:
            messages = [
                _('Header Rules and Payload Rules on the endpoint build the base request snapshot without authored JSON.'),
                _('Context Lines on this delivery provide additional named values that outbound handler rules can consume when deciding how to send, cancel, dead-letter, or retry.'),
            ]
            if delivery.replayed_from_delivery_id:
                messages.append(_('This delivery was created as a replay of %s. Its context lines and request snapshot were copied from that delivery.') % delivery.replayed_from_delivery_id.display_name)
            delivery.template_guidance = '\n'.join(messages)

    def _compute_queue_job_identity_key(self):
        for delivery in self:
            delivery.queue_job_identity_key = delivery._get_queue_job_identity_key() if delivery.id else False

    def _get_queue_job_identity_key(self):
        self.ensure_one()
        return f'webhook_outbound_delivery_process:{self.id}' if self.id else False

    def _get_next_replay_number(self):
        self.ensure_one()
        return self.env['webhook.outbound.delivery'].search_count([
            ('replayed_from_delivery_id', '=', self.id),
        ]) + 1

    @api.model
    def _normalize_headers_json(self, value, *, label='Request Headers'):
        try:
            headers = json.loads(value or '{}')
        except json.JSONDecodeError as err:
            raise ValidationError(_('%s must be valid JSON.') % label) from err
        if not isinstance(headers, dict):
            raise ValidationError(_('%s must be a JSON object.') % label)
        return json.dumps({str(key): str(header_value) for key, header_value in headers.items()}, indent=2, sort_keys=True)

    @api.model
    def _normalize_payload_json(self, value, *, label='Payload JSON'):
        try:
            payload = json.loads(value or '{}')
        except json.JSONDecodeError as err:
            raise ValidationError(_('%s must be valid JSON.') % label) from err
        return json.dumps(payload, indent=2, sort_keys=True)

    @api.model
    def _prepare_endpoint_snapshot_vals(self, endpoint, vals):
        prepared_vals = dict(vals)
        prepared_vals.setdefault('execution_user_id', endpoint.execution_user_id.id)
        prepared_vals.setdefault('handler_id', endpoint.handler_id.id if endpoint.handler_id else False)
        prepared_vals.setdefault('company_id', endpoint.company_id.id)
        prepared_vals.setdefault('partner_id', endpoint._get_scoped_partner().id if endpoint._get_scoped_partner() else False)
        prepared_vals.setdefault('http_method', endpoint.http_method)
        prepared_vals.setdefault('target_url', endpoint.target_url)
        prepared_vals.setdefault('timeout_seconds', endpoint.timeout_seconds)
        prepared_vals.setdefault('request_headers_json', '{}')
        prepared_vals.setdefault('payload_json', '{}')
        prepared_vals.setdefault('name', '%s / %s' % (endpoint.display_name, fields.Datetime.now()))
        return prepared_vals

    @api.model_create_multi
    def create(self, vals_list):
        prepared_vals_list = []
        for vals in vals_list:
            prepared_vals = dict(vals)
            endpoint_id = prepared_vals.get('endpoint_id')
            if endpoint_id:
                endpoint = self.env['webhook.outbound.endpoint'].browse(endpoint_id)
                prepared_vals = self._prepare_endpoint_snapshot_vals(endpoint, prepared_vals)
            prepared_vals['request_headers_json'] = self._normalize_headers_json(prepared_vals.get('request_headers_json'))
            prepared_vals['payload_json'] = self._normalize_payload_json(prepared_vals.get('payload_json'))
            prepared_vals_list.append(prepared_vals)
        return super().create(prepared_vals_list)

    def write(self, vals):
        prepared_vals = dict(vals)
        if 'request_headers_json' in prepared_vals:
            prepared_vals['request_headers_json'] = self._normalize_headers_json(prepared_vals.get('request_headers_json'))
        if 'payload_json' in prepared_vals:
            prepared_vals['payload_json'] = self._normalize_payload_json(prepared_vals.get('payload_json'))
        return super().write(prepared_vals)

    def _get_request_headers(self):
        self.ensure_one()
        try:
            return json.loads(self.request_headers_json or '{}')
        except json.JSONDecodeError as err:
            raise WebhookProcessingConfigurationError(_('Request Headers must be valid JSON.')) from err

    def _get_payload(self):
        self.ensure_one()
        try:
            return json.loads(self.payload_json or '{}')
        except json.JSONDecodeError as err:
            raise WebhookProcessingConfigurationError(_('Payload JSON must be valid JSON.')) from err

    def _resolve_expression_value(self, source, expression):
        current = source
        for token in (expression or '').split('.'):
            if token == '':
                continue
            if isinstance(current, dict):
                current = current.get(token)
            else:
                current = getattr(current, token)
            if not current:
                break
        if isinstance(current, models.BaseModel):
            if len(current) == 1:
                return current.id
            return current.ids
        return current

    def _decode_literal_value(self, value):
        if value in (False, None, '') or not isinstance(value, str):
            return value
        try:
            return json.loads(value)
        except json.JSONDecodeError:
            return value

    def _get_context_values(self):
        self.ensure_one()
        values = {}
        for line in self.context_line_ids.filtered('active').sorted(key=lambda record: (record.sequence, record.id)):
            values[line.key_name] = self._resolve_source_value(
                line.source_kind,
                line.source_expression,
                line.literal_value,
                context_values=values,
            )
        return values

    def _resolve_source_value(self, source_kind, source_expression=False, literal_value=False, *, context_values=None, request_data=None):
        self.ensure_one()
        if source_kind == 'literal':
            return self._decode_literal_value(literal_value)

        source_map = {
            'delivery_field': self,
            'endpoint_field': self.endpoint_id,
            'company_field': self.company_id,
            'partner_field': self.partner_id,
            'context_key': context_values or {},
            'request_field': request_data or {},
        }
        source = source_map.get(source_kind)
        if source is None:
            return False
        if not source_expression:
            return False
        try:
            return self._resolve_expression_value(source, source_expression)
        except AttributeError as err:
            raise WebhookProcessingConfigurationError(_('Could not resolve source expression %s.') % source_expression) from err

    def _set_payload_path(self, payload, target_path, value):
        if not target_path:
            return value
        if payload in (False, None):
            payload = {}
        if not isinstance(payload, dict):
            raise WebhookProcessingConfigurationError(_('Payload assignment requires a JSON object payload when using a nested target path.'))
        current = payload
        path_parts = [part for part in target_path.split('.') if part]
        for part in path_parts[:-1]:
            current = current.setdefault(part, {})
            if not isinstance(current, dict):
                raise WebhookProcessingConfigurationError(_('Payload assignment path %s collides with a non-object value.') % target_path)
        current[path_parts[-1]] = value
        return payload

    def _build_request_data(self):
        self.ensure_one()
        context_values = self._get_context_values()
        headers = {}
        payload = {}
        for rule in self.endpoint_id.header_rule_ids.filtered('active').sorted(key=lambda record: (record.sequence, record.id)):
            value = self._resolve_source_value(
                rule.source_kind,
                rule.source_expression,
                rule.literal_value,
                context_values=context_values,
            )
            headers[rule.header_name] = '' if value is False or value is None else str(value)
        for rule in self.endpoint_id.payload_rule_ids.filtered('active').sorted(key=lambda record: (record.sequence, record.id)):
            value = self._resolve_source_value(
                rule.source_kind,
                rule.source_expression,
                rule.literal_value,
                context_values=context_values,
            )
            payload = self._set_payload_path(payload, rule.target_path, value)
        return {
            'target_url': self.target_url,
            'http_method': self.http_method,
            'headers': headers,
            'payload': payload,
        }

    def _serialize_headers(self, headers):
        return json.dumps({str(key): str(value) for key, value in headers.items()}, indent=2, sort_keys=True)

    def _serialize_payload(self, payload):
        return json.dumps(payload, indent=2, sort_keys=True)

    def _get_next_attempt_number(self):
        self.ensure_one()
        return self.env['webhook.outbound.delivery.attempt'].search_count([
            ('delivery_id', '=', self.id),
        ]) + 1

    def _create_attempt(self, request_data, *, state='processing', note=False, error=False, response_status_code=False, response_headers=None, response_body=False):
        self.ensure_one()
        values = {
            'name': '%s / Attempt %s' % (self.display_name, self._get_next_attempt_number()),
            'delivery_id': self.id,
            'attempt_number': self._get_next_attempt_number(),
            'state': state,
            'http_method': request_data['http_method'],
            'target_url': request_data['target_url'],
            'request_headers_json': self._serialize_headers(request_data['headers']),
            'payload_json': self._serialize_payload(request_data['payload']),
            'processing_note': note or False,
            'processing_error': error or False,
            'response_status_code': response_status_code or False,
            'response_headers_json': self._serialize_headers(response_headers or {}) if response_headers else False,
            'response_body': response_body or False,
        }
        if state != 'processing':
            values['finished_at'] = fields.Datetime.now()
        return self.env['webhook.outbound.delivery.attempt'].create(values)

    @api.constrains('target_url', 'timeout_seconds', 'request_headers_json', 'payload_json')
    def _check_delivery_configuration(self):
        for delivery in self:
            if not delivery.target_url or not str(delivery.target_url).strip():
                raise ValidationError(_('Outbound deliveries require a target URL.'))
            if delivery.timeout_seconds <= 0:
                raise ValidationError(_('Outbound delivery timeout must be greater than zero seconds.'))
            delivery._get_request_headers()
            delivery._get_payload()

    def _queue_processing(self):
        for delivery in self:
            if delivery.endpoint_id.is_paused:
                raise ValidationError(_('Outbound endpoint %s is paused and cannot queue new deliveries.') % delivery.endpoint_id.display_name)
            if not delivery.endpoint_id.active:
                raise ValidationError(_('Archived outbound endpoint %s cannot queue new deliveries.') % delivery.endpoint_id.display_name)
            if delivery.state not in ('draft', 'error'):
                continue
            delivery.write({
                'state': 'queued',
                'queued_at': fields.Datetime.now(),
                'processing_error': False,
            })
            delivery.with_user(delivery.execution_user_id).with_delay(identity_key=delivery._get_queue_job_identity_key()).process_delivery()

    def action_queue_delivery(self):
        self._queue_processing()
        return True

    def action_reset_to_draft(self):
        for delivery in self:
            if delivery.state == 'processing':
                raise ValidationError(_('Processing deliveries cannot be reset to draft.'))
            delivery.write({
                'state': 'draft',
                'queued_at': False,
                'processed_at': False,
                'processing_note': False,
                'processing_error': False,
                'response_status_code': False,
                'response_headers_json': False,
                'response_body': False,
            })
        return True

    def action_create_replay_delivery(self):
        self.ensure_one()
        if self.state in ('queued', 'processing'):
            raise ValidationError(_('Queued or processing deliveries cannot be replayed.'))
        replay_delivery = self.copy({
            'name': '%s / Replay %s' % (self.display_name, self._get_next_replay_number()),
            'state': 'draft',
            'queued_at': False,
            'processed_at': False,
            'processing_note': False,
            'processing_error': False,
            'response_status_code': False,
            'response_headers_json': False,
            'response_body': False,
            'replayed_from_delivery_id': self.id,
        })
        action = self.env.ref('webhooks.action_webhook_outbound_delivery').read()[0]
        action['res_id'] = replay_delivery.id
        action['view_mode'] = 'form'
        action['views'] = [(self.env.ref('webhooks.view_webhook_outbound_delivery_form').id, 'form')]
        return action

    def action_cancel_delivery(self):
        for delivery in self:
            if delivery.state in ('done', 'processing'):
                raise ValidationError(_('Completed or processing deliveries cannot be canceled.'))
            delivery.write({'state': 'canceled'})
        return True

    def _execute_low_code_handler(self, handler, request_data=None):
        self.ensure_one()
        request_data = dict(request_data or self._build_request_data())
        context_values = self._get_context_values()
        rules = handler.outbound_rule_ids.filtered('active').sorted(key=lambda record: (record.sequence, record.id))
        matched_rule = False
        for rule in rules:
            if all(self._outbound_condition_matches(condition, context_values, request_data) for condition in rule.condition_ids.sorted(key=lambda record: (record.sequence, record.id))):
                matched_rule = rule
                break

        if not matched_rule:
            return {'status': 'send'}

        updated_request_data = dict(request_data)
        updated_request_data['headers'] = dict(request_data['headers'])
        updated_request_data['payload'] = json.loads(json.dumps(request_data['payload']))
        for assignment in matched_rule.assignment_ids.sorted(key=lambda record: (record.sequence, record.id)):
            value = self._resolve_source_value(
                assignment.source_kind,
                assignment.source_expression,
                assignment.literal_value,
                context_values=context_values,
                request_data=updated_request_data,
            )
            if assignment.target_scope == 'request':
                updated_request_data[assignment.target_expression] = value
            elif assignment.target_scope == 'header':
                updated_request_data['headers'][assignment.target_expression] = '' if value is False or value is None else str(value)
            else:
                updated_request_data['payload'] = self._set_payload_path(updated_request_data['payload'], assignment.target_expression, value)

        result = {
            'status': matched_rule.result_status,
            'note': matched_rule.note or False,
            'matched_rule_id': matched_rule.id,
        }
        if updated_request_data.get('target_url') != request_data['target_url']:
            result['target_url'] = updated_request_data['target_url']
        if updated_request_data.get('http_method') != request_data['http_method']:
            result['http_method'] = updated_request_data['http_method']
        if updated_request_data['headers'] != request_data['headers']:
            result['headers'] = updated_request_data['headers']
        if updated_request_data['payload'] != request_data['payload']:
            result['payload'] = updated_request_data['payload']
        if matched_rule.result_status == 'retry' and matched_rule.retry_seconds:
            result['seconds'] = matched_rule.retry_seconds
        return result

    def _outbound_condition_matches(self, condition, context_values, request_data):
        actual_value = self._resolve_source_value(
            condition.source_kind,
            condition.source_expression,
            context_values=context_values,
            request_data=request_data,
        )
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
        raise WebhookProcessingConfigurationError(_('Unsupported outbound condition operator %s.') % condition.operator)

    def _apply_handler_result(self, result, request_data):
        if not isinstance(result, dict):
            return result, request_data
        updated_request_data = dict(request_data)
        if 'target_url' in result and result.get('target_url'):
            updated_request_data['target_url'] = result['target_url']
        if 'http_method' in result and result.get('http_method'):
            updated_request_data['http_method'] = str(result['http_method']).lower()
        if 'headers' in result and result.get('headers') is not None:
            updated_request_data['headers'] = {str(key): str(value) for key, value in result['headers'].items()}
        if 'payload' in result:
            updated_request_data['payload'] = result['payload']
        return result, updated_request_data

    def process_delivery(self):
        for delivery in self:
            if delivery.state in ('done', 'dead_letter', 'canceled'):
                continue

            request_data = False
            handler_note = False
            matched_rule_id = False
            try:
                request_data = delivery._build_request_data()
                if delivery.handler_id:
                    result = delivery.handler_id.execute_outbound(delivery, request_data=request_data)
                    if isinstance(result, dict):
                        matched_rule_id = result.get('matched_rule_id') or False
                    result, request_data = delivery._apply_handler_result(result, request_data)
                    if isinstance(result, dict):
                        status = result.get('status', 'send')
                        handler_note = result.get('note') or result.get('message')
                        if status == 'cancel':
                            delivery._create_attempt(request_data, state='canceled', note=handler_note)
                            delivery.write({
                                'state': 'canceled',
                                'processed_at': fields.Datetime.now(),
                                'processing_note': handler_note or False,
                                'processing_error': False,
                            })
                            continue
                        if status == 'dead_letter':
                            delivery._create_attempt(request_data, state='dead_letter', note=handler_note)
                            delivery.write({
                                'state': 'dead_letter',
                                'processed_at': fields.Datetime.now(),
                                'processing_note': handler_note or False,
                                'processing_error': False,
                            })
                            continue
                        if status == 'retry':
                            delivery._create_attempt(
                                request_data,
                                state='error',
                                note=handler_note,
                                error=handler_note or _('Retry requested by outbound handler.'),
                            )
                            delivery.write({
                                'state': 'error',
                                'processing_note': handler_note or False,
                                'processing_error': handler_note or _('Retry requested by outbound handler.'),
                            })
                            raise RetryableJobError(handler_note or _('Retry requested by outbound handler.'), seconds=result.get('seconds'))
                    elif result is False:
                        delivery._create_attempt(request_data, state='canceled')
                        delivery.write({
                            'state': 'canceled',
                            'processed_at': fields.Datetime.now(),
                            'processing_note': False,
                            'processing_error': False,
                        })
                        continue
            except RetryableJobError:
                raise
            except Exception:
                processing_error = traceback.format_exc()
                if request_data:
                    delivery._create_attempt(
                        request_data,
                        state='error',
                        note=handler_note or False,
                        error=processing_error,
                    )
                delivery.write({
                    'state': 'error',
                    'processing_note': handler_note or False,
                    'processing_error': processing_error,
                })
                raise

            delivery.write({
                'request_headers_json': delivery._serialize_headers(request_data['headers']),
                'payload_json': delivery._serialize_payload(request_data['payload']),
                'matched_outbound_rule_id': matched_rule_id or False,
            })

            attempt = delivery._create_attempt(request_data)
            try:
                delivery.write({'state': 'processing', 'processing_error': False})
                response = requests.request(
                    request_data['http_method'].upper(),
                    request_data['target_url'],
                    json=request_data['payload'],
                    headers=request_data['headers'],
                    timeout=delivery.timeout_seconds,
                )
            except requests.RequestException as err:
                attempt.write({
                    'state': 'error',
                    'finished_at': fields.Datetime.now(),
                    'processing_note': handler_note or False,
                    'processing_error': str(err),
                })
                delivery.write({
                    'state': 'error',
                    'processing_note': handler_note or False,
                    'processing_error': str(err),
                })
                raise RetryableJobError(str(err)) from err

            common_values = {
                'response_status_code': response.status_code,
                'response_headers_json': json.dumps(dict(response.headers.items()), indent=2, sort_keys=True),
                'response_body': response.text,
                'processed_at': fields.Datetime.now(),
                'processing_note': handler_note or False,
                'matched_outbound_rule_id': matched_rule_id or False,
            }
            if 200 <= response.status_code < 400:
                attempt.write({
                    'state': 'done',
                    'finished_at': fields.Datetime.now(),
                    'processing_note': handler_note or False,
                    'processing_error': False,
                    'response_status_code': response.status_code,
                    'response_headers_json': delivery._serialize_headers(dict(response.headers.items())),
                    'response_body': response.text,
                })
                delivery.write({
                    **common_values,
                    'state': 'done',
                    'processing_error': False,
                })
                continue

            error_message = _('Remote endpoint returned HTTP %s.') % response.status_code
            if 400 <= response.status_code < 500:
                attempt.write({
                    'state': 'dead_letter',
                    'finished_at': fields.Datetime.now(),
                    'processing_note': handler_note or False,
                    'processing_error': error_message,
                    'response_status_code': response.status_code,
                    'response_headers_json': delivery._serialize_headers(dict(response.headers.items())),
                    'response_body': response.text,
                })
                delivery.write({
                    **common_values,
                    'state': 'dead_letter',
                    'processing_error': error_message,
                })
                continue

            attempt.write({
                'state': 'error',
                'finished_at': fields.Datetime.now(),
                'processing_note': handler_note or False,
                'processing_error': error_message,
                'response_status_code': response.status_code,
                'response_headers_json': delivery._serialize_headers(dict(response.headers.items())),
                'response_body': response.text,
            })
            delivery.write({
                **common_values,
                'state': 'error',
                'processing_error': error_message,
            })
            raise RetryableJobError(error_message)