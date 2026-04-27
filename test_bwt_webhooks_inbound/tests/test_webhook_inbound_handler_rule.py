"""Behavioral tests for :class:`webhook.inbound.handler.rule` and adjacent endpoint behavior.

These tests exercise the model-driven inbound rule engine end-to-end
(create / upsert with conditions, lookups and assignments) and the
small endpoint-level guards that surround it (state transitions,
direction enforcement and path immutability).

Test suites in this module:

* :class:`TestInboundCreateRecordRule`
* :class:`TestInboundUpsertRecordRule`
* :class:`TestInboundEndpointPathImmutability`
* :class:`TestInboundHandlerDirectionEnforcement`
* :class:`TestInboundEndpointActiveLookup`
* :class:`TestInboundEndpointDeliveryGate`
* :class:`TestInboundEndpointStateTransitions`
* :class:`TestInboundEndpointStateTransitionGuards`
* :class:`TestInboundRuleConfigurationConstraints`
* :class:`TestInboundRuleLookupConfigurationConstraint`
* :class:`TestInboundRuleAssignmentConfigurationConstraint`
* :class:`TestHandlerPythonCallbackConfiguration`
* :class:`TestHandlerExecuteInboundPythonCallback`
"""

from odoo.exceptions import ValidationError

from odoo.addons.test_bwt_webhooks_core.tests.base import WebhookTestCase


class TestInboundCreateRecordRule(WebhookTestCase):
    """A matching ``create_record`` rule creates a record and logs a done execution."""

    def test_create_record_rule_creates_target_record_and_done_execution(self):
        handler = self.factory.handler(direction="inbound")
        endpoint = self.factory.inbound_endpoint(handler=handler)
        rule = self.env["bwt.webhook.inbound.handler.rule"].create(
            {
                "handler_id": handler.id,
                "name": "Create Partner",
                "action_type": "create_record",
                "target_model_name": "res.partner",
            }
        )
        self.env["bwt.webhook.inbound.handler.rule.condition"].create(
            {
                "rule_id": rule.id,
                "source_kind": "semantic_field",
                "source_expression": "event_type",
                "operator": "equals",
                "expected_value": "customer.created",
            }
        )
        self.env["bwt.webhook.inbound.handler.rule.assignment"].create(
            {
                "rule_id": rule.id,
                "target_kind": "field",
                "target_expression": "name",
                "source_kind": "resolved_value",
                "source_expression": "customer_name",
            }
        )
        self.env["bwt.webhook.inbound.handler.rule.assignment"].create(
            {
                "rule_id": rule.id,
                "target_kind": "field",
                "target_expression": "ref",
                "source_kind": "resolved_value",
                "source_expression": "external_ref",
            }
        )
        event = self.factory.inbound_event(
            endpoint,
            handler=handler,
            event_type="customer.created",
            resolved_values={
                "customer_name": "Alice Example",
                "external_ref": "EXT-CREATE-1",
            },
        )

        result = handler.execute_inbound(event)

        partner = self.env["res.partner"].search([("ref", "=", "EXT-CREATE-1")], limit=1)
        self.assertEqual(result["status"], "done")
        self.assertEqual(result["matched_rule_id"], rule.id)
        self.assertEqual(partner.name, "Alice Example")
        self.assertEqual(len(event.rule_execution_ids), 1)
        self.assertEqual(event.rule_execution_ids.rule_id, rule)
        self.assertEqual(event.rule_execution_ids.state, "done")
        self.assertEqual(event.rule_execution_ids.record_reference, f"res.partner:{partner.id}")


