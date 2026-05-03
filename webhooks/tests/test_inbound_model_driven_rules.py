from odoo.exceptions import ValidationError

from .common import WebhookRuleTestCase


class TestInboundModelDrivenRules(WebhookRuleTestCase):
    def test_create_record_rule_creates_target_record_and_execution_log(self):
        handler = self._create_handler(direction="inbound")
        endpoint = self._create_inbound_endpoint(handler=handler)

        rule = self.env["webhook.handler.inbound.rule"].create(
            {
                "handler_id": handler.id,
                "name": "Create Partner",
                "action_type": "create_record",
                "target_model_name": "res.partner",
            }
        )
        self.env["webhook.handler.inbound.rule.condition"].create(
            {
                "rule_id": rule.id,
                "source_kind": "semantic_field",
                "source_expression": "event_type",
                "operator": "equals",
                "expected_value": "customer.created",
            }
        )
        self.env["webhook.handler.inbound.rule.assignment"].create(
            {
                "rule_id": rule.id,
                "target_kind": "field",
                "target_expression": "name",
                "source_kind": "resolved_value",
                "source_expression": "customer_name",
            }
        )
        self.env["webhook.handler.inbound.rule.assignment"].create(
            {
                "rule_id": rule.id,
                "target_kind": "field",
                "target_expression": "ref",
                "source_kind": "resolved_value",
                "source_expression": "external_ref",
            }
        )

        event = self._create_inbound_event(
            endpoint,
            handler=handler,
            event_type="customer.created",
            resolved_values={
                "customer_name": "Alice Example",
                "external_ref": "EXT-CREATE-1",
            },
        )

        result = handler.execute_inbound(event)
        partner = self.env["res.partner"].search(
            [("ref", "=", "EXT-CREATE-1")], limit=1
        )

        self.assertEqual(result["status"], "done")
        self.assertEqual(result["matched_rule_id"], rule.id)
        self.assertEqual(partner.name, "Alice Example")
        self.assertEqual(len(event.rule_execution_ids), 1)
        self.assertEqual(event.rule_execution_ids.rule_id, rule)
        self.assertEqual(event.rule_execution_ids.state, "done")
        self.assertEqual(
            event.rule_execution_ids.record_reference, f"res.partner:{partner.id}"
        )

    def test_upsert_rule_uses_lookup_to_update_existing_record(self):
        existing_partner = self.env["res.partner"].create(
            {
                "name": "Old Name",
                "ref": "EXT-UPSERT-1",
            }
        )
        handler = self._create_handler(direction="inbound")
        endpoint = self._create_inbound_endpoint(handler=handler)

        rule = self.env["webhook.handler.inbound.rule"].create(
            {
                "handler_id": handler.id,
                "name": "Upsert Partner",
                "action_type": "upsert_record",
                "target_model_name": "res.partner",
            }
        )
        self.env["webhook.handler.inbound.rule.condition"].create(
            {
                "rule_id": rule.id,
                "source_kind": "semantic_field",
                "source_expression": "topic",
                "operator": "equals",
                "expected_value": "partner.sync",
            }
        )
        self.env["webhook.handler.inbound.rule.lookup"].create(
            {
                "rule_id": rule.id,
                "target_field_name": "ref",
                "source_kind": "resolved_value",
                "source_expression": "external_ref",
            }
        )
        self.env["webhook.handler.inbound.rule.assignment"].create(
            {
                "rule_id": rule.id,
                "target_kind": "field",
                "target_expression": "name",
                "source_kind": "resolved_value",
                "source_expression": "customer_name",
            }
        )

        event = self._create_inbound_event(
            endpoint,
            handler=handler,
            topic="partner.sync",
            resolved_values={
                "external_ref": "EXT-UPSERT-1",
                "customer_name": "New Name",
            },
        )

        result = handler.execute_inbound(event)
        updated_partner = self.env["res.partner"].browse(existing_partner.id)

        self.assertEqual(result["status"], "done")
        self.assertEqual(result["matched_rule_id"], rule.id)
        self.assertEqual(updated_partner.name, "New Name")
        self.assertEqual(
            self.env["res.partner"].search_count([("ref", "=", "EXT-UPSERT-1")]), 1
        )
        self.assertEqual(
            event.rule_execution_ids.record_reference,
            f"res.partner:{existing_partner.id}",
        )

    def test_inbound_endpoint_path_is_immutable(self):
        endpoint = self._create_inbound_endpoint(path="immutable-path")

        with self.assertRaisesRegex(ValidationError, "cannot be changed"):
            endpoint.write({"path": "changed-path"})

    def test_outbound_handler_cannot_execute_inbound_event(self):
        handler = self._create_handler(direction="outbound")
        endpoint = self._create_inbound_endpoint()
        event = self._create_inbound_event(endpoint)

        with self.assertRaisesRegex(ValidationError, "cannot process inbound"):
            handler.execute_inbound(event)

    def test_find_active_endpoint_by_path_ignores_draft_records(self):
        active_endpoint = self._create_inbound_endpoint(path="lookup-active")
        self._create_inbound_endpoint(path="lookup-draft", state="draft")

        found_endpoint = self.env[
            "webhook.inbound.endpoint"
        ]._find_active_endpoint_by_path(
            "lookup-active"
        )
        missing_endpoint = self.env[
            "webhook.inbound.endpoint"
        ]._find_active_endpoint_by_path(
            "lookup-draft"
        )

        self.assertEqual(found_endpoint, active_endpoint)
        self.assertFalse(missing_endpoint)

    def test_draft_inbound_endpoint_rejects_deliveries(self):
        endpoint = self._create_inbound_endpoint(state="draft")

        with self.assertRaisesRegex(ValidationError, "draft"):
            endpoint._validate_inbound_request(b"{}", {}, {}, {})

    def test_inbound_endpoint_state_actions(self):
        endpoint = self._create_inbound_endpoint(state="draft")

        endpoint.action_activate()
        self.assertEqual(endpoint.state, "active")

        endpoint.action_set_draft()
        self.assertEqual(endpoint.state, "draft")

        endpoint.action_archive()
        self.assertEqual(endpoint.state, "archived")

        endpoint.action_set_draft()
        self.assertEqual(endpoint.state, "draft")

    def test_inbound_endpoint_state_actions_reject_invalid_states(self):
        active_endpoint = self._create_inbound_endpoint(state="active")
        draft_endpoint = self._create_inbound_endpoint(state="draft")
        archived_endpoint = self._create_inbound_endpoint(state="archived")

        with self.assertRaisesRegex(ValidationError, "Only draft inbound endpoints"):
            active_endpoint.action_activate()
        with self.assertRaisesRegex(
            ValidationError, "Only active or archived inbound endpoints"
        ):
            draft_endpoint.action_set_draft()
        with self.assertRaisesRegex(
            ValidationError, "Only draft or active inbound endpoints"
        ):
            archived_endpoint.action_archive()

    def test_queue_processing_rejects_non_queueable_states(self):
        endpoint = self._create_inbound_endpoint()
        event = self._create_inbound_event(endpoint, state="done")

        with self.assertRaisesRegex(
            ValidationError, "Only received or failed webhook events"
        ):
            event.action_queue_processing()

    def test_reset_to_received_rejects_non_retriable_states(self):
        endpoint = self._create_inbound_endpoint()
        event = self._create_inbound_event(endpoint, state="done")

        with self.assertRaisesRegex(ValidationError, "Only failed or dead-letter"):
            event.action_reset_to_received()
