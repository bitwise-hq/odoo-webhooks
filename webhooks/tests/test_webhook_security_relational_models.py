from odoo.exceptions import AccessError

from .common import WebhookEndpointTestCase


class TestWebhookSecurityRelationalModels(WebhookEndpointTestCase):
    def setUp(self):
        super().setUp()
        self.webhook_operator_group = self.env.ref("webhooks.group_webhooks_operator")

    def _create_outbound_rule(self, handler, **values):
        create_vals = {
            "handler_id": handler.id,
            "name": values.pop("name", self._next_token("outbound_rule")),
            "result_status": values.pop("result_status", "send"),
        }
        create_vals.update(values)
        return self.env["webhook.handler.outbound.rule"].create(create_vals)

    def _create_scoped_records(self, scope_name, partner=False):
        partner_id = partner.id if partner else False
        inbound_handler = self._create_handler(
            name=f"{scope_name} inbound handler",
            code=f"{scope_name}_inbound_handler",
            direction="inbound",
            partner_id=partner_id,
        )
        inbound_rule = self.env["webhook.handler.inbound.rule"].create(
            {
                "handler_id": inbound_handler.id,
                "name": f"{scope_name} inbound rule",
                "action_type": "done",
            }
        )
        inbound_condition = self.env["webhook.handler.inbound.rule.condition"].create(
            {
                "rule_id": inbound_rule.id,
                "source_kind": "semantic_field",
                "source_expression": "topic",
                "operator": "equals",
                "expected_value": f"{scope_name}.topic",
            }
        )
        inbound_lookup = self.env["webhook.handler.inbound.rule.lookup"].create(
            {
                "rule_id": inbound_rule.id,
                "target_field_name": "ref",
                "source_kind": "literal",
                "literal_value": f"{scope_name}-lookup",
            }
        )
        inbound_assignment = self.env["webhook.handler.inbound.rule.assignment"].create(
            {
                "rule_id": inbound_rule.id,
                "target_kind": "field",
                "target_expression": "name",
                "source_kind": "literal",
                "literal_value": f"{scope_name} assignment",
            }
        )
        inbound_endpoint = self._create_inbound_endpoint(
            handler=inbound_handler,
            name=f"{scope_name} inbound endpoint",
            path=f"{scope_name}-endpoint",
            partner_id=partner_id,
        )
        source = self._create_source(
            inbound_endpoint,
            field_name="topic",
            source_kind="literal",
            literal_value=f"{scope_name}.topic",
        )
        binding = self._create_binding(
            inbound_endpoint,
            semantic_name="topic",
            value_key="topic",
        )
        signature_part = self._create_signature_part(
            inbound_endpoint,
            source_kind="literal",
            literal_value=f"{scope_name}-signature-part",
        )
        inbound_event = self._create_inbound_event(
            inbound_endpoint,
            handler=inbound_handler,
            state="done",
            topic=f"{scope_name}.topic",
        )
        rule_execution = self.env["webhook.inbound.rule.execution"].create(
            {
                "event_id": inbound_event.id,
                "rule_id": inbound_rule.id,
                "state": "done",
            }
        )

        outbound_handler = self._create_handler(
            name=f"{scope_name} outbound handler",
            code=f"{scope_name}_outbound_handler",
            direction="outbound",
            partner_id=partner_id,
        )
        outbound_rule = self._create_outbound_rule(
            outbound_handler,
            name=f"{scope_name} outbound rule",
        )
        outbound_condition = self.env["webhook.handler.outbound.rule.condition"].create(
            {
                "rule_id": outbound_rule.id,
                "source_kind": "context_key",
                "source_expression": "topic",
                "operator": "equals",
                "expected_value": f"{scope_name}.topic",
            }
        )
        outbound_assignment = self.env["webhook.handler.outbound.assignment"].create(
            {
                "rule_id": outbound_rule.id,
                "target_scope": "header",
                "target_expression": "X-Scope",
                "source_kind": "literal",
                "literal_value": scope_name,
            }
        )
        outbound_endpoint = self._create_outbound_endpoint(
            handler=outbound_handler,
            name=f"{scope_name} outbound endpoint",
            code=f"{scope_name}_outbound_endpoint",
            partner_id=partner_id,
            target_path=f"/{scope_name}",
        )
        header_rule = self.env["webhook.outbound.endpoint.header.rule"].create(
            {
                "endpoint_id": outbound_endpoint.id,
                "header_name": "X-Scope",
                "source_kind": "literal",
                "literal_value": scope_name,
            }
        )
        payload_rule = self.env["webhook.outbound.endpoint.payload.rule"].create(
            {
                "endpoint_id": outbound_endpoint.id,
                "target_path": "meta.scope",
                "source_kind": "literal",
                "literal_value": scope_name,
            }
        )
        delivery = self._create_outbound_delivery(outbound_endpoint)
        context_line = self._create_outbound_context_line(
            delivery,
            key_name="topic",
            literal_value=f"{scope_name}.topic",
        )
        attempt = delivery._create_attempt(
            delivery._build_request_data(),
            state="done",
            response_status_code=200,
            response_headers={"X-Test": "ok"},
            response_body="{}",
        )

        return {
            "webhook.handler": inbound_handler,
            "webhook.handler.inbound.rule": inbound_rule,
            "webhook.handler.inbound.rule.condition": inbound_condition,
            "webhook.handler.inbound.rule.lookup": inbound_lookup,
            "webhook.handler.inbound.rule.assignment": inbound_assignment,
            "webhook.inbound.endpoint": inbound_endpoint,
            "webhook.endpoint.source": source,
            "webhook.endpoint.semantic.binding": binding,
            "webhook.endpoint.signature.part": signature_part,
            "webhook.inbound.rule.execution": rule_execution,
            "webhook.handler.outbound.rule": outbound_rule,
            "webhook.handler.outbound.rule.condition": outbound_condition,
            "webhook.handler.outbound.assignment": outbound_assignment,
            "webhook.outbound.endpoint": outbound_endpoint,
            "webhook.outbound.endpoint.header.rule": header_rule,
            "webhook.outbound.endpoint.payload.rule": payload_rule,
            "webhook.outbound.delivery": delivery,
            "webhook.outbound.delivery.context.line": context_line,
            "webhook.outbound.delivery.attempt": attempt,
        }

    def _visible_ids(self, user, model_name, record_ids):
        return set(
            self.env[model_name]
            .with_user(user)
            .search([("id", "in", list(record_ids))])
            .ids
        )

    def test_partner_rules_scope_relational_models(self):
        partner_allowed = self.env["res.partner"].create(
            {"name": "Allowed Partner", "is_company": True}
        )
        partner_blocked = self.env["res.partner"].create(
            {"name": "Blocked Partner", "is_company": True}
        )
        operator_user = self._create_user(
            group_ids=[
                (6, 0, [self.internal_user_group.id, self.webhook_operator_group.id])
            ],
            webhook_allowed_partner_ids=[(6, 0, [partner_allowed.id])],
        )
        admin_user = self._create_user(
            group_ids=[
                (6, 0, [self.internal_user_group.id, self.webhook_admin_group.id])
            ],
        )

        records_by_model = {}
        for scope_name, partner in (
            ("global", False),
            ("allowed", partner_allowed),
            ("blocked", partner_blocked),
        ):
            scoped_records = self._create_scoped_records(scope_name, partner)
            for model_name, record in scoped_records.items():
                records_by_model.setdefault(model_name, {})[scope_name] = record.id

        for model_name, scoped_ids in records_by_model.items():
            operator_visible = self._visible_ids(
                operator_user, model_name, scoped_ids.values()
            )
            self.assertEqual(
                operator_visible,
                {scoped_ids["global"], scoped_ids["allowed"]},
                model_name,
            )
            admin_visible = self._visible_ids(
                admin_user, model_name, scoped_ids.values()
            )
            self.assertEqual(admin_visible, set(scoped_ids.values()), model_name)

    def test_operator_acl_blocks_relational_model_changes(self):
        partner_allowed = self.env["res.partner"].create(
            {"name": "Allowed Operator Partner", "is_company": True}
        )
        operator_user = self._create_user(
            group_ids=[
                (6, 0, [self.internal_user_group.id, self.webhook_operator_group.id])
            ],
            webhook_allowed_partner_ids=[(6, 0, [partner_allowed.id])],
        )
        handler = self._create_handler(
            direction="outbound",
            partner_id=partner_allowed.id,
        )
        endpoint = self._create_outbound_endpoint(
            handler=handler,
            partner_id=partner_allowed.id,
        )
        header_rule = self.env["webhook.outbound.endpoint.header.rule"].create(
            {
                "endpoint_id": endpoint.id,
                "header_name": "X-Visible",
                "source_kind": "literal",
                "literal_value": "visible",
            }
        )

        with self.assertRaises(AccessError):
            self.env["webhook.handler.outbound.rule"].with_user(operator_user).create(
                {
                    "handler_id": handler.id,
                    "name": "Blocked Operator Rule",
                    "result_status": "send",
                }
            )

        with self.assertRaises(AccessError):
            header_rule.with_user(operator_user).write({"literal_value": "changed"})
