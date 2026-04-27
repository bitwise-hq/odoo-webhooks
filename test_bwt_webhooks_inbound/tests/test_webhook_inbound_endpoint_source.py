"""Behavioral tests for :class:`webhook.inbound.endpoint.source`.

The source record describes a single way to extract a value from an
incoming webhook request (a header, a header parameter, a payload
path, a literal value or a computed method). Multiple sources can
share a ``field_name`` to express ordered fallbacks.

Test suites in this module:

* :class:`TestEndpointSourceFieldNameNormalization`
* :class:`TestEndpointSourceRequiredFieldsByKind`
* :class:`TestEndpointResolvedValueExtraction`
* :class:`TestEndpointPayloadPathExtraction`
* :class:`TestEndpointComputedSourceFailure`
* :class:`TestEndpointConfiguredFieldEnumeration`
* :class:`TestEndpointSourceResolveValueByKind`
* :class:`TestEndpointSourceTransforms`
* :class:`TestEndpointSourceWriteRevalidation`
* :class:`TestEndpointComputedSourceSuccess`
* :class:`TestEndpointFieldCandidateResolution`
"""

import hashlib

from unittest.mock import patch

from odoo.exceptions import ValidationError

from odoo.addons.bwt_webhooks_core.exceptions import WebhookProcessingConfigurationError
from odoo.addons.test_bwt_webhooks_core.tests.base import WebhookTestCase


class TestEndpointSourceFieldNameNormalization(WebhookTestCase):
    """``field_name`` is trimmed of outer whitespace on create and write."""

    def setUp(self):
        super().setUp()
        self.endpoint = self.factory.inbound_endpoint()

    def test_field_name_is_trimmed_on_create(self):
        source = self.factory.endpoint_source(self.endpoint, field_name="  topic_key  ", literal_value="topic-value")

        self.assertEqual(source.field_name, "topic_key")

    def test_field_name_is_trimmed_on_write(self):
        source = self.factory.endpoint_source(self.endpoint, field_name="initial", literal_value="topic-value")

        source.field_name = "  normalized_key  "

        self.assertEqual(source.field_name, "normalized_key")

    def test_blank_field_name_is_rejected_on_create(self):
        with self.assertRaisesRegex(ValidationError, "field key"):
            self.factory.endpoint_source(self.endpoint, field_name="   ", literal_value="value")


class TestEndpointSourceRequiredFieldsByKind(WebhookTestCase):
    """A source of each ``source_kind`` rejects creation when its required field is missing."""

    def setUp(self):
        super().setUp()
        self.endpoint = self.factory.inbound_endpoint()
        self.source_model = self.env["bwt.webhook.inbound.endpoint.source"]

    def test_header_source_without_header_name_is_rejected(self):
        with self.assertRaisesRegex(ValidationError, "header name"):
            self.source_model.create(
                {
                    "endpoint_id": self.endpoint.id,
                    "field_name": "header_key",
                    "source_kind": "header",
                }
            )

    def test_header_param_source_without_parameter_name_is_rejected(self):
        with self.assertRaisesRegex(ValidationError, "parameter name"):
            self.source_model.create(
                {
                    "endpoint_id": self.endpoint.id,
                    "field_name": "header_param_key",
                    "source_kind": "header_param",
                    "header_name": "Stripe-Signature",
                }
            )

    def test_payload_path_source_without_path_is_rejected(self):
        with self.assertRaisesRegex(ValidationError, "payload path"):
            self.source_model.create(
                {
                    "endpoint_id": self.endpoint.id,
                    "field_name": "payload_key",
                    "source_kind": "payload_path",
                }
            )

    def test_literal_source_without_literal_value_is_rejected(self):
        with self.assertRaisesRegex(ValidationError, "literal value"):
            self.source_model.create(
                {
                    "endpoint_id": self.endpoint.id,
                    "field_name": "literal_key",
                    "source_kind": "literal",
                    "literal_value": False,
                }
            )

    def test_computed_source_without_method_name_is_rejected(self):
        with self.assertRaisesRegex(ValidationError, "computed method"):
            self.source_model.create(
                {
                    "endpoint_id": self.endpoint.id,
                    "field_name": "computed_key",
                    "source_kind": "computed",
                }
            )


