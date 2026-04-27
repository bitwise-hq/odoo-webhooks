import json

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
    operator_action_hint = fields.Text(compute='_compute_operator_action_hint', string='Operator Guidance')
    queue_job_identity_key = fields.Char(
        compute='_compute_queue_job_identity_key',
        string='Queue Job Identity Key',
        help='Identity key used when enqueuing background delivery processing for this outbound delivery.',
    )

    @api.depends('state', 'handler_id', 'processing_note', 'processing_error', 'response_status_code')
    def _compute_operator_action_hint(self):
        for delivery in self:
            if delivery.state == 'draft':
                delivery.operator_action_hint = _('Queue this delivery to send the stored payload to the configured outbound endpoint.')
            elif delivery.state == 'queued':
                delivery.operator_action_hint = _('This delivery is queued and waiting for the background worker.')
            elif delivery.state == 'processing':
                delivery.operator_action_hint = _('This delivery is currently being processed by the queue worker.')
            elif delivery.state == 'error':
                delivery.operator_action_hint = _('Review the delivery error, adjust the endpoint or payload if needed, then requeue the delivery.')
            elif delivery.state == 'dead_letter':
                delivery.operator_action_hint = _('The remote endpoint returned a non-retryable failure. Confirm replay is safe before resetting this delivery.')
            elif delivery.state == 'canceled':
                delivery.operator_action_hint = _('This delivery was canceled before sending. Reset it to draft if you need to send it again.')
            else:
                delivery.operator_action_hint = False

    @api.depends('id')
    def _compute_queue_job_identity_key(self):
        for delivery in self:
            delivery.queue_job_identity_key = delivery._get_queue_job_identity_key() if delivery.id else False

    def _get_queue_job_identity_key(self):
        self.ensure_one()
        return f'webhook_outbound_delivery_process:{self.id}' if self.id else False

    @api.model
    def _normalize_headers_json(self, value):
        try:
            headers = json.loads(value or '{}')
        except json.JSONDecodeError as err:
            raise ValidationError(_('Request Headers must be valid JSON.')) from err
        if not isinstance(headers, dict):
            raise ValidationError(_('Request Headers must be a JSON object.'))
        return json.dumps({str(key): str(header_value) for key, header_value in headers.items()}, indent=2, sort_keys=True)

    @api.model
    def _normalize_payload_json(self, value):
        try:
            payload = json.loads(value or '{}')
        except json.JSONDecodeError as err:
            raise ValidationError(_('Payload JSON must be valid JSON.')) from err
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
        prepared_vals.setdefault('request_headers_json', endpoint.static_headers_json or '{}')
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

    def action_cancel_delivery(self):
        for delivery in self:
            if delivery.state in ('done', 'processing'):
                raise ValidationError(_('Completed or processing deliveries cannot be canceled.'))
            delivery.write({'state': 'canceled'})
        return True

    def _execute_low_code_handler(self, handler):
        self.ensure_one()
        return {
            'status': 'send',
            'note': _('Model-driven outbound handler %s is configured but request customization is not implemented yet. Sending the stored request unchanged.') % handler.display_name,
        }

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

            request_data = {
                'target_url': delivery.target_url,
                'http_method': delivery.http_method,
                'headers': delivery._get_request_headers(),
                'payload': delivery._get_payload(),
            }
            handler_note = False
            if delivery.handler_id:
                result = delivery.handler_id.execute_outbound(delivery)
                result, request_data = delivery._apply_handler_result(result, request_data)
                if isinstance(result, dict):
                    status = result.get('status', 'send')
                    handler_note = result.get('note') or result.get('message')
                    if status == 'cancel':
                        delivery.write({
                            'state': 'canceled',
                            'processed_at': fields.Datetime.now(),
                            'processing_note': handler_note or False,
                            'processing_error': False,
                        })
                        continue
                    if status == 'dead_letter':
                        delivery.write({
                            'state': 'dead_letter',
                            'processed_at': fields.Datetime.now(),
                            'processing_note': handler_note or False,
                            'processing_error': False,
                        })
                        continue
                    if status == 'retry':
                        delivery.write({
                            'state': 'error',
                            'processing_note': handler_note or False,
                            'processing_error': handler_note or _('Retry requested by outbound handler.'),
                        })
                        raise RetryableJobError(handler_note or _('Retry requested by outbound handler.'), seconds=result.get('seconds'))
                elif result is False:
                    delivery.write({
                        'state': 'canceled',
                        'processed_at': fields.Datetime.now(),
                        'processing_note': False,
                        'processing_error': False,
                    })
                    continue

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
                delivery.write({
                    **common_values,
                    'state': 'done',
                    'processing_error': False,
                })
                continue

            error_message = _('Remote endpoint returned HTTP %s.') % response.status_code
            if 400 <= response.status_code < 500:
                delivery.write({
                    **common_values,
                    'state': 'dead_letter',
                    'processing_error': error_message,
                })
                continue

            delivery.write({
                **common_values,
                'state': 'error',
                'processing_error': error_message,
            })
            raise RetryableJobError(error_message)