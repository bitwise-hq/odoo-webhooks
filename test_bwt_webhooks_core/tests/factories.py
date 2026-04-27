"""Test fixture factory for the webhooks framework.

The :class:`WebhookFactory` builds well-formed records for every model
in ``webhooks_core``, ``webhooks_inbound`` and ``webhooks_outbound``.
Tests use it to assemble exactly the state they exercise; defaults are
sensible but every field is explicitly overridable.

A single instance is created per test in
:class:`WebhookTestCase.setUp` and reused by all factory calls in that
test. Records are bound to the test transaction and rolled back
automatically.

Design rules
------------
* Each public method creates exactly one record and returns it.
* Default values are minimal but valid: a freshly created record is
  ready to use without further setup.
* Tokens are unique within a factory instance to keep ``unique``
  indexes happy even when a single test creates many records of the
  same type.
"""

import hashlib
import itertools
import json


class WebhookFactory:
    """Build webhooks framework records for tests."""

    def __init__(self, env, *, company=None):
        self.env = env
        self.company = company or env.company
        self._counter = itertools.count(1)

    # ------------------------------------------------------------------
    # Identity helpers
    # ------------------------------------------------------------------

    def next_token(self, prefix):
        """Return a unique short identifier for ``prefix``."""
        return f"{prefix}_{next(self._counter)}"

    @staticmethod
    def serialize_json(value):
        """Serialize ``value`` as the framework stores JSON columns."""
        return json.dumps(value, indent=2, sort_keys=True)

    @staticmethod
    def sha256(body):
        """Return the hex SHA-256 digest of ``body`` (str or bytes)."""
        if isinstance(body, str):
            body = body.encode("utf-8")
        return hashlib.sha256(body).hexdigest()

    # ------------------------------------------------------------------
    # Users
    # ------------------------------------------------------------------

    def user(self, *, admin=True, **overrides):
        """Create an internal user that can own webhooks.

        ``admin=True`` (default) grants the webhooks admin group.
        """
        token = self.next_token("user")
        groups = [self.env.ref("base.group_user").id]
        if admin:
            groups.append(self.env.ref("bwt_webhooks_core.group_webhooks_admin").id)
        vals = {
            "name": token,
            "login": f"{token}@example.com",
            "email": f"{token}@example.com",
            "company_id": self.company.id,
            "company_ids": [(6, 0, [self.company.id])],
            "group_ids": [(6, 0, groups)],
            "active": True,
            **overrides,
        }
        return self.env["res.users"].with_context(no_reset_password=True).create(vals)

    # ------------------------------------------------------------------
    # Handler
    # ------------------------------------------------------------------

    def handler(self, *, direction="inbound", **overrides):
        token = self.next_token("handler")
        vals = {
            "name": token,
            "code": token,
            "company_id": self.company.id,
            "direction": direction,
            "execution_mode": "model_driven",
            **overrides,
        }
        return self.env["bwt.webhook.handler"].create(vals)

    # ------------------------------------------------------------------
    # Inbound endpoint and child records
    # ------------------------------------------------------------------

    def inbound_endpoint(self, *, handler=None, **overrides):
        token = self.next_token("inbound_endpoint")
        vals = {
            "name": token,
            "path": token,
            "state": "active",
            "company_id": self.company.id,
            "handler_id": handler.id if handler else False,
            "payload_contract": "json_object",
            "delivery_identity_policy": "body_sha256",
            "replay_identity_policy": "none",
            **overrides,
        }
        return self.env["bwt.webhook.inbound.endpoint"].create(vals)

    def endpoint_source(self, endpoint, **overrides):
        token = self.next_token("source")
        vals = {
            "endpoint_id": endpoint.id,
            "field_name": token,
            "source_kind": "literal",
            "literal_value": token,
            **overrides,
        }
        return self.env["bwt.webhook.inbound.endpoint.source"].create(vals)

    def semantic_binding(self, endpoint, *, semantic_name="topic", **overrides):
        vals = {
            "endpoint_id": endpoint.id,
            "semantic_name": semantic_name,
            "value_key": self.next_token("binding"),
            **overrides,
        }
        return self.env["bwt.webhook.inbound.endpoint.semantic.binding"].create(vals)

    def signature_part(self, endpoint, *, source_kind="raw_body", **overrides):
        vals = {
            "endpoint_id": endpoint.id,
            "source_kind": source_kind,
            **overrides,
        }
        if source_kind == "literal" and "literal_value" not in overrides:
            vals["literal_value"] = self.next_token("signature_part")
        return self.env["bwt.webhook.inbound.endpoint.signature.part"].create(vals)

    # ------------------------------------------------------------------
    # Inbound event
    # ------------------------------------------------------------------

    def inbound_event(
        self,
        endpoint,
        *,
        handler=None,
        payload=None,
        headers=None,
        resolved_values=None,
        **overrides,
    ):
        token = self.next_token("inbound_event")
        payload = payload or {}
        headers = headers or {}
        request_body = overrides.pop("request_body", self.serialize_json(payload))
        body_sha256 = overrides.pop("body_sha256", self.sha256(request_body))
        vals = {
            "name": token,
            "endpoint_id": endpoint.id,
            "handler_id": handler.id if handler else endpoint.handler_id.id,
            "company_id": endpoint.company_id.id,
            "state": "received",
            "event_id": token,
            "delivery_id": token,
            "delivery_identity_key": token,
            "delivery_identity_source": "delivery_id",
            "delivery_kind": "primary",
            "resolved_values_json": self.serialize_json(resolved_values or {}),
            "body_sha256": body_sha256,
            "request_body": request_body,
            "request_headers_json": self.serialize_json(headers),
            "payload_json": self.serialize_json(payload),
            **overrides,
        }
        return self.env["bwt.webhook.inbound.event"].create(vals)

    # ------------------------------------------------------------------
    # Inbound handler rule
    # ------------------------------------------------------------------

    def inbound_rule(self, handler, *, action_type="done", **overrides):
        vals = {
            "handler_id": handler.id,
            "name": self.next_token("inbound_rule"),
            "action_type": action_type,
            **overrides,
        }
        return self.env["bwt.webhook.inbound.handler.rule"].create(vals)

    # ------------------------------------------------------------------
    # Outbound endpoint
    # ------------------------------------------------------------------

    def outbound_endpoint(self, *, handler=None, **overrides):
        token = self.next_token("outbound_endpoint")
        vals = {
            "name": token,
            "code": token,
            "state": "active",
            "company_id": self.company.id,
            "handler_id": handler.id if handler else False,
            "http_method": "post",
            "request_body_mode": "json",
            "target_hostname": "https://example.com",
            "target_path": f"/{token}",
            "timeout_seconds": 30,
            **overrides,
        }
        return self.env["bwt.webhook.outbound.endpoint"].create(vals)

    # ------------------------------------------------------------------
    # Outbound delivery
    # ------------------------------------------------------------------

    def outbound_delivery(self, endpoint, **overrides):
        token = self.next_token("outbound_delivery")
        vals = {
            "name": token,
            "endpoint_id": endpoint.id,
            **overrides,
        }
        return self.env["bwt.webhook.outbound.delivery"].create(vals)

    def outbound_context_line(self, delivery, *, key_name=None, source_kind="literal", **overrides):
        vals = {
            "delivery_id": delivery.id,
            "key_name": key_name or self.next_token("ctx"),
            "source_kind": source_kind,
            **overrides,
        }
        return self.env["bwt.webhook.outbound.delivery.context.line"].create(vals)

    # ------------------------------------------------------------------
    # Outbound handler rule
    # ------------------------------------------------------------------

    def outbound_rule(self, handler, *, result_status="send", **overrides):
        vals = {
            "handler_id": handler.id,
            "name": self.next_token("outbound_rule"),
            "result_status": result_status,
            **overrides,
        }
        return self.env["bwt.webhook.outbound.handler.rule"].create(vals)

    def outbound_rule_condition(
        self,
        rule,
        *,
        source_kind="delivery_field",
        source_expression="state",
        operator="equals",
        **overrides,
    ):
        vals = {
            "rule_id": rule.id,
            "source_kind": source_kind,
            "source_expression": source_expression,
            "operator": operator,
            **overrides,
        }
        return self.env["bwt.webhook.outbound.handler.rule.condition"].create(vals)

    def outbound_rule_assignment(
        self,
        rule,
        *,
        target_scope="payload",
        target_expression=None,
        source_kind="literal",
        **overrides,
    ):
        vals = {
            "rule_id": rule.id,
            "target_scope": target_scope,
            "target_expression": target_expression or self.next_token("target"),
            "source_kind": source_kind,
            **overrides,
        }
        return self.env["bwt.webhook.outbound.handler.rule.assignment"].create(vals)

    # ------------------------------------------------------------------
    # Outbound endpoint header / payload rules
    # ------------------------------------------------------------------

    def outbound_header_rule(self, endpoint, *, header_name=None, source_kind="literal", **overrides):
        vals = {
            "endpoint_id": endpoint.id,
            "header_name": header_name or self.next_token("header"),
            "source_kind": source_kind,
            **overrides,
        }
        return self.env["bwt.webhook.outbound.endpoint.header.rule"].create(vals)

    def outbound_payload_rule(self, endpoint, *, target_path=None, source_kind="literal", **overrides):
        vals = {
            "endpoint_id": endpoint.id,
            "target_path": target_path or self.next_token("path"),
            "source_kind": source_kind,
            **overrides,
        }
        return self.env["bwt.webhook.outbound.endpoint.payload.rule"].create(vals)

    # ------------------------------------------------------------------
    # Outbound delivery attempt
    # ------------------------------------------------------------------

    def outbound_attempt(self, delivery, *, attempt_number=None, **overrides):
        vals = {
            "delivery_id": delivery.id,
            "attempt_number": attempt_number if attempt_number is not None else next(self._counter),
            "state": "processing",
            "http_method": delivery.http_method or "post",
            "request_body_mode": delivery.request_body_mode or "json",
            "target_url": delivery.target_url,
            "request_headers_json": "{}",
            "payload_json": "{}",
            **overrides,
        }
        return self.env["bwt.webhook.outbound.delivery.attempt"].create(vals)
