import hashlib
import json

from odoo.tests.common import TransactionCase


class WebhookRuleTestCase(TransactionCase):
    def setUp(self):
        super().setUp()
        self.company = self.env.company
        self.internal_user_group = self.env.ref("base.group_user")
        self.webhook_admin_group = self.env.ref("webhooks.group_webhooks_admin")
        self._token_index = 0
        self.execution_user = (
            self.env["res.users"]
            .with_context(no_reset_password=True)
            .create(
                {
                    "name": "Webhook Test User",
                    "login": "webhook_test_user",
                    "email": "webhook.test@example.com",
                    "company_id": self.company.id,
                    "company_ids": [(6, 0, [self.company.id])],
                    "group_ids": [
                        (
                            6,
                            0,
                            [self.internal_user_group.id, self.webhook_admin_group.id],
                        )
                    ],
                }
            )
        )

    def _next_token(self, prefix):
        self._token_index += 1
        return f"{prefix}_{self._token_index}"

    def _serialize(self, value):
        return json.dumps(value, indent=2, sort_keys=True)

    def _create_handler(self, *, direction="inbound", **values):
        token = self._next_token("handler")
        create_vals = {
            "name": values.pop("name", token),
            "code": values.pop("code", token),
            "company_id": self.company.id,
            "direction": values.pop("direction", direction),
            "execution_mode": values.pop("execution_mode", "model_driven"),
        }
        create_vals.update(values)
        return self.env["webhook.handler"].create(create_vals)

    def _create_inbound_endpoint(self, *, handler=False, **values):
        token = self._next_token("inbound_endpoint")
        create_vals = {
            "name": values.pop("name", token),
            "path": values.pop("path", token),
            "state": values.pop("state", "active"),
            "company_id": self.company.id,
            "execution_user_id": values.pop(
                "execution_user_id", self.execution_user.id
            ),
            "handler_id": values.pop("handler_id", handler.id if handler else False),
            "payload_contract": values.pop("payload_contract", "json_object"),
            "delivery_identity_policy": values.pop(
                "delivery_identity_policy", "body_sha256"
            ),
            "replay_identity_policy": values.pop("replay_identity_policy", "none"),
        }
        create_vals.update(values)
        return self.env["webhook.endpoint"].create(create_vals)

    def _create_outbound_endpoint(self, *, handler=False, **values):
        token = self._next_token("outbound_endpoint")
        create_vals = {
            "name": values.pop("name", token),
            "code": values.pop("code", token),
            "state": values.pop("state", "active"),
            "company_id": self.company.id,
            "execution_user_id": values.pop(
                "execution_user_id", self.execution_user.id
            ),
            "handler_id": values.pop("handler_id", handler.id if handler else False),
            "http_method": values.pop("http_method", "post"),
            "target_hostname": values.pop("target_hostname", "https://example.com"),
            "target_path": values.pop("target_path", f"/{token}"),
            "timeout_seconds": values.pop("timeout_seconds", 30),
        }
        create_vals.update(values)
        return self.env["webhook.outbound.endpoint"].create(create_vals)

    def _create_inbound_event(
        self,
        endpoint,
        *,
        handler=False,
        resolved_values=None,
        payload=None,
        headers=None,
        **values,
    ):
        token = self._next_token("inbound_event")
        payload_value = payload or {}
        headers_value = headers or {}
        request_body = values.pop("request_body", self._serialize(payload_value))
        body_sha256 = hashlib.sha256(request_body.encode("utf-8")).hexdigest()
        create_vals = {
            "name": values.pop("name", token),
            "endpoint_id": endpoint.id,
            "execution_user_id": values.pop(
                "execution_user_id", endpoint.execution_user_id.id
            ),
            "handler_id": values.pop(
                "handler_id", handler.id if handler else endpoint.handler_id.id
            ),
            "company_id": values.pop("company_id", endpoint.company_id.id),
            "partner_id": values.pop("partner_id", endpoint.partner_id.id),
            "state": values.pop("state", "received"),
            "topic": values.pop("topic", False),
            "event_type": values.pop("event_type", False),
            "event_id": values.pop("event_id", token),
            "delivery_id": values.pop("delivery_id", token),
            "delivery_identity_key": values.pop("delivery_identity_key", token),
            "delivery_identity_source": values.pop(
                "delivery_identity_source", "delivery_id"
            ),
            "replay_identity_key": values.pop("replay_identity_key", False),
            "replay_identity_source": values.pop("replay_identity_source", False),
            "delivery_kind": values.pop("delivery_kind", "primary"),
            "resolved_values_json": values.pop(
                "resolved_values_json", self._serialize(resolved_values or {})
            ),
            "body_sha256": values.pop("body_sha256", body_sha256),
            "request_body": request_body,
            "request_headers_json": values.pop(
                "request_headers_json", self._serialize(headers_value)
            ),
            "payload_json": values.pop("payload_json", self._serialize(payload_value)),
        }
        create_vals.update(values)
        return self.env["webhook.inbound.event"].create(create_vals)

    def _create_outbound_delivery(self, endpoint, **values):
        token = self._next_token("outbound_delivery")
        create_vals = {
            "name": values.pop("name", token),
            "endpoint_id": endpoint.id,
        }
        create_vals.update(values)
        return self.env["webhook.outbound.delivery"].create(create_vals)

    def _create_outbound_context_line(self, delivery, **values):
        create_vals = {
            "delivery_id": delivery.id,
            "key_name": values.pop("key_name"),
            "source_kind": values.pop("source_kind", "literal"),
            "literal_value": values.pop("literal_value", False),
            "source_expression": values.pop("source_expression", False),
        }
        create_vals.update(values)
        return self.env["webhook.outbound.delivery.context.line"].create(create_vals)
