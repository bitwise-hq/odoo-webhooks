from odoo import fields

from .common import WebhookRuleTestCase


class TestOutboundModelDrivenRules(WebhookRuleTestCase):
    def test_build_request_data_uses_endpoint_rules_and_context_lines(self):
        endpoint = self._create_outbound_endpoint()
        self.env['webhook.outbound.endpoint.header.rule'].create({
            'endpoint_id': endpoint.id,
            'header_name': 'X-Static',
            'source_kind': 'literal',
            'literal_value': 'static-source',
        })
        self.env['webhook.outbound.endpoint.header.rule'].create({
            'endpoint_id': endpoint.id,
            'header_name': 'X-Trace',
            'source_kind': 'context_key',
            'source_expression': 'trace_id',
        })
        self.env['webhook.outbound.endpoint.payload.rule'].create({
            'endpoint_id': endpoint.id,
            'target_path': 'data.customer',
            'source_kind': 'context_key',
            'source_expression': 'customer_name',
        })
        self.env['webhook.outbound.endpoint.payload.rule'].create({
            'endpoint_id': endpoint.id,
            'target_path': 'data.amount',
            'source_kind': 'context_key',
            'source_expression': 'amount',
        })
        self.env['webhook.outbound.endpoint.payload.rule'].create({
            'endpoint_id': endpoint.id,
            'target_path': 'meta.company',
            'source_kind': 'company_field',
            'source_expression': 'name',
        })

        delivery = self._create_outbound_delivery(endpoint)
        self._create_outbound_context_line(delivery, key_name='trace_id', literal_value='trace-001')
        self._create_outbound_context_line(delivery, key_name='customer_name', literal_value='Alice Example')
        self._create_outbound_context_line(delivery, key_name='amount', literal_value='149.99')

        request_data = delivery._build_request_data()

        self.assertEqual(request_data['headers']['X-Static'], 'static-source')
        self.assertEqual(request_data['headers']['X-Trace'], 'trace-001')
        self.assertEqual(request_data['payload']['data']['customer'], 'Alice Example')
        self.assertEqual(request_data['payload']['data']['amount'], 149.99)
        self.assertEqual(request_data['payload']['meta']['company'], self.company.name)

    def test_handler_rule_mutates_request_and_requests_retry(self):
        handler = self._create_handler(inbound_enabled=False, outbound_enabled=True)
        endpoint = self._create_outbound_endpoint(handler=handler)
        self.env['webhook.outbound.endpoint.header.rule'].create({
            'endpoint_id': endpoint.id,
            'header_name': 'X-Origin',
            'source_kind': 'literal',
            'literal_value': 'webhooks',
        })

        rule = self.env['webhook.handler.outbound.rule'].create({
            'handler_id': handler.id,
            'name': 'Retry Draft Deliveries',
            'result_status': 'retry',
            'retry_seconds': 15,
            'note': 'Retry later',
        })
        self.env['webhook.handler.outbound.rule.condition'].create({
            'rule_id': rule.id,
            'source_kind': 'delivery_field',
            'source_expression': 'state',
            'operator': 'equals',
            'expected_value': 'draft',
        })
        self.env['webhook.handler.outbound.assignment'].create({
            'rule_id': rule.id,
            'target_scope': 'request',
            'target_expression': 'target_url',
            'source_kind': 'literal',
            'literal_value': 'https://override.example.com/hook',
        })
        self.env['webhook.handler.outbound.assignment'].create({
            'rule_id': rule.id,
            'target_scope': 'request',
            'target_expression': 'http_method',
            'source_kind': 'literal',
            'literal_value': 'patch',
        })
        self.env['webhook.handler.outbound.assignment'].create({
            'rule_id': rule.id,
            'target_scope': 'header',
            'target_expression': 'X-Mode',
            'source_kind': 'literal',
            'literal_value': 'retry',
        })
        self.env['webhook.handler.outbound.assignment'].create({
            'rule_id': rule.id,
            'target_scope': 'payload',
            'target_expression': 'meta.retry',
            'source_kind': 'literal',
            'literal_value': 'true',
        })

        delivery = self._create_outbound_delivery(endpoint)
        request_data = delivery._build_request_data()
        result = handler.execute_outbound(delivery, request_data=request_data)
        _, updated_request_data = delivery._apply_handler_result(result, request_data)

        self.assertEqual(result['status'], 'retry')
        self.assertEqual(result['matched_rule_id'], rule.id)
        self.assertEqual(result['seconds'], 15)
        self.assertEqual(updated_request_data['target_url'], 'https://override.example.com/hook')
        self.assertEqual(updated_request_data['http_method'], 'patch')
        self.assertEqual(updated_request_data['headers']['X-Origin'], 'webhooks')
        self.assertEqual(updated_request_data['headers']['X-Mode'], 'retry')
        self.assertTrue(updated_request_data['payload']['meta']['retry'])

    def test_build_request_data_normalizes_datetime_payload_values(self):
        endpoint = self._create_outbound_endpoint()
        self.env['webhook.outbound.endpoint.payload.rule'].create({
            'endpoint_id': endpoint.id,
            'target_path': 'meta.created_at',
            'source_kind': 'delivery_field',
            'source_expression': 'create_date',
        })

        delivery = self._create_outbound_delivery(endpoint)

        request_data = delivery._build_request_data()

        self.assertEqual(
            request_data['payload']['meta']['created_at'],
            fields.Datetime.to_string(delivery.create_date),
        )
        self.assertIn(fields.Datetime.to_string(delivery.create_date), delivery._serialize_payload(request_data['payload']))