class TestInboundUpsertRecordRule(WebhookTestCase):
    """A matching ``upsert_record`` rule updates the existing record via lookup."""

    def test_upsert_rule_updates_existing_record_located_by_lookup(self):
        existing_partner = self.env["res.partner"].create({"name": "Old Name", "ref": "EXT-UPSERT-1"})
        handler = self.factory.handler(direction="inbound")
        endpoint = self.factory.inbound_endpoint(handler=handler)
        rule = self.env["bwt.webhook.inbound.handler.rule"].create(
            {
                "handler_id": handler.id,
                "name": "Upsert Partner",
                "action_type": "upsert_record",
                "target_model_name": "res.partner",
            }
        )
        self.env["bwt.webhook.inbound.handler.rule.condition"].create(
            {
                "rule_id": rule.id,
                "source_kind": "semantic_field",
                "source_expression": "topic",
                "operator": "equals",
                "expected_value": "partner.sync",
            }
        )
        self.env["bwt.webhook.inbound.handler.rule.lookup"].create(
            {
                "rule_id": rule.id,
                "target_field_name": "ref",
                "source_kind": "resolved_value",
                "source_expression": "external_ref",
            }
        )
        self.env["bwt.webhook.inbound.handler.rule.assignment"].create(
            {
                "rule_id": rule.id,
                "target_kind": "field",
                "target_expression": "name",
                "source_kind": "resolved_value",
                "source_expression": "customer_name",
            }
        )
        event = self.factory.inbound_event(
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
        self.assertEqual(self.env["res.partner"].search_count([("ref", "=", "EXT-UPSERT-1")]), 1)
        self.assertEqual(
            event.rule_execution_ids.record_reference,
            f"res.partner:{existing_partner.id}",
        )


class TestInboundEndpointPathImmutability(WebhookTestCase):
    """``path`` cannot be changed after the endpoint is created."""

    def test_path_write_after_create_is_rejected(self):
        endpoint = self.factory.inbound_endpoint(path="immutable-path")

        with self.assertRaisesRegex(ValidationError, "cannot be changed"):
            endpoint.write({"path": "changed-path"})

    def test_path_write_with_same_value_is_allowed(self):
        endpoint = self.factory.inbound_endpoint(path="stable-path")

        endpoint.write({"path": "stable-path", "name": "Stable"})

        self.assertEqual(endpoint.path, "stable-path")
        self.assertEqual(endpoint.name, "Stable")


class TestInboundHandlerDirectionEnforcement(WebhookTestCase):
    """An outbound handler cannot process an inbound event."""

    def test_outbound_handler_rejects_execute_inbound(self):
        handler = self.factory.handler(direction="outbound")
        endpoint = self.factory.inbound_endpoint()
        event = self.factory.inbound_event(endpoint)

        with self.assertRaisesRegex(ValidationError, "cannot process inbound"):
            handler.execute_inbound(event)


class TestInboundEndpointActiveLookup(WebhookTestCase):
    """``_find_active_endpoint_by_path`` ignores non-active records."""

    def setUp(self):
        super().setUp()
        self.endpoint_model = self.env["bwt.webhook.inbound.endpoint"]
        self.active_endpoint = self.factory.inbound_endpoint(path="lookup-active")
        self.factory.inbound_endpoint(path="lookup-draft", state="draft")

    def test_active_endpoint_is_returned_for_matching_path(self):
        self.assertEqual(
            self.endpoint_model._find_active_endpoint_by_path("lookup-active"),
            self.active_endpoint,
        )

    def test_draft_endpoint_is_not_returned(self):
        self.assertFalse(self.endpoint_model._find_active_endpoint_by_path("lookup-draft"))


class TestInboundEndpointDeliveryGate(WebhookTestCase):
    """A draft endpoint refuses to validate inbound requests."""

    def test_draft_endpoint_rejects_inbound_request(self):
        endpoint = self.factory.inbound_endpoint(state="draft")

        with self.assertRaisesRegex(ValidationError, "draft"):
            endpoint._validate_inbound_request(b"{}", {}, {}, {})


class TestInboundEndpointStateTransitions(WebhookTestCase):
    """``action_activate`` / ``action_set_draft`` / ``action_archive`` drive transitions."""

    def test_draft_endpoint_activate_transitions_to_active(self):
        endpoint = self.factory.inbound_endpoint(state="draft")

        endpoint.action_activate()

        self.assertEqual(endpoint.state, "active")

    def test_active_endpoint_set_draft_transitions_to_draft(self):
        endpoint = self.factory.inbound_endpoint(state="active")

        endpoint.action_set_draft()

        self.assertEqual(endpoint.state, "draft")

    def test_active_endpoint_archive_transitions_to_archived(self):
        endpoint = self.factory.inbound_endpoint(state="active")

        endpoint.action_archive()

        self.assertEqual(endpoint.state, "archived")

    def test_archived_endpoint_set_draft_transitions_to_draft(self):
        endpoint = self.factory.inbound_endpoint(state="archived")

        endpoint.action_set_draft()

        self.assertEqual(endpoint.state, "draft")


class TestInboundEndpointStateTransitionGuards(WebhookTestCase):
    """The state-transition actions raise from invalid source states."""

    def test_active_endpoint_rejects_action_activate(self):
        endpoint = self.factory.inbound_endpoint(state="active")

        with self.assertRaisesRegex(ValidationError, "Only draft inbound endpoints"):
            endpoint.action_activate()

    def test_draft_endpoint_rejects_action_set_draft(self):
        endpoint = self.factory.inbound_endpoint(state="draft")

        with self.assertRaisesRegex(ValidationError, "Only active or archived inbound endpoints"):
            endpoint.action_set_draft()

    def test_archived_endpoint_rejects_action_archive(self):
        endpoint = self.factory.inbound_endpoint(state="archived")

        with self.assertRaisesRegex(ValidationError, "Only draft or active inbound endpoints"):
            endpoint.action_archive()


class TestInboundRuleConfigurationConstraints(WebhookTestCase):
    """``_check_rule_configuration`` validates retry delay sign and target model presence."""

    def test_negative_retry_seconds_is_rejected(self):
        handler = self.factory.handler(direction="inbound")

        with self.assertRaisesRegex(ValidationError, "Retry delay must be zero"):
            self.factory.inbound_rule(handler, action_type="retry", retry_seconds=-1)

    def test_create_record_rule_without_target_model_is_rejected(self):
        handler = self.factory.handler(direction="inbound")

        with self.assertRaisesRegex(ValidationError, "Target Model is required"):
            self.factory.inbound_rule(handler, action_type="create_record")


class TestInboundRuleLookupConfigurationConstraint(WebhookTestCase):
    """``_check_lookup_configuration`` requires a source key for non-literal kinds."""

    def test_resolved_value_lookup_without_source_expression_is_rejected(self):
        handler = self.factory.handler(direction="inbound")
        rule = self.factory.inbound_rule(
            handler,
            action_type="upsert_record",
            target_model_name="res.partner",
        )

        with self.assertRaisesRegex(ValidationError, "Lookup rows require Source Key"):
            self.env["bwt.webhook.inbound.handler.rule.lookup"].create(
                {
                    "rule_id": rule.id,
                    "target_field_name": "ref",
                    "source_kind": "resolved_value",
                }
            )


class TestInboundRuleAssignmentConfigurationConstraint(WebhookTestCase):
    """``_check_assignment_configuration`` requires a source key for non-literal kinds."""

    def test_resolved_value_assignment_without_source_expression_is_rejected(self):
        handler = self.factory.handler(direction="inbound")
        rule = self.factory.inbound_rule(
            handler,
            action_type="create_record",
            target_model_name="res.partner",
        )

        with self.assertRaisesRegex(ValidationError, "Assignment rows require Source Key"):
            self.env["bwt.webhook.inbound.handler.rule.assignment"].create(
                {
                    "rule_id": rule.id,
                    "target_kind": "field",
                    "target_expression": "name",
                    "source_kind": "resolved_value",
                }
            )


class TestHandlerPythonCallbackConfiguration(WebhookTestCase):
    """``_check_python_callback_configuration`` requires both model and method."""

    def test_python_handler_without_model_or_method_is_rejected(self):
        with self.assertRaisesRegex(ValidationError, "model name and a method name"):
            self.factory.handler(execution_mode="python")


class TestHandlerExecuteInboundPythonCallback(WebhookTestCase):
    """``execute_inbound`` dispatches to a configured python callback."""

    def test_python_handler_invokes_configured_callback_and_returns_value(self):
        handler = self.factory.handler(
            direction="inbound",
            execution_mode="python",
            python_model_name="res.partner",
            python_method_name="webhook_inbound_callback_for_test",
        )
        endpoint = self.factory.inbound_endpoint(handler=handler)
        event = self.factory.inbound_event(endpoint, handler=handler)

        captured = {}

        def callback(self_model, evt):
            captured["event_id"] = evt.id
            return {"status": "done", "called": True}

        type(self.env["res.partner"]).webhook_inbound_callback_for_test = callback
        self.addCleanup(
            delattr,
            type(self.env["res.partner"]),
            "webhook_inbound_callback_for_test",
        )

        result = handler.execute_inbound(event)

        self.assertEqual(result, {"status": "done", "called": True})
        self.assertEqual(captured["event_id"], event.id)