class TestEndpointResolvedValueExtraction(WebhookTestCase):
    """``_extract_resolved_values`` applies fallbacks, joiners, normalization and hashing."""

    def setUp(self):
        super().setUp()
        self.endpoint = self.factory.inbound_endpoint()
        self.body = b"{}"
        self.headers = {"X-Auth": "ToKen"}
        self.payload = {"data": {"items": [{"sku": "ABC"}]}}

    def test_required_header_falling_back_to_literals_uses_lower_candidate_sequence(
        self,
    ):
        self.factory.endpoint_source(
            self.endpoint,
            field_name="delivery_key",
            source_kind="header",
            header_name="X-Delivery",
            required=True,
        )
        self.factory.endpoint_source(
            self.endpoint,
            field_name="delivery_key",
            source_kind="literal",
            literal_value="fallback",
            candidate_sequence=20,
            joiner=":",
            sequence=1,
        )
        self.factory.endpoint_source(
            self.endpoint,
            field_name="delivery_key",
            source_kind="literal",
            literal_value="delivery",
            candidate_sequence=20,
            normalize_mode="upper",
            sequence=2,
        )

        resolved = self.endpoint._extract_resolved_values(self.body, self.headers, self.payload)

        self.assertEqual(resolved["delivery_key"], "fallback:DELIVERY")

    def test_normalize_mode_lower_and_hash_algorithm_are_applied_after_extraction(self):
        self.factory.endpoint_source(
            self.endpoint,
            field_name="auth_hash",
            source_kind="header",
            header_name="X-Auth",
            normalize_mode="lower",
            hash_algorithm="sha256",
        )

        resolved = self.endpoint._extract_resolved_values(self.body, self.headers, self.payload)

        expected = hashlib.sha256("token".encode("utf-8")).hexdigest()
        self.assertEqual(resolved["auth_hash"], expected)

    def test_payload_path_with_index_extracts_nested_value_as_json(self):
        self.factory.endpoint_source(
            self.endpoint,
            field_name="payload_item",
            source_kind="payload_path",
            payload_path="data.items.0",
        )

        resolved = self.endpoint._extract_resolved_values(self.body, self.headers, self.payload)

        self.assertEqual(resolved["payload_item"], '{"sku": "ABC"}')


class TestEndpointPayloadPathExtraction(WebhookTestCase):
    """``_extract_payload_path_value`` returns falsy when the path is missing."""

    def setUp(self):
        super().setUp()
        self.endpoint = self.factory.inbound_endpoint()
        self.payload = {"data": {"items": [{"sku": "ABC"}]}}

    def test_unknown_dict_key_returns_falsy(self):
        self.assertFalse(self.endpoint._extract_payload_path_value(self.payload, "data.items.foo"))

    def test_out_of_range_list_index_returns_falsy(self):
        self.assertFalse(self.endpoint._extract_payload_path_value(self.payload, "data.items.9"))

    def test_traversing_through_string_returns_falsy(self):
        self.assertFalse(self.endpoint._extract_payload_path_value("plain-text", "data"))


class TestEndpointComputedSourceFailure(WebhookTestCase):
    """A computed source pointing at a missing method raises a configuration error."""

    def test_missing_computed_method_raises_when_field_value_is_extracted(self):
        endpoint = self.factory.inbound_endpoint()
        self.factory.endpoint_source(
            endpoint,
            field_name="missing_computed",
            source_kind="computed",
            computed_method="does_not_exist",
        )

        with self.assertRaisesRegex(WebhookProcessingConfigurationError, "does_not_exist"):
            endpoint._extract_field_value("missing_computed", b"{}", {}, {})


class TestEndpointConfiguredFieldEnumeration(WebhookTestCase):
    """``_get_configured_field_names`` returns the sorted, distinct field names."""

    def test_field_names_are_sorted_and_deduplicated(self):
        endpoint = self.factory.inbound_endpoint()
        self.factory.endpoint_source(
            endpoint,
            field_name="delivery_key",
            source_kind="literal",
            literal_value="delivery",
        )
        self.factory.endpoint_source(
            endpoint,
            field_name="auth_hash",
            source_kind="header",
            header_name="X-Auth",
        )
        self.factory.endpoint_source(
            endpoint,
            field_name="payload_item",
            source_kind="payload_path",
            payload_path="data.items.0",
        )

        names = endpoint._get_configured_field_names()

        self.assertEqual(names, ["auth_hash", "delivery_key", "payload_item"])

    def test_endpoint_without_sources_returns_empty_list(self):
        endpoint = self.factory.inbound_endpoint()

        self.assertEqual(endpoint._get_configured_field_names(), [])


class TestEndpointSourceResolveValueByKind(WebhookTestCase):
    """``_resolve_value`` dispatches to the correct extractor for each source kind."""

    def setUp(self):
        super().setUp()
        self.endpoint = self.factory.inbound_endpoint()

    def test_body_sha256_source_returns_hex_digest_of_body(self):
        body = b'{"x": 1}'
        line = self.factory.endpoint_source(
            self.endpoint,
            field_name="body_digest",
            source_kind="body_sha256",
        )

        result = line._resolve_value(self.endpoint, body, {}, {})

        self.assertEqual(result, hashlib.sha256(body).hexdigest())

    def test_return_all_wraps_scalar_value_in_list(self):
        line = self.factory.endpoint_source(
            self.endpoint,
            field_name="single",
            source_kind="literal",
            literal_value="abc",
        )

        result = line._resolve_value(self.endpoint, b"", {}, {}, return_all=True)

        self.assertEqual(result, ["abc"])

    def test_return_all_with_blank_scalar_returns_empty_list(self):
        line = self.factory.endpoint_source(
            self.endpoint,
            field_name="blank",
            source_kind="header",
            header_name="X-Missing",
        )

        result = line._resolve_value(self.endpoint, b"", {}, {}, return_all=True)

        self.assertEqual(result, [])


