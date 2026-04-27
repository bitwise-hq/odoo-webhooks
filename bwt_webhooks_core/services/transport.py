"""Pure outbound HTTP transport helpers.

The :class:`bwt.webhook.outbound.delivery` model owns scheduling, queue-job
plumbing, and request logging. The actual translation of an
:class:`~webhooks.services.value_objects.OutboundRequest` into the
keyword arguments accepted by :func:`requests.request` lives here, so
it can be unit-tested without an ORM.
"""

from typing import Any

from odoo.addons.bwt_webhooks_core.exceptions import WebhookProcessingConfigurationError


def flatten_form_data(values: Any) -> dict:
    """Flatten a nested mapping into ``application/x-www-form-urlencoded`` keys.

    Nested dicts use ``key[child]`` notation, lists use ``key[index]``.
    Booleans become ``"true"``/``"false"`` and ``None`` becomes ``""``.
    """
    flat: dict = {}
    for key, value in (values or {}).items():
        _flatten_form_value(flat, str(key), value)
    return flat


def _flatten_form_value(target: dict, key: str, value: Any) -> None:
    if isinstance(value, dict):
        if not value:
            target[key] = ""
            return
        for nested_key, nested_value in value.items():
            _flatten_form_value(target, f"{key}[{nested_key}]", nested_value)
        return
    if isinstance(value, (list, tuple)):
        if not value:
            target[key] = ""
            return
        for index, nested_value in enumerate(value):
            _flatten_form_value(target, f"{key}[{index}]", nested_value)
        return
    if value is True:
        target[key] = "true"
    elif value is False:
        target[key] = "false"
    elif value is None:
        target[key] = ""
    else:
        target[key] = str(value)


def normalize_request_files(files: Any) -> dict:
    """Coerce a ``files`` mapping into the tuples ``requests`` expects.

    Accepts either ``{name: (filename, content[, content_type])}`` or
    ``{name: {"filename": ..., "content": ..., "content_type": ...}}``.
    """
    if not files:
        return {}
    if not isinstance(files, dict):
        raise WebhookProcessingConfigurationError("Outbound multipart files must be provided as a dictionary.")
    normalized: dict = {}
    for field_name, value in files.items():
        key = str(field_name)
        if isinstance(value, dict):
            if "content" not in value:
                raise WebhookProcessingConfigurationError("Multipart file mapping %s requires a content entry." % key)
            filename = value.get("filename") or key
            content = value["content"]
            content_type = value.get("content_type")
            normalized[key] = (filename, content, content_type) if content_type else (filename, content)
        elif isinstance(value, (list, tuple)) and 2 <= len(value) <= 4:
            normalized[key] = tuple(value)
        else:
            raise WebhookProcessingConfigurationError("Multipart file mapping %s must be a tuple/list accepted by requests or a dict with filename/content." % key)
    return normalized


def build_transport_kwargs(request) -> dict:
    """Translate an :class:`OutboundRequest` to ``requests.request`` kwargs.

    The ``request`` argument is validated via
    :meth:`OutboundRequest.assert_valid`; callers should already have
    invoked it but the redundant check is cheap and keeps the helper
    safe to use standalone.
    """
    request.assert_valid()
    if request.request_body_mode == "json":
        if request.files:
            raise WebhookProcessingConfigurationError("JSON request body mode cannot include multipart files.")
        return {"json": request.payload}

    if not isinstance(request.payload, dict):
        raise WebhookProcessingConfigurationError("Request body mode %s requires a JSON object payload." % request.request_body_mode)

    if request.request_body_mode == "form_urlencoded":
        if request.files:
            raise WebhookProcessingConfigurationError("Form URL Encoded request body mode cannot include multipart files.")
        return {"data": flatten_form_data(request.payload)}

    # multipart
    return {
        "data": flatten_form_data(request.payload),
        "files": normalize_request_files(request.files),
    }
