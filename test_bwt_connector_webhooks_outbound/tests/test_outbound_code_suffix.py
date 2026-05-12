"""Tests for backend-scoped ``code_suffix`` derivation on outbound endpoints."""

from odoo.exceptions import ValidationError
from odoo.tests.common import TransactionCase
from odoo.tools import mute_logger


class _BackendOutboundTestCase(TransactionCase):
    BACKEND_MODEL = "bwt.test.connector.webhook.backend.outbound"

    def setUp(self):
        super().setUp()
        self.backend = self.env[self.BACKEND_MODEL].create({"name": "Acme", "code": "acme"})


class TestCodeSuffixDerivation(_BackendOutboundTestCase):
    def test_code_is_derived_from_suffix_and_backend_on_create(self):
        endpoint = self.env["bwt.webhook.outbound.endpoint"].create(
            {
                "name": "Customer Create",
                "code_suffix": "customer-create",
                "http_method": "post",
                "target_hostname": "https://example.com",
                "target_path": "/v1/customers",
                "connector_backend_ref": f"{self.backend._name},{self.backend.id}",
            }
        )

        prefix = self.backend._build_backend_scoped_technical_name("customer-create")
        self.assertEqual(endpoint.code, prefix)
        self.assertEqual(endpoint.code_suffix, "customer-create")

    def test_pre_link_seed_uses_suffix_as_placeholder(self):
        endpoint = self.env["bwt.webhook.outbound.endpoint"].create(
            {
                "name": "Customer Create (seed)",
                "code_suffix": "customer-create",
                "http_method": "post",
                "target_hostname": "https://example.com",
                "target_path": "/v1/customers",
            }
        )

        # No backend ref -> the suffix is used as the bare code
        # placeholder so the unique(code) constraint stays satisfied.
        self.assertEqual(endpoint.code, "customer-create")

    def test_assigning_backend_ref_recomputes_code(self):
        endpoint = self.env["bwt.webhook.outbound.endpoint"].create(
            {
                "name": "Customer Update",
                "code_suffix": "customer-update",
                "http_method": "post",
                "target_hostname": "https://example.com",
                "target_path": "/v1/customers/{customer_id}",
            }
        )
        self.assertEqual(endpoint.code, "customer-update")

        endpoint.write({"connector_backend_ref": f"{self.backend._name},{self.backend.id}"})

        prefix = self.backend._build_backend_scoped_technical_name("customer-update")
        self.assertEqual(endpoint.code, prefix)

    def test_two_backends_can_share_suffix(self):
        backend2 = self.env[self.BACKEND_MODEL].create({"name": "Beta", "code": "beta"})
        endpoint1 = self.env["bwt.webhook.outbound.endpoint"].create(
            {
                "name": "Customer Create A",
                "code_suffix": "customer-create",
                "http_method": "post",
                "target_hostname": "https://example.com",
                "target_path": "/v1/customers",
                "connector_backend_ref": f"{self.backend._name},{self.backend.id}",
            }
        )
        endpoint2 = self.env["bwt.webhook.outbound.endpoint"].create(
            {
                "name": "Customer Create B",
                "code_suffix": "customer-create",
                "http_method": "post",
                "target_hostname": "https://example.com",
                "target_path": "/v1/customers",
                "connector_backend_ref": f"{backend2._name},{backend2.id}",
            }
        )

        self.assertNotEqual(endpoint1.code, endpoint2.code)

    def test_duplicate_suffix_within_same_backend_is_rejected(self):
        self.env["bwt.webhook.outbound.endpoint"].create(
            {
                "name": "Customer Create",
                "code_suffix": "customer-create",
                "http_method": "post",
                "target_hostname": "https://example.com",
                "target_path": "/v1/customers",
                "connector_backend_ref": f"{self.backend._name},{self.backend.id}",
            }
        )
        with self.assertRaises(Exception), mute_logger("odoo.sql_db"), self.env.cr.savepoint():  # IntegrityError or ValidationError
            self.env["bwt.webhook.outbound.endpoint"].create(
                {
                    "name": "Customer Create dup",
                    "code_suffix": "customer-create",
                    "http_method": "post",
                    "target_hostname": "https://example.com",
                    "target_path": "/v1/customers",
                    "connector_backend_ref": f"{self.backend._name},{self.backend.id}",
                }
            )
            self.env.cr.flush()


class TestGetOutboundEndpointBySuffix(_BackendOutboundTestCase):
    def setUp(self):
        super().setUp()
        self.endpoint = self.env["bwt.webhook.outbound.endpoint"].create(
            {
                "name": "Primary",
                "code_suffix": "primary",
                "http_method": "post",
                "target_hostname": "https://example.com",
                "target_path": "/p",
                "connector_backend_ref": f"{self.backend._name},{self.backend.id}",
            }
        )

    def test_match_by_suffix(self):
        result = self.backend.get_outbound_endpoint(code_suffix="primary")
        self.assertEqual(result, self.endpoint)

    def test_unknown_suffix_required_raises(self):
        with self.assertRaisesRegex(ValidationError, "code suffix"):
            self.backend.get_outbound_endpoint(code_suffix="nope")

    def test_unknown_suffix_optional_returns_empty(self):
        self.assertFalse(self.backend.get_outbound_endpoint(code_suffix="nope", required=False))


