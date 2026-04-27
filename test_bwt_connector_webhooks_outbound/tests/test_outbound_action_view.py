"""Tests for ``action_view_outbound_endpoint`` (single vs. list variants)."""

from odoo.exceptions import ValidationError
from odoo.tests.common import TransactionCase


def _create_endpoint(env, backend, code, path):
    return env["bwt.webhook.outbound.endpoint"].create(
        {
            "name": code,
            "code": code,
            "target_hostname": "https://example.com",
            "target_path": path,
            "connector_backend_ref": f"{backend._name},{backend.id}",
        }
    )


class _BackendOutboundTestCase(TransactionCase):
    BACKEND_MODEL = "bwt.test.connector.webhook.backend.outbound"

    def setUp(self):
        super().setUp()
        self.backend = self.env[self.BACKEND_MODEL].create({"name": "Acme", "code": "acme"})
        self.primary = _create_endpoint(self.env, self.backend, f"primary-{self.backend.id}", "/primary")


class TestActionViewOutboundEndpoint(_BackendOutboundTestCase):
    """Returns a list-mode action when more than one endpoint exists."""

    def test_two_endpoints_returns_list_mode_action(self):
        _create_endpoint(self.env, self.backend, f"alt-{self.backend.id}", "/alt")

        action = self.backend.action_view_outbound_endpoint()

        self.assertEqual(action["view_mode"], "list,form")
        self.assertIn("connector_backend_ref", action["domain"][0])

    def test_single_endpoint_returns_form_mode_action(self):
        action = self.backend.action_view_outbound_endpoint()

        self.assertEqual(action["view_mode"], "form")
        self.assertEqual(action["res_id"], self.primary.id)


class TestActionViewOutboundEndpointWithoutLink(TransactionCase):
    """Raises when no endpoints are linked to the backend."""

    def test_bare_backend_without_endpoints_raises(self):
        backend = self.env["bwt.test.connector.webhook.backend.outbound.bare"].create({"name": "x", "code": "x"})

        with self.assertRaisesRegex(ValidationError, "No outbound webhook endpoint"):
            backend.action_view_outbound_endpoint()
