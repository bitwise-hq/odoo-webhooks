"""Unit tests for :mod:`bwt_webhooks_core.services.transport`.

Test suites in this module:

* :class:`TestFlattenFormData` — nested-mapping flattening used to build
  ``application/x-www-form-urlencoded`` payloads.
* :class:`TestNormalizeRequestFiles` — normalization of multipart file
  descriptors into the tuple form expected by ``requests``.
* :class:`TestBuildTransportKwargs` — dispatch from
  :class:`OutboundRequest` into ``requests`` keyword arguments.
"""

from .common import WebhookServiceTestCase
from odoo.addons.bwt_webhooks_core.exceptions import WebhookProcessingConfigurationError
from odoo.addons.bwt_webhooks_core.services.transport import (
    build_transport_kwargs,
    flatten_form_data,
    normalize_request_files,
)
from odoo.addons.bwt_webhooks_core.services.value_objects import OutboundRequest


def _request(**overrides):
    base = {
        "target_url": "https://example",
        "http_method": "post",
        "request_body_mode": "json",
        "headers": {},
        "payload": {"k": "v"},
        "files": {},
    }
    base.update(overrides)
    return OutboundRequest(**base)


class TestFlattenFormData(WebhookServiceTestCase):
    """``flatten_form_data`` flattens nested mappings into bracketed keys."""

    def test_flat_mapping(self):
        self.assertEqual(flatten_form_data({"a": 1, "b": "x"}), {"a": "1", "b": "x"})

    def test_nested_dict_uses_brackets(self):
        self.assertEqual(
            flatten_form_data({"a": {"b": {"c": 1}}}),
            {"a[b][c]": "1"},
        )

    def test_list_uses_index_brackets(self):
        self.assertEqual(
            flatten_form_data({"items": ["x", "y"]}),
            {"items[0]": "x", "items[1]": "y"},
        )

    def test_empty_collections_become_empty_string(self):
        self.assertEqual(flatten_form_data({"a": {}, "b": []}), {"a": "", "b": ""})

    def test_booleans_and_none(self):
        self.assertEqual(
            flatten_form_data({"a": True, "b": False, "c": None}),
            {"a": "true", "b": "false", "c": ""},
        )


class TestNormalizeRequestFiles(WebhookServiceTestCase):
    """``normalize_request_files`` coerces file specs into ``requests`` tuples."""

    def test_empty_returns_empty(self):
        self.assertEqual(normalize_request_files(None), {})
        self.assertEqual(normalize_request_files({}), {})

    def test_rejects_non_dict(self):
        with self.assertRaises(WebhookProcessingConfigurationError):
            normalize_request_files([("a", b"x")])

    def test_dict_form_with_content_type(self):
        result = normalize_request_files(
            {
                "file": {
                    "filename": "x.txt",
                    "content": b"hello",
                    "content_type": "text/plain",
                }
            }
        )
        self.assertEqual(result, {"file": ("x.txt", b"hello", "text/plain")})

    def test_dict_form_without_content_type(self):
        result = normalize_request_files({"file": {"filename": "x.txt", "content": b"hi"}})
        self.assertEqual(result, {"file": ("x.txt", b"hi")})

    def test_dict_form_requires_content(self):
        with self.assertRaises(WebhookProcessingConfigurationError):
            normalize_request_files({"file": {"filename": "x.txt"}})

    def test_tuple_passthrough(self):
        result = normalize_request_files({"file": ("x.txt", b"y")})
        self.assertEqual(result, {"file": ("x.txt", b"y")})

    def test_invalid_value_type(self):
        with self.assertRaises(WebhookProcessingConfigurationError):
            normalize_request_files({"file": "not-a-tuple"})


class TestBuildTransportKwargs(WebhookServiceTestCase):
    """``build_transport_kwargs`` projects an ``OutboundRequest`` to ``requests`` kwargs."""

    def test_json_mode(self):
        kwargs = build_transport_kwargs(_request(payload={"k": 1}))
        self.assertEqual(kwargs, {"json": {"k": 1}})

    def test_json_mode_rejects_files(self):
        request = _request(files={"a": ("a.txt", b"x")})
        with self.assertRaises(WebhookProcessingConfigurationError):
            build_transport_kwargs(request)

    def test_form_urlencoded_mode_flattens(self):
        request = _request(request_body_mode="form_urlencoded", payload={"a": [1, 2]})
        kwargs = build_transport_kwargs(request)
        self.assertEqual(kwargs, {"data": {"a[0]": "1", "a[1]": "2"}})

    def test_form_urlencoded_rejects_files(self):
        request = _request(
            request_body_mode="form_urlencoded",
            payload={"a": 1},
            files={"f": ("f.txt", b"")},
        )
        with self.assertRaises(WebhookProcessingConfigurationError):
            build_transport_kwargs(request)

    def test_form_modes_require_dict_payload(self):
        request = _request(request_body_mode="form_urlencoded", payload="not-a-dict")
        with self.assertRaises(WebhookProcessingConfigurationError):
            build_transport_kwargs(request)

    def test_multipart_mode(self):
        request = _request(
            request_body_mode="multipart",
            payload={"meta": "x"},
            files={"f": {"filename": "f.txt", "content": b"y"}},
        )
        kwargs = build_transport_kwargs(request)
        self.assertEqual(kwargs["data"], {"meta": "x"})
        self.assertEqual(kwargs["files"], {"f": ("f.txt", b"y")})