class TestEndpointSourceTransforms(WebhookTestCase):
    """``_apply_transforms`` honors the configured normalization mode."""

    def test_strip_normalize_mode_removes_surrounding_whitespace(self):
        endpoint = self.factory.inbound_endpoint()
        line = self.factory.endpoint_source(
            endpoint,
            field_name="trimmed",
            source_kind="literal",
            literal_value="x",
            normalize_mode="strip",
        )

        self.assertEqual(line._apply_transforms("  hello  "), "hello")


class TestEndpointSourceWriteRevalidation(WebhookTestCase):
    """``write`` re-runs the configuration check and accepts unrelated updates."""

    def test_writing_unrelated_field_without_field_name_is_accepted(self):
        endpoint = self.factory.inbound_endpoint()
        line = self.factory.endpoint_source(
            endpoint,
            field_name="ok_field",
            source_kind="literal",
            literal_value="x",
        )

        line.write({"sequence": 99})

        self.assertEqual(line.sequence, 99)


class TestEndpointComputedSourceSuccess(WebhookTestCase):
    """A computed source delegates to the named method on the endpoint."""

    def test_computed_source_dispatches_and_returns_method_result(self):
        endpoint = self.factory.inbound_endpoint()
        line = self.factory.endpoint_source(
            endpoint,
            field_name="computed_value",
            source_kind="computed",
            computed_method="_test_compute_helper",
        )

        with patch.object(
            type(endpoint),
            "_test_compute_helper",
            create=True,
            return_value="computed-result",
        ) as helper:
            value = endpoint._compute_source_value(line, b"{}", {}, {})

        self.assertEqual(value, "computed-result")
        helper.assert_called_once()


class TestEndpointFieldCandidateResolution(WebhookTestCase):
    """``_extract_field_candidates`` aggregates candidates per ``field_name``."""

    def test_endpoint_without_sources_for_field_returns_empty_list(self):
        endpoint = self.factory.inbound_endpoint()

        self.assertEqual(endpoint._extract_field_candidates("nope", b"{}", {}, {}), [])

    def test_single_literal_source_returns_raw_literal_value(self):
        endpoint = self.factory.inbound_endpoint()
        self.factory.endpoint_source(
            endpoint,
            field_name="ref",
            source_kind="literal",
            literal_value="EXT-1",
        )

        self.assertEqual(
            endpoint._extract_field_candidates("ref", b"{}", {}, {}),
            ["EXT-1"],
        )

    def test_multiple_lines_in_same_candidate_concatenate_with_joiner(self):
        endpoint = self.factory.inbound_endpoint()
        self.factory.endpoint_source(
            endpoint,
            field_name="composite",
            source_kind="literal",
            literal_value="alpha",
            sequence=10,
            joiner="-",
        )
        self.factory.endpoint_source(
            endpoint,
            field_name="composite",
            source_kind="literal",
            literal_value="beta",
            sequence=20,
        )

        self.assertEqual(
            endpoint._extract_field_candidates("composite", b"{}", {}, {}),
            ["alpha-beta"],
        )

    def test_blank_optional_line_is_skipped_and_required_lines_drive_value(self):
        endpoint = self.factory.inbound_endpoint()
        self.factory.endpoint_source(
            endpoint,
            field_name="ref",
            source_kind="header",
            header_name="X-Missing",
            required=False,
            sequence=10,
        )
        self.factory.endpoint_source(
            endpoint,
            field_name="ref",
            source_kind="literal",
            literal_value="fallback",
            sequence=20,
        )

        self.assertEqual(
            endpoint._extract_field_candidates("ref", b"{}", {}, {}),
            ["fallback"],
        )

    def test_header_param_with_allow_multiple_returns_all_matches(self):
        endpoint = self.factory.inbound_endpoint()
        self.factory.endpoint_source(
            endpoint,
            field_name="signatures",
            source_kind="header_param",
            header_name="Stripe-Signature",
            header_param_name="v1",
        )
        headers = {"Stripe-Signature": 'v1="abc", v1=def'}

        self.assertEqual(
            endpoint._extract_field_candidates("signatures", b"{}", headers, {}, allow_multiple=True),
            ["abc", "def"],
        )

    def test_required_multi_value_source_with_no_matches_drops_candidate(self):
        endpoint = self.factory.inbound_endpoint()
        self.factory.endpoint_source(
            endpoint,
            field_name="signatures",
            source_kind="header_param",
            header_name="Stripe-Signature",
            header_param_name="v1",
            required=True,
        )

        self.assertEqual(
            endpoint._extract_field_candidates("signatures", b"{}", {}, {}, allow_multiple=True),
            [],
        )
