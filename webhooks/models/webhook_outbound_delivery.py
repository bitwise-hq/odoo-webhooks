import json
import re
import traceback
from types import SimpleNamespace

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
    _PLACEHOLDER_ONLY_PATTERN = re.compile(r'^\{([A-Za-z_][A-Za-z0-9_]*(?:\.[A-Za-z_][A-Za-z0-9_]*|\[\d+\])*)\}$')

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
    request_headers_template_json = fields.Text(required=True, default='{}', string='Header Template')
    payload_json = fields.Text(required=True, default='{}', string='Payload JSON')
    payload_template_json = fields.Text(required=True, default='{}', string='Payload Template')
    template_context_json = fields.Text(required=True, default='{}', string='Template Context')
    response_status_code = fields.Integer(index=True, string='Response Status')
    response_headers_json = fields.Text(string='Response Headers')
    response_body = fields.Text(string='Response Body')
    processing_note = fields.Text()
    processing_error = fields.Text()
    replayed_from_delivery_id = fields.Many2one(
        'webhook.outbound.delivery',
        string='Replay Of',
        ondelete='set null',
        index=True,
        check_company=True,
    )
    replay_delivery_ids = fields.One2many('webhook.outbound.delivery', 'replayed_from_delivery_id', string='Replay Deliveries')
    replay_count = fields.Integer(compute='_compute_replay_count')
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

    @api.depends('handler_id', 'handler_id.execution_mode', 'replayed_from_delivery_id', 'request_headers_template_json', 'payload_template_json', 'template_context_json')
    def _compute_template_guidance(self):
        for delivery in self:
            messages = [
                _('Templates can reference {delivery.id}, {delivery.name}, {endpoint.code}, {company.name}, {partner.name}, {now}, and any top-level keys from Template Context.'),
                _('Low-code outbound handlers use the same template context and can additionally inspect {request.target_url}, {request.http_method}, {request.headers}, and {request.payload} after endpoint and delivery templates render.'),
            ]
            if delivery.replayed_from_delivery_id:
                messages.append(_('This delivery was created as a replay of %s. The request snapshot, templates, and template context were copied from that delivery.') % delivery.replayed_from_delivery_id.display_name)
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
    def _normalize_template_context_json(self, value):
        try:
            context = json.loads(value or '{}')
        except json.JSONDecodeError as err:
            raise ValidationError(_('Template Context must be valid JSON.')) from err
        if not isinstance(context, dict):
            raise ValidationError(_('Template Context must be a JSON object.'))
        return json.dumps(context, indent=2, sort_keys=True)

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
        prepared_vals.setdefault('request_headers_json', endpoint.static_headers_json or '{}')
        prepared_vals.setdefault('request_headers_template_json', endpoint.request_headers_template_json or '{}')
        prepared_vals.setdefault('payload_json', '{}')
        prepared_vals.setdefault('payload_template_json', endpoint.payload_template_json or '{}')
        prepared_vals.setdefault('template_context_json', '{}')
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
            prepared_vals['request_headers_template_json'] = self._normalize_headers_json(
                prepared_vals.get('request_headers_template_json'),
                label='Header Template',
            )
            prepared_vals['payload_json'] = self._normalize_payload_json(prepared_vals.get('payload_json'))
            prepared_vals['payload_template_json'] = self._normalize_payload_json(
                prepared_vals.get('payload_template_json'),
                label='Payload Template',
            )
            prepared_vals['template_context_json'] = self._normalize_template_context_json(prepared_vals.get('template_context_json'))
            prepared_vals_list.append(prepared_vals)
        return super().create(prepared_vals_list)

    def write(self, vals):
        prepared_vals = dict(vals)
        if 'request_headers_json' in prepared_vals:
            prepared_vals['request_headers_json'] = self._normalize_headers_json(prepared_vals.get('request_headers_json'))
        if 'request_headers_template_json' in prepared_vals:
            prepared_vals['request_headers_template_json'] = self._normalize_headers_json(
                prepared_vals.get('request_headers_template_json'),
                label='Header Template',
            )
        if 'payload_json' in prepared_vals:
            prepared_vals['payload_json'] = self._normalize_payload_json(prepared_vals.get('payload_json'))
        if 'payload_template_json' in prepared_vals:
            prepared_vals['payload_template_json'] = self._normalize_payload_json(
                prepared_vals.get('payload_template_json'),
                label='Payload Template',
            )
        if 'template_context_json' in prepared_vals:
            prepared_vals['template_context_json'] = self._normalize_template_context_json(prepared_vals.get('template_context_json'))
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

    def _get_request_headers_template(self):
        self.ensure_one()
        try:
            headers = json.loads(self.request_headers_template_json or '{}')
        except json.JSONDecodeError as err:
            raise WebhookProcessingConfigurationError(_('Header Template must be valid JSON.')) from err
        if not isinstance(headers, dict):
            raise WebhookProcessingConfigurationError(_('Header Template must be a JSON object.'))
        return headers

    def _get_payload_template(self):
        self.ensure_one()
        try:
            return json.loads(self.payload_template_json or '{}')
        except json.JSONDecodeError as err:
            raise WebhookProcessingConfigurationError(_('Payload Template must be valid JSON.')) from err

    def _get_template_context(self):
        self.ensure_one()
        try:
            custom_context = json.loads(self.template_context_json or '{}')
        except json.JSONDecodeError as err:
            raise WebhookProcessingConfigurationError(_('Template Context must be valid JSON.')) from err
        if not isinstance(custom_context, dict):
            raise WebhookProcessingConfigurationError(_('Template Context must be a JSON object.'))
        scoped_partner = self.partner_id
        return {
            'delivery': {
                'id': self.id,
                'name': self.name,
                'state': self.state,
                'http_method': self.http_method,
                'target_url': self.target_url,
            },
            'endpoint': {
                'id': self.endpoint_id.id,
                'name': self.endpoint_id.name,
                'code': self.endpoint_id.code,
                'target_url': self.endpoint_id.target_url,
            },
            'company': {
                'id': self.company_id.id,
                'name': self.company_id.display_name,
            },
            'partner': {
                'id': scoped_partner.id if scoped_partner else False,
                'name': scoped_partner.display_name if scoped_partner else False,
            },
            'now': fields.Datetime.to_string(fields.Datetime.now()),
            **custom_context,
        }

    def _wrap_template_context_value(self, value):
        if isinstance(value, dict):
            return SimpleNamespace(**{key: self._wrap_template_context_value(item) for key, item in value.items()})
        if isinstance(value, list):
            return [self._wrap_template_context_value(item) for item in value]
        return value

    def _resolve_template_expression(self, expression, context):
        current = context
        index = 0
        while index < len(expression):
            char = expression[index]
            if char == '.':
                index += 1
                continue
            if char == '[':
                end_index = expression.find(']', index)
                if end_index == -1:
                    raise WebhookProcessingConfigurationError(_('Invalid template expression %s.') % expression)
                current = current[int(expression[index + 1:end_index])]
                index = end_index + 1
                continue
            start_index = index
            while index < len(expression) and expression[index] not in '.[':
                index += 1
            token = expression[start_index:index]
            if isinstance(current, dict):
                current = current[token]
            else:
                current = getattr(current, token)
        return current

    def _render_template_string(self, value, context, wrapped_context):
        placeholder_match = self._PLACEHOLDER_ONLY_PATTERN.match(value)
        if placeholder_match:
            try:
                return self._resolve_template_expression(placeholder_match.group(1), context)
            except (AttributeError, IndexError, KeyError, TypeError, ValueError) as err:
                raise WebhookProcessingConfigurationError(_('Could not render template value %s.') % value) from err
        try:
            return value.format_map(wrapped_context)
        except (AttributeError, IndexError, KeyError, TypeError, ValueError) as err:
            raise WebhookProcessingConfigurationError(_('Could not render template value %s.') % value) from err

    def _render_template_value(self, value, context, wrapped_context):
        if isinstance(value, dict):
            return {
                str(key): self._render_template_value(item, context, wrapped_context)
                for key, item in value.items()
            }
        if isinstance(value, list):
            return [self._render_template_value(item, context, wrapped_context) for item in value]
        if isinstance(value, str):
            return self._render_template_string(value, context, wrapped_context)
        return value

    def _has_template_content(self, value):
        return (value or '').strip() not in ('', '{}')

    def _get_template_rendering_context(self, request_data=None):
        self.ensure_one()
        context = self._get_template_context()
        context['attempt_count'] = len(self.attempt_ids)
        context['replay_count'] = len(self.replay_delivery_ids)
        if request_data is not None:
            context['request'] = {
                'target_url': request_data['target_url'],
                'http_method': request_data['http_method'],
                'headers': request_data['headers'],
                'payload': request_data['payload'],
            }
        wrapped_context = {
            key: self._wrap_template_context_value(item)
            for key, item in context.items()
        }
        return context, wrapped_context

    def _merge_json_objects(self, base_value, updates, *, label):
        if not isinstance(base_value, dict) or not isinstance(updates, dict):
            raise WebhookProcessingConfigurationError(_('%s merge requires both values to be JSON objects.') % label)
        merged = dict(base_value)
        for key, value in updates.items():
            if isinstance(value, dict) and isinstance(merged.get(key), dict):
                merged[key] = self._merge_json_objects(merged[key], value, label=label)
            else:
                merged[key] = value
        return merged

    def _build_request_data(self):
        self.ensure_one()
        headers = dict(self._get_request_headers())
        payload = self._get_payload()
        context, wrapped_context = self._get_template_rendering_context()
        if self._has_template_content(self.request_headers_template_json):
            rendered_headers = self._render_template_value(self._get_request_headers_template(), context, wrapped_context)
            if not isinstance(rendered_headers, dict):
                raise WebhookProcessingConfigurationError(_('Header Template must render to a JSON object.'))
            headers.update({str(key): str(value) for key, value in rendered_headers.items()})
        if self._has_template_content(self.payload_template_json):
            payload = self._render_template_value(self._get_payload_template(), context, wrapped_context)
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

    @api.constrains('target_url', 'timeout_seconds', 'request_headers_json', 'request_headers_template_json', 'payload_json', 'payload_template_json', 'template_context_json')
    def _check_delivery_configuration(self):
        for delivery in self:
            if not delivery.target_url or not str(delivery.target_url).strip():
                raise ValidationError(_('Outbound deliveries require a target URL.'))
            if delivery.timeout_seconds <= 0:
                raise ValidationError(_('Outbound delivery timeout must be greater than zero seconds.'))
            delivery._get_request_headers()
            delivery._get_payload()
            delivery._get_request_headers_template()
            delivery._get_payload_template()
            delivery._get_template_context()

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
        outbound_config = handler._get_low_code_outbound_config()
        if not outbound_config:
            return {
                'status': 'send',
                'note': _('No outbound low-code instructions were configured on handler %s. Sending the rendered request unchanged.') % handler.display_name,
            }

        context, wrapped_context = self._get_template_rendering_context(request_data=request_data)
        result = {
            'status': outbound_config.get('status') or 'send',
        }
        if result['status'] not in ('send', 'cancel', 'dead_letter', 'retry'):
            raise WebhookProcessingConfigurationError(_('Outbound low-code handler status %s is not supported.') % result['status'])

        if outbound_config.get('note'):
            result['note'] = str(self._render_template_value(outbound_config['note'], context, wrapped_context))

        if outbound_config.get('target_url'):
            result['target_url'] = str(self._render_template_value(outbound_config['target_url'], context, wrapped_context))

        if outbound_config.get('http_method'):
            rendered_http_method = str(self._render_template_value(outbound_config['http_method'], context, wrapped_context)).lower()
            if rendered_http_method not in dict(self._HTTP_METHOD_SELECTION):
                raise WebhookProcessingConfigurationError(_('Outbound low-code handler HTTP method %s is not supported.') % rendered_http_method)
            result['http_method'] = rendered_http_method

        headers = dict(request_data['headers'])
        if 'headers' in outbound_config:
            rendered_headers = self._render_template_value(outbound_config['headers'], context, wrapped_context)
            if not isinstance(rendered_headers, dict):
                raise WebhookProcessingConfigurationError(_('Outbound low-code handler headers must render to a JSON object.'))
            headers = {str(key): str(value) for key, value in rendered_headers.items()}
        if outbound_config.get('headers_update') is not None:
            rendered_headers_update = self._render_template_value(outbound_config['headers_update'], context, wrapped_context)
            if not isinstance(rendered_headers_update, dict):
                raise WebhookProcessingConfigurationError(_('Outbound low-code handler headers_update must render to a JSON object.'))
            headers.update({str(key): str(value) for key, value in rendered_headers_update.items()})
        if headers != request_data['headers']:
            result['headers'] = headers

        payload = request_data['payload']
        if 'payload' in outbound_config:
            payload = self._render_template_value(outbound_config['payload'], context, wrapped_context)
        if outbound_config.get('payload_update') is not None:
            rendered_payload_update = self._render_template_value(outbound_config['payload_update'], context, wrapped_context)
            payload = self._merge_json_objects(payload, rendered_payload_update, label=_('Outbound handler payload update'))
        if payload != request_data['payload']:
            result['payload'] = payload

        if outbound_config.get('seconds') is not None:
            try:
                result['seconds'] = int(self._render_template_value(outbound_config['seconds'], context, wrapped_context))
            except (TypeError, ValueError) as err:
                raise WebhookProcessingConfigurationError(_('Outbound low-code handler seconds must render to an integer.')) from err

        return result

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
            try:
                request_data = delivery._build_request_data()
                if delivery.handler_id:
                    result = delivery.handler_id.execute_outbound(delivery, request_data=request_data)
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