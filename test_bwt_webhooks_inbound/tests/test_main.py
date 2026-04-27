"""Behavioral tests for :mod:`webhooks_inbound.controllers.main`.

The controller is the public HTTP entry point for inbound webhook
deliveries. It looks up an active endpoint by URL path, hands the
raw request to ``webhook.inbound.event._receive_webhook_request`` under
the SUPERUSER context, and translates framework exceptions into the
appropriate HTTP error responses.
"""

from unittest.mock import Mock, patch

from werkzeug.exceptions import BadRequest, Forbidden, NotFound

from odoo import SUPERUSER_ID
from odoo.exceptions import ValidationError

from odoo.addons.bwt_webhooks_core.exceptions import (
    WebhookSignatureValidationError,
    WebhookValidationError,
)
from odoo.addons.test_bwt_webhooks_core.tests.base import WebhookTestCase

from odoo.addons.bwt_webhooks_inbound.controllers import main as controller_main


class _FakeHttpRequest:
    def __init__(self, body, headers):
        self._body = body
        self.headers = headers

    def get_data(self, cache=True):
        return self._body


class _FakeIndexedEnv(dict):
    pass


class _FakeRequestEnv:
    def __init__(self, base_context, returned_envs):
        self.context = dict(base_context)
        self._returned_envs = list(returned_envs)
        self.calls = []

    def __call__(self, user=None, context=None):
        self.calls.append({"user": user, "context": dict(context or {})})
        return self._returned_envs.pop(0)


class _ControllerTestBase(WebhookTestCase):
    """Shared scaffolding to invoke the inbound webhook controller in isolation."""

    def _call_inbound_webhook(self, controller, endpoint_path):
        return controller_main.WebhookController.inbound_webhook.__wrapped__(controller, endpoint_path)

    def _build_request(
        self,
        *,
        endpoint=None,
        event=None,
        body=b"{}",
        headers=None,
        receive_side_effect=None,
        lookup_endpoint=None,
    ):
        headers = headers or {"X-Test": "1"}
        lookup_model = Mock()
        lookup_model._find_active_endpoint_by_path.return_value = lookup_endpoint

        endpoint_model = Mock()
        endpoint_model.browse.return_value = endpoint

        event_model = Mock()
        if receive_side_effect is not None:
            event_model._receive_webhook_request.side_effect = receive_side_effect
        else:
            event_model._receive_webhook_request.return_value = event

        request_env = _FakeRequestEnv(
            {"lang": "en_US", "test_flag": True},
            [
                _FakeIndexedEnv({"bwt.webhook.inbound.endpoint": lookup_model}),
                _FakeIndexedEnv(
                    {
                        "bwt.webhook.inbound.endpoint": endpoint_model,
                        "bwt.webhook.inbound.event": event_model,
                    }
                ),
            ],
        )
        fake_request = Mock()
        fake_request.httprequest = _FakeHttpRequest(body, headers)
        fake_request.env = request_env
        fake_request.make_json_response = Mock(
            return_value={
                "status": "accepted",
                "event_id": event.id if event else False,
            }
        )
        return fake_request, request_env, lookup_model, endpoint_model, event_model


