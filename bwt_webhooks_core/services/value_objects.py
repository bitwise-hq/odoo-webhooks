"""Typed value objects used by the inbound and outbound pipelines.

Keeping these as plain dataclasses (no Odoo imports) lets services and
unit tests construct them without spinning up a registry.
"""

import dataclasses
import json
from typing import Any, Optional

from odoo.tools import json_default

from .constants import (
    BLANK_VALUES,
    OUTCOME_CANCEL,
    OUTCOME_RETRY,
    OUTCOME_SEND,
    TERMINAL_OUTCOME_STATE,
    VALID_OUTBOUND_BODY_MODES,
)


# ---------------------------------------------------------------------------
# Inbound
# ---------------------------------------------------------------------------


@dataclasses.dataclass(frozen=True)
class InboundMetadata:
    """Resolved inbound webhook semantic values keyed by semantic name."""

    values: dict

    def get(self, semantic_name, default=False):
        return self.values.get(semantic_name, default)

    def as_dict(self) -> dict:
        return dict(self.values)


# ---------------------------------------------------------------------------
# Outbound
# ---------------------------------------------------------------------------


@dataclasses.dataclass
class OutboundRequest:
    """Typed snapshot of a single outbound HTTP request.

    Mutability is preserved on purpose so that handler rules can apply
    incremental mutations (header set, payload path set) on a
    per-record :class:`OutboundRequest` without re-creating it.
    """

    target_url: str
    http_method: str
    request_body_mode: str
    headers: dict
    payload: Any
    files: dict = dataclasses.field(default_factory=dict)

    @classmethod
    def from_dict(cls, data: dict, *, default_body_mode: str = "json") -> "OutboundRequest":
        body_mode = data.get("request_body_mode") or default_body_mode
        payload = data.get("payload")
        if payload is None or payload is False:
            payload = {}
        return cls(
            target_url=data.get("target_url") or "",
            http_method=str(data.get("http_method") or "post").lower(),
            request_body_mode=str(body_mode).strip().lower(),
            headers=dict(data.get("headers") or {}),
            payload=payload,
            files=dict(data.get("files") or {}),
        )

    def to_dict(self) -> dict:
        return {
            "target_url": self.target_url,
            "http_method": self.http_method,
            "request_body_mode": self.request_body_mode,
            "headers": dict(self.headers),
            "payload": self.payload,
            "files": dict(self.files),
        }

    def deep_copy(self) -> "OutboundRequest":
        return OutboundRequest(
            target_url=self.target_url,
            http_method=self.http_method,
            request_body_mode=self.request_body_mode,
            headers=dict(self.headers),
            payload=json.loads(json.dumps(self.payload, default=json_default)),
            files=dict(self.files),
        )

    def with_overrides(self, raw: dict) -> "OutboundRequest":
        """Return a copy with mutations from a handler-result dict applied.

        Recognised keys: ``target_url``, ``http_method``,
        ``request_body_mode`` (or legacy ``transport_mode``),
        ``headers`` (replaces), ``payload`` (replaces),
        ``files`` (replaces).
        """
        updated = self.deep_copy()
        if raw.get("target_url"):
            updated.target_url = raw["target_url"]
        if raw.get("http_method"):
            updated.http_method = str(raw["http_method"]).lower()
        if "headers" in raw and raw.get("headers") is not None:
            updated.headers = {str(k): str(v) for k, v in raw["headers"].items()}
        if "payload" in raw:
            updated.payload = json.loads(json.dumps(raw["payload"], default=json_default))
        body_mode = raw.get("request_body_mode") or raw.get("transport_mode")
        if body_mode not in BLANK_VALUES:
            updated.request_body_mode = str(body_mode).strip().lower()
        if "files" in raw:
            updated.files = dict(raw.get("files") or {})
        return updated

    def assert_valid(self, valid_body_modes=VALID_OUTBOUND_BODY_MODES):
        """Validate body-mode and files invariants.

        ``valid_body_modes`` defaults to the set defined in
        :mod:`webhooks.services.constants`; callers may pass a custom
        set to support extended body modes from sibling addons.
        """
        # Imported here to keep this module free of Odoo imports at the
        # top level; ``WebhookProcessingConfigurationError`` lives in
        # the addon's ``exceptions`` module which only depends on Odoo
        # for ``ValidationError``.
        from odoo.addons.bwt_webhooks_core.exceptions import (
            WebhookProcessingConfigurationError,
        )

        if self.request_body_mode not in valid_body_modes:
            raise WebhookProcessingConfigurationError(
                "Unsupported outbound request body mode %s. Supported modes: %s."
                % (
                    self.request_body_mode or "unknown",
                    ", ".join(sorted(valid_body_modes)),
                )
            )
        if not isinstance(self.files, dict):
            raise WebhookProcessingConfigurationError("Outbound multipart files must be provided as a dictionary.")

    @property
    def multipart_file_keys_label(self):
        if not self.files:
            return False
        return ", ".join(sorted(str(k) for k in self.files))


@dataclasses.dataclass
class HandlerOutcome:
    """Interpretation of an outbound handler's return value."""

    status: str
    request: OutboundRequest
    note: str = ""
    seconds: Optional[int] = None
    matched_rule_id: Any = False

    @classmethod
    def from_raw(cls, raw: Any, base_request: OutboundRequest) -> "HandlerOutcome":
        if raw is False:
            return cls(status=OUTCOME_CANCEL, request=base_request)
        if not isinstance(raw, dict):
            return cls(status=OUTCOME_SEND, request=base_request)
        request = base_request.with_overrides(raw)
        return cls(
            status=raw.get("status") or OUTCOME_SEND,
            request=request,
            note=raw.get("note") or raw.get("message") or "",
            seconds=raw.get("seconds"),
            matched_rule_id=raw.get("matched_rule_id") or False,
        )

    @property
    def terminal_state(self) -> Optional[str]:
        return TERMINAL_OUTCOME_STATE.get(self.status)

    @property
    def is_retry(self) -> bool:
        return self.status == OUTCOME_RETRY