class TestDeriveConnectorEndpointCodeEdgeCases(_BackendOutboundTestCase):
    """Edge cases in ``_derive_connector_endpoint_code``."""

    def test_ref_as_recordset_not_string(self):
        """Non-string ref (line 64: ``backend = ref``) uses the record directly."""
        result = self.env["bwt.webhook.outbound.endpoint"]._derive_connector_endpoint_code({"code_suffix": "my-suffix", "connector_backend_ref": self.backend})
        expected = self.backend._build_backend_scoped_technical_name("my-suffix")
        self.assertEqual(result, expected)

    def test_non_existent_backend_returns_none(self):
        """When the referenced record no longer exists, derivation returns None."""
        # Use a reference string pointing to a non-existent ID so .exists() is empty
        ref_string = f"{self.BACKEND_MODEL},999999999"
        result = self.env["bwt.webhook.outbound.endpoint"]._derive_connector_endpoint_code({"code_suffix": "any-suffix", "connector_backend_ref": ref_string})
        self.assertIsNone(result)


class TestConnectorEndpointWriteNoDerived(_BackendOutboundTestCase):
    """``write()`` when derived code is None falls through to ``super().write(vals)``."""

    def setUp(self):
        super().setUp()
        self.endpoint = self.env["bwt.webhook.outbound.endpoint"].create(
            {
                "name": "Write Test Endpoint",
                "code_suffix": "write-test",
                "http_method": "post",
                "target_hostname": "https://example.com",
                "target_path": "/write",
                "connector_backend_ref": f"{self.BACKEND_MODEL},{self.backend.id}",
            }
        )

    def test_write_clears_backend_ref_so_derived_is_none(self):
        """Writing a non-existent backend ref causes derived=None → super().write()."""
        self.endpoint.write(
            {
                "connector_backend_ref": f"{self.BACKEND_MODEL},999999999",
                "code_suffix": "write-test",
            }
        )
        # After clearing the backend ref, code stays unchanged (super().write applied)
        self.assertFalse(self.endpoint.connector_backend_ref)


class TestConnectorEndpointHostnameResolution(_BackendOutboundTestCase):
    """Hostname-resolution branch coverage."""

    def setUp(self):
        super().setUp()
        self.endpoint_no_backend = self.env["bwt.webhook.outbound.endpoint"].create(
            {
                "name": "Standalone Hostname",
                "code": "standalone-hostname",
                "http_method": "post",
                "target_hostname": "https://standalone.example.com",
                "target_path": "/x",
            }
        )

    def test_hostname_not_resolved_externally_when_no_backend(self):
        """False branch of ``if self.connector_backend_ref:`` (line 117: super())."""
        result = self.endpoint_no_backend._outbound_hostname_resolved_externally()
        self.assertFalse(result)

    def test_get_hostname_falls_to_super_when_no_backend(self):
        """``_get_outbound_target_hostname`` with no backend uses stored hostname."""
        result = self.endpoint_no_backend._get_outbound_target_hostname()
        self.assertEqual(result, "https://standalone.example.com")

    def test_get_hostname_falls_to_super_when_resolver_attribute_missing(self):
        """``if resolver:`` False branch when backend has no resolver attribute."""
        from unittest.mock import patch

        endpoint = self.env["bwt.webhook.outbound.endpoint"].create(
            {
                "name": "No Resolver",
                "code": f"no-resolver-{self.backend.id}",
                "http_method": "post",
                "target_hostname": "https://fallback.example.com",
                "target_path": "/x",
                "connector_backend_ref": f"{self.BACKEND_MODEL},{self.backend.id}",
            }
        )
        # Patch the class so getattr finds None for this attribute
        with patch.object(type(self.backend), "_get_outbound_api_base_url", None):
            result = endpoint._get_outbound_target_hostname()

        self.assertEqual(result, "https://fallback.example.com")

    def test_get_hostname_returns_resolver_result_when_truthy(self):
        """``if resolved:`` True branch (line 127) when resolver returns a URL."""
        from unittest.mock import patch

        endpoint = self.env["bwt.webhook.outbound.endpoint"].create(
            {
                "name": "Resolver Returns URL",
                "code": f"resolver-url-{self.backend.id}",
                "http_method": "post",
                "target_hostname": "https://fallback.example.com",
                "target_path": "/x",
                "connector_backend_ref": f"{self.BACKEND_MODEL},{self.backend.id}",
            }
        )
        with patch.object(type(self.backend), "_get_outbound_api_base_url", return_value="https://resolved.example.com"):
            result = endpoint._get_outbound_target_hostname()

        self.assertEqual(result, "https://resolved.example.com")