class TestInboundWebhookSuccessResponse(_ControllerTestBase):
    """The happy path returns a 202 JSON response and runs as SUPERUSER."""

    REQUEST_BODY = b'{"ok": true}'
    REQUEST_HEADERS = {"X-Test": "1"}

    def setUp(self):
        super().setUp()
        self.controller = controller_main.WebhookController()
        self.endpoint = self.factory.inbound_endpoint(path="controller-success")
        self.event = self.factory.inbound_event(self.endpoint)
        (
            self.fake_request,
            self.request_env,
            self.lookup_model,
            self.endpoint_model,
            self.event_model,
        ) = self._build_request(
            endpoint=self.endpoint,
            event=self.event,
            body=self.REQUEST_BODY,
            headers=self.REQUEST_HEADERS,
            lookup_endpoint=self.endpoint,
        )

    def _invoke(self):
        with patch.object(controller_main, "request", self.fake_request):
            return self._call_inbound_webhook(self.controller, self.endpoint.path)

    def test_success_returns_accepted_json_response(self):
        response = self._invoke()

        self.assertEqual(response, {"status": "accepted", "event_id": self.event.id})

    def test_success_returns_response_with_status_code_202(self):
        self._invoke()

        self.fake_request.make_json_response.assert_called_once_with(
            {"status": "accepted", "event_id": self.event.id},
            status=202,
        )

    def test_success_runs_lookup_and_execution_envs_as_superuser(self):
        self._invoke()

        self.assertEqual(len(self.request_env.calls), 2)
        for call in self.request_env.calls:
            self.assertEqual(call["user"], SUPERUSER_ID)
            self.assertTrue(call["context"]["webhook_automated_execution"])
            self.assertTrue(call["context"]["test_flag"])

    def test_success_calls_lookup_browse_and_receive_with_request_arguments(self):
        self._invoke()

        self.lookup_model._find_active_endpoint_by_path.assert_called_once_with(self.endpoint.path)
        self.endpoint_model.browse.assert_called_once_with(self.endpoint.id)
        self.event_model._receive_webhook_request.assert_called_once_with(self.endpoint, self.REQUEST_BODY, self.REQUEST_HEADERS)


class TestInboundWebhookEndpointLookup(_ControllerTestBase):
    """A missing endpoint raises ``NotFound`` and skips the receive helper."""

    def setUp(self):
        super().setUp()
        self.controller = controller_main.WebhookController()
        (
            self.fake_request,
            self.request_env,
            self.lookup_model,
            self.endpoint_model,
            self.event_model,
        ) = self._build_request(lookup_endpoint=False)

    def test_missing_endpoint_raises_not_found(self):
        with patch.object(controller_main, "request", self.fake_request):
            with self.assertRaises(NotFound):
                self._call_inbound_webhook(self.controller, "missing-endpoint")

        self.lookup_model._find_active_endpoint_by_path.assert_called_once_with("missing-endpoint")

    def test_missing_endpoint_does_not_invoke_receive_webhook_request(self):
        with patch.object(controller_main, "request", self.fake_request):
            with self.assertRaises(NotFound):
                self._call_inbound_webhook(self.controller, "missing-endpoint")

        self.event_model._receive_webhook_request.assert_not_called()


class TestInboundWebhookErrorMapping(_ControllerTestBase):
    """Framework exceptions from ``_receive_webhook_request`` map to HTTP errors."""

    def setUp(self):
        super().setUp()
        self.controller = controller_main.WebhookController()
        self.endpoint = self.factory.inbound_endpoint(path="controller-errors")
        self.event = self.factory.inbound_event(self.endpoint)

    def _build(self, error):
        return self._build_request(
            endpoint=self.endpoint,
            event=self.event,
            receive_side_effect=error,
            lookup_endpoint=self.endpoint,
        )

    def test_webhook_validation_error_is_mapped_to_bad_request(self):
        fake_request, _env, _lookup, _ep, event_model = self._build(WebhookValidationError("Bad webhook"))

        with patch.object(controller_main, "request", fake_request):
            with self.assertRaisesRegex(BadRequest, "Bad webhook"):
                self._call_inbound_webhook(self.controller, self.endpoint.path)

        event_model._receive_webhook_request.assert_called_once()

    def test_webhook_signature_validation_error_is_mapped_to_forbidden(self):
        fake_request, _env, _lookup, _ep, event_model = self._build(WebhookSignatureValidationError("Bad signature"))

        with patch.object(controller_main, "request", fake_request):
            with self.assertRaisesRegex(Forbidden, "Bad signature"):
                self._call_inbound_webhook(self.controller, self.endpoint.path)

        event_model._receive_webhook_request.assert_called_once()

    def test_generic_validation_error_is_mapped_to_bad_request(self):
        fake_request, _env, _lookup, _ep, event_model = self._build(ValidationError("Generic validation"))

        with patch.object(controller_main, "request", fake_request):
            with self.assertRaisesRegex(BadRequest, "Generic validation"):
                self._call_inbound_webhook(self.controller, self.endpoint.path)

        event_model._receive_webhook_request.assert_called_once()
