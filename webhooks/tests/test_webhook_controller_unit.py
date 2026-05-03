from unittest.mock import Mock, patch

from odoo import SUPERUSER_ID
from odoo.exceptions import ValidationError
from werkzeug.exceptions import BadRequest, Forbidden, NotFound

from ..controllers import main as controller_main
from ..exceptions import WebhookSignatureValidationError, WebhookValidationError
from .common import WebhookRuleTestCase


class FakeHttpRequest:
    def __init__(self, body, headers):
        self._body = body
        self.headers = headers

    def get_data(self, cache=True):
        return self._body


class FakeIndexedEnv(dict):
    pass


class FakeRequestEnv:
    def __init__(self, base_context, returned_envs):
        self.context = dict(base_context)
        self._returned_envs = list(returned_envs)
        self.calls = []

    def __call__(self, user=None, context=None):
        self.calls.append({"user": user, "context": dict(context or {})})
        return self._returned_envs.pop(0)


class TestWebhookControllerUnit(WebhookRuleTestCase):
    def _call_inbound_webhook(self, controller, endpoint_path):
        return controller_main.WebhookController.inbound_webhook.__wrapped__(
            controller, endpoint_path
        )

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

        request_env = FakeRequestEnv(
            {"lang": "en_US", "test_flag": True},
            [
                FakeIndexedEnv({"webhook.inbound.endpoint": lookup_model}),
                FakeIndexedEnv(
                    {
                        "webhook.inbound.endpoint": endpoint_model,
                        "webhook.inbound.event": event_model,
                    }
                ),
            ],
        )
        fake_request = Mock()
        fake_request.httprequest = FakeHttpRequest(body, headers)
        fake_request.env = request_env
        fake_request.make_json_response = Mock(
            return_value={
                "status": "accepted",
                "event_id": event.id if event else False,
            }
        )
        return fake_request, request_env, lookup_model, endpoint_model, event_model

    def test_inbound_webhook_returns_accepted_json_response(self):
        controller = controller_main.WebhookController()
        endpoint = self._create_inbound_endpoint(path="controller-success")
        event = self._create_inbound_event(endpoint)
        fake_request, request_env, lookup_model, endpoint_model, event_model = (
            self._build_request(
                endpoint=endpoint,
                event=event,
                body=b'{"ok": true}',
                headers={"X-Test": "1"},
                lookup_endpoint=endpoint,
            )
        )

        with patch.object(controller_main, "request", fake_request):
            response = self._call_inbound_webhook(controller, endpoint.path)

        self.assertEqual(response, {"status": "accepted", "event_id": event.id})
        self.assertEqual(len(request_env.calls), 2)
        for call in request_env.calls:
            self.assertEqual(call["user"], SUPERUSER_ID)
            self.assertTrue(call["context"]["webhook_automated_execution"])
            self.assertTrue(call["context"]["test_flag"])
        lookup_model._find_active_endpoint_by_path.assert_called_once_with(
            endpoint.path
        )
        endpoint_model.browse.assert_called_once_with(endpoint.id)
        event_model._receive_webhook_request.assert_called_once_with(
            endpoint, b'{"ok": true}', {"X-Test": "1"}
        )
        fake_request.make_json_response.assert_called_once_with(
            {"status": "accepted", "event_id": event.id},
            status=202,
        )

    def test_inbound_webhook_raises_not_found_for_missing_endpoint(self):
        controller = controller_main.WebhookController()
        fake_request, _request_env, lookup_model, _endpoint_model, event_model = (
            self._build_request(lookup_endpoint=False)
        )

        with patch.object(controller_main, "request", fake_request):
            with self.assertRaises(NotFound):
                self._call_inbound_webhook(controller, "missing-endpoint")

        lookup_model._find_active_endpoint_by_path.assert_called_once_with(
            "missing-endpoint"
        )
        event_model._receive_webhook_request.assert_not_called()

    def test_inbound_webhook_maps_webhook_validation_errors_to_http_errors(self):
        controller = controller_main.WebhookController()
        endpoint = self._create_inbound_endpoint(path="controller-errors")
        event = self._create_inbound_event(endpoint)
        cases = [
            (
                WebhookValidationError("Bad webhook"),
                BadRequest,
                "Bad webhook",
            ),
            (
                WebhookSignatureValidationError("Bad signature"),
                Forbidden,
                "Bad signature",
            ),
            (
                ValidationError("Generic validation"),
                BadRequest,
                "Generic validation",
            ),
        ]

        for error, expected_exception, message in cases:
            with self.subTest(expected_exception=expected_exception.__name__):
                (
                    fake_request,
                    _request_env,
                    _lookup_model,
                    _endpoint_model,
                    event_model,
                ) = self._build_request(
                    endpoint=endpoint,
                    event=event,
                    receive_side_effect=error,
                    lookup_endpoint=endpoint,
                )
                with patch.object(controller_main, "request", fake_request):
                    with self.assertRaisesRegex(expected_exception, message):
                        self._call_inbound_webhook(controller, endpoint.path)
                event_model._receive_webhook_request.assert_called_once()
