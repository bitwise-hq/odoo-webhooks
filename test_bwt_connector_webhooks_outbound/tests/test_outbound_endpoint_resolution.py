"""Tests for ``get_outbound_endpoint`` resolution and the computed field."""

from odoo.exceptions import ValidationError
from odoo.tests.common import TransactionCase


def _create_endpoint(env, backend, code, path):
    return env["bwt.webhook.outbound.endpoint"].create(
        {
            "name": code,
            "code": code,
            "http_method": "post",
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
        self.endpoint = _create_endpoint(self.env, self.backend, f"primary-{self.backend.id}", "/primary")


class TestGetOutboundEndpointByCode(_BackendOutboundTestCase):
    """``get_outbound_endpoint`` filtering by ``endpoint_code``."""

    def test_matching_code_returns_endpoint(self):
        result = self.backend.get_outbound_endpoint(endpoint_code=self.endpoint.code)
        self.assertEqual(result, self.endpoint)

    def test_non_matching_code_required_raises(self):
        with self.assertRaisesRegex(ValidationError, "No outbound webhook endpoint with code"):
            self.backend.get_outbound_endpoint(
                endpoint_code="no-such-code",
                required=True,
            )

    def test_non_matching_code_not_required_returns_empty(self):
        result = self.backend.get_outbound_endpoint(
            endpoint_code="no-such-code",
            required=False,
        )
        self.assertFalse(result)


class TestGetOutboundEndpointWithoutCode(_BackendOutboundTestCase):
    """``get_outbound_endpoint`` with no ``endpoint_code`` argument."""

    def test_single_linked_endpoint_is_returned(self):
        result = self.backend.get_outbound_endpoint()
        self.assertEqual(result, self.endpoint)

    def test_no_linked_endpoint_required_raises(self):
        bare = self.env[self.BACKEND_MODEL].create({"name": "Bare", "code": "bare"})

        with self.assertRaisesRegex(ValidationError, "No outbound webhook endpoint is linked"):
            bare.get_outbound_endpoint(required=True)

    def test_no_linked_endpoint_not_required_returns_empty(self):
        bare = self.env[self.BACKEND_MODEL].create({"name": "Bare", "code": "bare"})

        result = bare.get_outbound_endpoint(required=False)

        self.assertFalse(result)

    def test_multiple_linked_endpoints_raises(self):
        _create_endpoint(self.env, self.backend, f"alt-{self.backend.id}", "/alt")

        with self.assertRaisesRegex(ValidationError, "Multiple outbound webhook endpoints"):
            self.backend.get_outbound_endpoint()


class TestOutboundEndpointComputedField(_BackendOutboundTestCase):
    """``outbound_endpoint_id`` resolves to the first linked endpoint."""

    def test_compute_returns_linked_endpoint(self):
        self.assertEqual(self.backend.outbound_endpoint_id, self.endpoint)

    def test_compute_returns_empty_when_no_endpoint_linked(self):
        bare = self.env[self.BACKEND_MODEL].create({"name": "Bare", "code": "bare"})

        self.assertFalse(bare.outbound_endpoint_id)

    def test_compute_returns_empty_when_reference_is_unset(self):
        # Exercise the ``if not ref: … continue`` branch by forcing
        # ``_get_connector_backend_reference`` to return ``False``.
        from unittest.mock import patch

        with patch.object(type(self.backend), "_get_connector_backend_reference", lambda s: False):
            result = self.backend.outbound_endpoint_id

        self.assertFalse(result)
