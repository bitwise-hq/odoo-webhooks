"""Outbound webhook delivery model and processing pipeline.

The pipeline (per record) is::

    process_delivery
        -> _process_one
            -> _build_outbound_request                -> OutboundRequest
            -> handler.execute_outbound (if any)      -> raw return
                -> HandlerOutcome.from_raw            -> HandlerOutcome
                    terminal: write + return
                    retry:    raise RetryableJobError
                    send:     continue with possibly-mutated request
            -> _create_attempt
            -> _dispatch -> requests.request -> _record_response

Two value objects keep the data flow explicit:

* :class:`OutboundRequest` — the snapshot of an HTTP request to send.
* :class:`HandlerOutcome`  — the interpretation of a handler's return value.
"""

import json
import traceback
from typing import Any

import requests

from odoo import SUPERUSER_ID, api, fields, models, _
from odoo.addons.queue_job.exception import RetryableJobError
from odoo.exceptions import ValidationError

from odoo.addons.bwt_webhooks_core.exceptions import WebhookProcessingConfigurationError
from odoo.addons.bwt_webhooks_core.services.conditions import (
    UnsupportedOperator,
    decode_literal_value,
    evaluate_condition,
)
from odoo.addons.bwt_webhooks_core.services.constants import (
    OUTCOME_RETRY,
    OUTCOME_SEND,
)
from odoo.addons.bwt_webhooks_core.services.payload import (
    safe_load_json_dict,
    set_payload_path,
)
from odoo.addons.bwt_webhooks_core.services.serialization import (
    serialize_headers,
    serialize_payload,
)
from odoo.addons.bwt_webhooks_core.services.transport import build_transport_kwargs
from odoo.addons.bwt_webhooks_core.services.value_objects import (
    HandlerOutcome,
    OutboundRequest,
)

# ---------------------------------------------------------------------------
# Model
# ---------------------------------------------------------------------------


class WebhookOutboundDelivery(models.Model):
    _name = "bwt.webhook.outbound.delivery"
    _inherit = ["mail.thread", "mail.activity.mixin"]
    _description = "Outbound Webhook Delivery"
    _order = "create_date desc, id desc"
    _check_company_auto = True

    # ------------------------------------------------------------------
    # Fields
    # ------------------------------------------------------------------

    name = fields.Char(
        required=True,
        default=lambda self: _("Outbound Webhook Delivery"),
    )
    endpoint_id = fields.Many2one(
        "bwt.webhook.outbound.endpoint",
        required=True,
        ondelete="cascade",
        index=True,
        check_company=True,
    )
    handler_id = fields.Many2one(
        "bwt.webhook.handler",
        related="endpoint_id.handler_id",
        store=True,
        readonly=True,
        index=True,
        check_company=True,
    )
    company_id = fields.Many2one(
        "res.company",
        related="endpoint_id.company_id",
        store=True,
        readonly=True,
        index=True,
    )
    state = fields.Selection(
        selection=[
            ("draft", "Draft"),
            ("queued", "Queued"),
            ("processing", "Processing"),
            ("done", "Done"),
            ("error", "Error"),
            ("dead_letter", "Dead Letter"),
            ("canceled", "Canceled"),
        ],
        required=True,
        default="draft",
        index=True,
        tracking=True,
        help=("Lifecycle of the outbound delivery. Reset failed, dead-letter, or canceled deliveries to Draft before queueing them again. Use replay when the downstream system requires an audited resend."),
    )
    queued_at = fields.Datetime(index=True)
    processed_at = fields.Datetime(index=True)
    queue_to_done_seconds = fields.Float(
        string="Queue To Done (s)",
        compute="_compute_latency_seconds",
        store=True,
        readonly=True,
        help="Seconds between queueing and completion.",
    )
    end_to_end_seconds = fields.Float(
        string="End To End (s)",
        compute="_compute_latency_seconds",
        store=True,
        readonly=True,
        help="Seconds between delivery creation and completion.",
    )
    http_method = fields.Selection(related="endpoint_id.http_method", string="HTTP Method", readonly=True)
    target_url = fields.Char(related="endpoint_id.target_url", string="Target URL", readonly=True)
    timeout_seconds = fields.Integer(related="endpoint_id.timeout_seconds", readonly=True)
    request_body_mode = fields.Selection(
        related="endpoint_id.request_body_mode",
        store=True,
        readonly=True,
    )
    request_headers_json = fields.Text(
        required=True,
        default="{}",
        string="Request Headers",
        help=("Base outbound request headers snapshot. Endpoint Header Rules and outbound handler logic can still adjust the final request before sending."),
    )
    payload_json = fields.Text(
        required=True,
        default="{}",
        string="Payload JSON",
        help=("Base outbound JSON payload snapshot. Endpoint Payload Rules and outbound handler logic can still adjust the final request before sending."),
    )
    response_status_code = fields.Integer(index=True, string="Response Status", tracking=True)
    response_headers_json = fields.Text(string="Response Headers")
    response_body = fields.Text()
    processing_note = fields.Text()
    processing_error = fields.Text()
    matched_outbound_rule_id = fields.Many2one(
        "bwt.webhook.outbound.handler.rule",
        string="Matched Rule",
        ondelete="set null",
        index=True,
        tracking=True,
    )
    replayed_from_delivery_id = fields.Many2one(
        "bwt.webhook.outbound.delivery",
        string="Replay Of",
        ondelete="set null",
        index=True,
        check_company=True,
        tracking=True,
    )
    replay_delivery_ids = fields.One2many(
        "bwt.webhook.outbound.delivery",
        "replayed_from_delivery_id",
        string="Replay Deliveries",
        help="Audited replay deliveries created from this delivery.",
    )
    replay_count = fields.Integer(compute="_compute_replay_count", store=True)
    context_line_ids = fields.One2many(
        "bwt.webhook.outbound.delivery.context.line",
        "delivery_id",
        string="Context Lines",
        copy=True,
        help=("Additional named values available to outbound handler rules when mutating, retrying, canceling, or dead-lettering this delivery."),
    )
    attempt_ids = fields.One2many(
        "bwt.webhook.outbound.delivery.attempt",
        "delivery_id",
        string="Attempts",
        help=("HTTP attempt log for this delivery, including response details and processing errors."),
    )
    attempt_count = fields.Integer(compute="_compute_attempt_count", store=True)
    queue_job_identity_key = fields.Char(
        compute="_compute_queue_job_identity_key",
        help="Identity key used when enqueuing background delivery processing.",
    )
    queue_job_ids = fields.Many2many(
        "queue.job",
        compute="_compute_queue_job_observability",
        string="Queue Jobs",
        help="Background queue jobs created to process this outbound delivery.",
    )
    queue_job_count = fields.Integer(compute="_compute_queue_job_observability")
    latest_queue_job_id = fields.Many2one(
        "queue.job",
        compute="_compute_queue_job_observability",
        string="Latest Queue Job",
    )
    latest_queue_job_state = fields.Char(compute="_compute_queue_job_observability")

    # ------------------------------------------------------------------
    # Computed fields
    # ------------------------------------------------------------------

    @api.depends("attempt_ids")
    def _compute_attempt_count(self):
        for delivery in self:
            delivery.attempt_count = len(delivery.attempt_ids)

    @api.depends("replay_delivery_ids")
    def _compute_replay_count(self):
        for delivery in self:
            delivery.replay_count = len(delivery.replay_delivery_ids)

    def _compute_queue_job_identity_key(self):
        for delivery in self:
            delivery.queue_job_identity_key = delivery._get_queue_job_identity_key() if delivery.id else False

    @api.depends("create_date", "queued_at", "processed_at")
    def _compute_latency_seconds(self):
        for delivery in self:
            delivery.queue_to_done_seconds = 0.0
            delivery.end_to_end_seconds = 0.0
            if delivery.create_date and delivery.processed_at:
                created_dt = fields.Datetime.to_datetime(delivery.create_date)
                processed_dt = fields.Datetime.to_datetime(delivery.processed_at)
                delivery.end_to_end_seconds = max((processed_dt - created_dt).total_seconds(), 0.0)
            if delivery.queued_at and delivery.processed_at:
                queued_dt = fields.Datetime.to_datetime(delivery.queued_at)
                processed_dt = fields.Datetime.to_datetime(delivery.processed_at)
                delivery.queue_to_done_seconds = max((processed_dt - queued_dt).total_seconds(), 0.0)

    @api.depends("queue_job_identity_key")
    def _compute_queue_job_observability(self):
        job_model = self.env["queue.job"]
        identity_keys = [k for k in self.mapped("queue_job_identity_key") if k]
        jobs_by_key = {}
        if identity_keys:
            jobs = job_model.search(
                [
                    ("identity_key", "in", identity_keys),
                    ("model_name", "=", "bwt.webhook.outbound.delivery"),
                    ("method_name", "=", "process_delivery"),
                ],
                order="date_created desc, id desc",
            )
            for job in jobs:
                jobs_by_key.setdefault(job.identity_key, job_model.browse())
                jobs_by_key[job.identity_key] |= job
        for delivery in self:
            jobs = jobs_by_key.get(delivery.queue_job_identity_key, job_model.browse())
            delivery.queue_job_ids = jobs
            delivery.queue_job_count = len(jobs)
            delivery.latest_queue_job_id = jobs[:1]
            delivery.latest_queue_job_state = jobs[:1].state if jobs else False

    # ------------------------------------------------------------------
    # Identity / queue-job helpers
    # ------------------------------------------------------------------

    def _get_queue_job_identity_key(self):
        self.ensure_one()
        return f"webhook_outbound_delivery_process:{self.id}" if self.id else False

    def _get_queue_job_action_domain(self):
        self.ensure_one()
        if not self.queue_job_identity_key:
            return [("id", "=", 0)]
        return [
            ("identity_key", "=", self.queue_job_identity_key),
            ("model_name", "=", "bwt.webhook.outbound.delivery"),
            ("method_name", "=", "process_delivery"),
        ]

    def action_view_queue_jobs(self):
        self.ensure_one()
        action = self.env.ref("queue_job.action_queue_job").read()[0]
        action["name"] = _("Outbound Queue Jobs")
        action["domain"] = self._get_queue_job_action_domain()
        return action

    # ------------------------------------------------------------------
    # JSON snapshot normalization (create / write)
    # ------------------------------------------------------------------

    @api.model
    def _normalize_headers_json(self, value, *, label="Request Headers"):
        try:
            headers = json.loads(value or "{}")
        except json.JSONDecodeError as err:
            raise ValidationError(_("%(label)s must be valid JSON.", label=label)) from err
        if not isinstance(headers, dict):
            raise ValidationError(_("%(label)s must be a JSON object.", label=label))
        return serialize_headers(headers)

    @api.model
    def _normalize_payload_json(self, value, *, label="Payload JSON"):
        try:
            payload = json.loads(value or "{}")
        except json.JSONDecodeError as err:
            raise ValidationError(_("%(label)s must be valid JSON.", label=label)) from err
        return serialize_payload(payload)

    @api.model
    def _prepare_endpoint_snapshot_vals(self, endpoint, vals):
        prepared = dict(vals)
        prepared.setdefault("request_headers_json", "{}")
        prepared.setdefault("payload_json", "{}")
        prepared.setdefault("name", "%s / %s" % (endpoint.display_name, fields.Datetime.now()))
        return prepared

    @api.model_create_multi
    def create(self, vals_list):
        prepared_vals_list = []
        for vals in vals_list:
            prepared = dict(vals)
            endpoint = self.env["bwt.webhook.outbound.endpoint"].browse(prepared.get("endpoint_id"))
            prepared = self._prepare_endpoint_snapshot_vals(endpoint, prepared)
            prepared["request_headers_json"] = self._normalize_headers_json(prepared.get("request_headers_json"))
            prepared["payload_json"] = self._normalize_payload_json(prepared.get("payload_json"))
            prepared_vals_list.append(prepared)
        return super().create(prepared_vals_list)

    def write(self, vals):
        prepared = dict(vals)
        if "request_headers_json" in prepared:
            prepared["request_headers_json"] = self._normalize_headers_json(prepared["request_headers_json"])
        if "payload_json" in prepared:
            prepared["payload_json"] = self._normalize_payload_json(prepared["payload_json"])
        return super().write(prepared)

    # ------------------------------------------------------------------
    # Source-value resolution (rules / context lines / conditions)
    # ------------------------------------------------------------------

    def _decode_literal_value(self, value):
        return decode_literal_value(value)

    def _resolve_expression_value(self, source, expression):
        current = source
        for token in (expression or "").split("."):
            if token == "":
                continue
            if isinstance(current, dict):
                current = current.get(token)
            else:
                current = getattr(current, token)
            if not current:
                break
        if isinstance(current, models.BaseModel):
            return current.id if len(current) == 1 else current.ids
        return current

    def _resolve_source_value(
        self,
        source_kind,
        source_expression=False,
        literal_value=False,
        *,
        context_values=None,
        request_data=None,
    ):
        """Resolve a value by ``source_kind`` for rules / conditions / context lines.

        ``request_data`` may be either an :class:`OutboundRequest` or a plain
        dict (for backwards-compatible callers and condition evaluation).
        """
        self.ensure_one()
        if source_kind == "literal":
            return self._decode_literal_value(literal_value)

        if isinstance(request_data, OutboundRequest):
            request_view = request_data.to_dict()
        else:
            request_view = request_data or {}

        source_map = {
            "delivery_field": self,
            "endpoint_field": self.endpoint_id,
            "company_field": self.company_id,
            "context_key": context_values or {},
            "request_field": request_view,
        }
        source = source_map.get(source_kind)
        if source is None or not source_expression:
            return False
        try:
            return self._resolve_expression_value(source, source_expression)
        except AttributeError as err:
            raise WebhookProcessingConfigurationError(
                _(
                    "Could not resolve source expression %(expression)s.",
                    expression=source_expression,
                )
            ) from err

    def _get_context_values(self):
        self.ensure_one()
        values = {}
        for line in self.context_line_ids.filtered("active").sorted(key=lambda r: (r.sequence, r.id)):
            values[line.key_name] = self._resolve_source_value(
                line.source_kind,
                line.source_expression,
                line.literal_value,
                context_values=values,
            )
        return values

    @staticmethod
    def _set_payload_path(payload, target_path, value):
        return set_payload_path(payload, target_path, value)

    # ------------------------------------------------------------------
    # Building outbound requests
    # ------------------------------------------------------------------

    def _build_outbound_request(self) -> OutboundRequest:
        """Build the base :class:`OutboundRequest` for this delivery."""
        self.ensure_one()
        context_values = self._get_context_values()
        headers = self._safe_load_json_dict(self.request_headers_json)
        payload = self._safe_load_json_dict(self.payload_json)

        for rule in self.endpoint_id.header_rule_ids.filtered("active").sorted(key=lambda r: (r.sequence, r.id)):
            value = self._resolve_source_value(
                rule.source_kind,
                rule.source_expression,
                rule.literal_value,
                context_values=context_values,
            )
            headers[rule.header_name] = "" if value in (False, None) else str(value)
        for rule in self.endpoint_id.payload_rule_ids.filtered("active").sorted(key=lambda r: (r.sequence, r.id)):
            value = self._resolve_source_value(
                rule.source_kind,
                rule.source_expression,
                rule.literal_value,
                context_values=context_values,
            )
            payload = self._set_payload_path(payload, rule.target_path, value)

        rendered_target_url = self.endpoint_id._render_outbound_target_url(context_values, delivery=self)
        request = OutboundRequest(
            target_url=rendered_target_url,
            http_method=(self.http_method or "post").lower(),
            request_body_mode=str(self.request_body_mode or "json").strip().lower(),
            headers=headers,
            payload=payload,
            files={},
        )
        request.assert_valid()
        return request

    @staticmethod
    def _safe_load_json_dict(value):
        return safe_load_json_dict(value)

    # ------------------------------------------------------------------
    # Request data accessors
    # ------------------------------------------------------------------

    def _get_request_headers(self):
        self.ensure_one()
        try:
            return json.loads(self.request_headers_json or "{}")
        except json.JSONDecodeError as err:
            raise WebhookProcessingConfigurationError(_("Request Headers must be valid JSON.")) from err

    def _get_payload(self):
        self.ensure_one()
        try:
            return json.loads(self.payload_json or "{}")
        except json.JSONDecodeError as err:
            raise WebhookProcessingConfigurationError(_("Payload JSON must be valid JSON.")) from err

    def _apply_handler_result(self, raw, request_data):
        """Return ``(raw, updated_request_dict)``."""
        base = self._coerce_outbound_request(request_data)
        outcome = HandlerOutcome.from_raw(raw, base)
        outcome.request.assert_valid()
        return raw, outcome.request.to_dict()

    # ------------------------------------------------------------------
    # Transport request construction
    # ------------------------------------------------------------------

    def _build_transport_kwargs(self, request: OutboundRequest) -> dict:
        return build_transport_kwargs(request)

    # ------------------------------------------------------------------
    # Handler interpretation
    # ------------------------------------------------------------------

    def _resolve_handler_outcome(self, raw: Any, base_request: OutboundRequest) -> HandlerOutcome:
        """Wrap a raw handler return value into a :class:`HandlerOutcome`."""
        outcome = HandlerOutcome.from_raw(raw, base_request)
        outcome.request.assert_valid()
        return outcome

    def _execute_model_driven_handler(self, handler, request_data=None) -> dict:
        """Evaluate the handler's outbound rules and return a raw result dict.

        ``request_data`` may be a dict or an :class:`OutboundRequest`. The
        return value follows the same shape as user-written Python callbacks
        so that :meth:`HandlerOutcome.from_raw` can interpret either source
        uniformly.
        """
        self.ensure_one()
        request = self._coerce_outbound_request(request_data)
        request.assert_valid()

        context_values = self._get_context_values()
        rules = handler.outbound_rule_ids.filtered("active").sorted(key=lambda r: (r.sequence, r.id))
        matched_rule = next(
            (rule for rule in rules if all(self._outbound_condition_matches(condition, context_values, request) for condition in rule.condition_ids.sorted(key=lambda c: (c.sequence, c.id)))),
            False,
        )
        if not matched_rule:
            return {"status": OUTCOME_SEND}

        mutated = request.deep_copy()
        for assignment in matched_rule.assignment_ids.sorted(key=lambda a: (a.sequence, a.id)):
            value = self._resolve_source_value(
                assignment.source_kind,
                assignment.source_expression,
                assignment.literal_value,
                context_values=context_values,
                request_data=mutated,
            )
            self._apply_assignment(mutated, assignment, value)
        mutated.assert_valid()

        result = {
            "status": matched_rule.result_status,
            "note": matched_rule.note or False,
            "matched_rule_id": matched_rule.id,
        }
        for key in (
            "target_url",
            "http_method",
            "request_body_mode",
            "headers",
            "payload",
            "files",
        ):
            mutated_value = getattr(mutated, key)
            if mutated_value != getattr(request, key):
                result[key] = mutated_value
        if matched_rule.result_status == OUTCOME_RETRY and matched_rule.retry_seconds:
            result["seconds"] = matched_rule.retry_seconds
        return result

    def _coerce_outbound_request(self, request_data) -> OutboundRequest:
        """Return an :class:`OutboundRequest` from an object or mapping."""
        if isinstance(request_data, OutboundRequest):
            return request_data
        return OutboundRequest.from_dict(request_data or {}, default_body_mode=self.request_body_mode or "json")

    @staticmethod
    def _apply_assignment(request: OutboundRequest, assignment, value):
        if assignment.target_scope == "request":
            setattr(request, assignment.target_expression, value)
        elif assignment.target_scope == "header":
            request.headers[assignment.target_expression] = "" if value in (False, None) else str(value)
        else:  # payload
            request.payload = WebhookOutboundDelivery._set_payload_path(request.payload, assignment.target_expression, value)

    def _outbound_condition_matches(self, condition, context_values, request_data):
        actual_value = self._resolve_source_value(
            condition.source_kind,
            condition.source_expression,
            context_values=context_values,
            request_data=request_data,
        )
        try:
            return evaluate_condition(actual_value, condition.operator, condition.expected_value)
        except UnsupportedOperator as exc:
            raise WebhookProcessingConfigurationError(
                _(
                    "Unsupported outbound condition operator %(operator)s.",
                    operator=exc.operator,
                )
            ) from exc

    # ------------------------------------------------------------------
    # Attempt logging
    # ------------------------------------------------------------------

    def _next_attempt_number(self):
        self.ensure_one()
        return self.env["bwt.webhook.outbound.delivery.attempt"].search_count([("delivery_id", "=", self.id)]) + 1

    def _create_attempt(
        self,
        request,
        *,
        state: str = "processing",
        note: Any = False,
        error: Any = False,
        response_status_code: Any = False,
        response_headers: Any = None,
        response_body: Any = False,
    ):
        self.ensure_one()
        if isinstance(request, dict):
            request = OutboundRequest.from_dict(request, default_body_mode=self.request_body_mode or "json")
        request.assert_valid()
        attempt_number = self._next_attempt_number()
        values = {
            "name": f"{self.display_name} / Attempt {attempt_number}",
            "delivery_id": self.id,
            "attempt_number": attempt_number,
            "state": state,
            "http_method": request.http_method,
            "request_body_mode": request.request_body_mode,
            "multipart_file_keys": request.multipart_file_keys_label,
            "target_url": request.target_url,
            "request_headers_json": serialize_headers(request.headers),
            "payload_json": serialize_payload(request.payload),
            "processing_note": note or False,
            "processing_error": error or False,
            "response_status_code": response_status_code or False,
            "response_headers_json": (serialize_headers(response_headers) if response_headers else False),
            "response_body": response_body or False,
        }
        if state != "processing":
            values["finished_at"] = fields.Datetime.now()
        return self.env["bwt.webhook.outbound.delivery.attempt"].create(values)

    @staticmethod
    def _response_audit_vals(response, *, state, note, error_message):
        return {
            "state": state,
            "finished_at": fields.Datetime.now(),
            "processing_note": note or False,
            "processing_error": error_message or False,
            "response_status_code": response.status_code,
            "response_headers_json": serialize_headers(dict(response.headers.items())),
            "response_body": response.text,
        }

    # ------------------------------------------------------------------
    # Lifecycle actions
    # ------------------------------------------------------------------

    def _queue_processing(self):
        for delivery in self:
            endpoint_state = delivery.endpoint_id.state
            if endpoint_state == "draft":
                raise ValidationError(
                    _(
                        "Draft outbound endpoint %(endpoint)s cannot queue new deliveries.",
                        endpoint=delivery.endpoint_id.display_name,
                    )
                )
            if endpoint_state == "archived":
                raise ValidationError(
                    _(
                        "Archived outbound endpoint %(endpoint)s cannot queue new deliveries.",
                        endpoint=delivery.endpoint_id.display_name,
                    )
                )
            if delivery.state not in ("draft", "error"):
                raise ValidationError(_("Only draft or failed deliveries can be queued."))
        for delivery in self:
            delivery.write(
                {
                    "state": "queued",
                    "queued_at": fields.Datetime.now(),
                    "processing_error": False,
                }
            )
            delivery.with_user(SUPERUSER_ID).with_delay(identity_key=delivery._get_queue_job_identity_key()).process_delivery()

    def action_queue_delivery(self):
        self._queue_processing()
        return True

    def action_reset_to_draft(self):
        for delivery in self:
            if delivery.state not in ("error", "dead_letter", "canceled"):
                raise ValidationError(_("Only failed, dead-letter, or canceled deliveries can be reset to draft."))
            delivery.write(
                {
                    "state": "draft",
                    "queued_at": False,
                    "processed_at": False,
                    "processing_note": False,
                    "processing_error": False,
                    "response_status_code": False,
                    "response_headers_json": False,
                    "response_body": False,
                }
            )
        return True

    def action_cancel_delivery(self):
        for delivery in self:
            if delivery.state not in ("draft", "error"):
                raise ValidationError(_("Only draft or failed deliveries can be canceled."))
            delivery.write({"state": "canceled"})
        return True

    def _get_next_replay_number(self):
        self.ensure_one()
        return self.env["bwt.webhook.outbound.delivery"].search_count([("replayed_from_delivery_id", "=", self.id)]) + 1

    def action_create_replay_delivery(self):
        self.ensure_one()
        if self.state in ("queued", "processing"):
            raise ValidationError(_("Queued or processing deliveries cannot be replayed."))
        replay = self.copy(
            {
                "name": f"{self.display_name} / Replay {self._get_next_replay_number()}",
                "state": "draft",
                "queued_at": False,
                "processed_at": False,
                "processing_note": False,
                "processing_error": False,
                "response_status_code": False,
                "response_headers_json": False,
                "response_body": False,
                "replayed_from_delivery_id": self.id,
            }
        )
        action = self.env.ref("bwt_webhooks_outbound.action_webhook_outbound_delivery").read()[0]
        action["res_id"] = replay.id
        action["view_mode"] = "form"
        action["views"] = [
            (
                self.env.ref("bwt_webhooks_outbound.view_webhook_outbound_delivery_form").id,
                "form",
            )
        ]
        return action

    # ------------------------------------------------------------------
    # Processing pipeline
    # ------------------------------------------------------------------

    def process_delivery(self):
        for delivery in self:
            if delivery.state in ("done", "dead_letter", "canceled"):
                continue
            delivery._process_one()

    def _process_one(self):
        """Process a single delivery: build, run handler, dispatch, record."""
        self.ensure_one()
        request = None
        attempt = None
        outcome = HandlerOutcome(status=OUTCOME_SEND, request=None)  # placeholder
        try:
            request = self._build_outbound_request()
            outcome = self._invoke_handler(request)
            request = outcome.request

            if outcome.terminal_state:
                self._finalize_terminal(request, outcome)
                return

            if outcome.is_retry:
                self._finalize_retry(request, outcome)  # raises RetryableJobError

            self.write(
                {
                    "request_headers_json": serialize_headers(request.headers),
                    "payload_json": serialize_payload(request.payload),
                    "matched_outbound_rule_id": outcome.matched_rule_id or False,
                }
            )
            transport_kwargs = self._build_transport_kwargs(request)
            attempt = self._create_attempt(request)
        except RetryableJobError:
            raise
        except Exception:
            self._record_pre_dispatch_failure(request, outcome.note, traceback.format_exc())
            raise

        self._dispatch(request, transport_kwargs, attempt, outcome)

    def _invoke_handler(self, request: OutboundRequest) -> HandlerOutcome:
        if not self.handler_id:
            return HandlerOutcome(status=OUTCOME_SEND, request=request)
        raw = self.handler_id.execute_outbound(self, request_data=request)
        return self._resolve_handler_outcome(raw, request)

    def _finalize_terminal(self, request: OutboundRequest, outcome: HandlerOutcome):
        """Record an attempt and finalize the delivery for handler-driven terminals."""
        state = outcome.terminal_state
        self._create_attempt(request, state=state, note=outcome.note or False)
        self.write(
            {
                "state": state,
                "processed_at": fields.Datetime.now(),
                "processing_note": outcome.note or False,
                "processing_error": False,
            }
        )

    def _finalize_retry(self, request: OutboundRequest, outcome: HandlerOutcome):
        """Record an error attempt and raise :class:`RetryableJobError`."""
        message = outcome.note or _("Retry requested by outbound handler.")
        self._create_attempt(request, state="error", note=outcome.note or False, error=message)
        self.write(
            {
                "state": "error",
                "processing_note": outcome.note or False,
                "processing_error": message,
            }
        )
        raise RetryableJobError(message, seconds=outcome.seconds)

    def _record_pre_dispatch_failure(self, request, note, processing_error):
        self.write(
            {
                "state": "error",
                "processing_note": note or False,
                "processing_error": processing_error,
            }
        )
        if request is None:
            return
        try:
            self._create_attempt(
                request,
                state="error",
                note=note or False,
                error=processing_error,
            )
        except Exception:
            self.write(
                {
                    "processing_error": ("%s\n\nFailed to record outbound attempt:\n%s" % (processing_error, traceback.format_exc())),
                }
            )

    def _dispatch(
        self,
        request: OutboundRequest,
        transport_kwargs: dict,
        attempt,
        outcome: HandlerOutcome,
    ):
        self.write({"state": "processing", "processing_error": False})
        try:
            response = requests.request(
                request.http_method.upper(),
                request.target_url,
                headers=request.headers,
                timeout=self.timeout_seconds,
                **transport_kwargs,
            )
        except requests.RequestException as err:
            message = str(err)
            attempt.write(
                {
                    "state": "error",
                    "finished_at": fields.Datetime.now(),
                    "processing_note": outcome.note or False,
                    "processing_error": message,
                }
            )
            self.write(
                {
                    "state": "error",
                    "processing_note": outcome.note or False,
                    "processing_error": message,
                }
            )
            raise RetryableJobError(message) from err

        self._record_response(attempt, response, outcome)

    @staticmethod
    def _classify_response_status(status_code: int) -> str:
        if 200 <= status_code < 400:
            return "done"
        if 400 <= status_code < 500:
            return "dead_letter"
        return "error"

    def _record_response(self, attempt, response, outcome: HandlerOutcome):
        state = self._classify_response_status(response.status_code)
        error_message = (
            False
            if state == "done"
            else _(
                "Remote endpoint returned HTTP %(status)s.",
                status=response.status_code,
            )
        )
        audit = self._response_audit_vals(response, state=state, note=outcome.note, error_message=error_message)
        attempt.write(audit)
        self.write(
            {
                "state": state,
                "processed_at": audit["finished_at"],
                "processing_note": outcome.note or False,
                "processing_error": error_message or False,
                "response_status_code": response.status_code,
                "response_headers_json": audit["response_headers_json"],
                "response_body": response.text,
                "matched_outbound_rule_id": outcome.matched_rule_id or False,
            }
        )
        self._handle_outbound_response(response, state, outcome)
        if state == "error":
            raise RetryableJobError(error_message)

    def _handle_outbound_response(self, response, state, outcome: HandlerOutcome):
        """Hook called after the HTTP response is recorded.

        Override to react to a completed delivery (e.g. parse
        ``response_body`` and write external IDs back onto a related
        record).

        :param response: the :class:`requests.Response` object.
        :param state: ``'done'``, ``'dead_letter'`` or ``'error'`` —
            already written on ``self`` before this hook fires.
        :param outcome: the :class:`HandlerOutcome` produced by the
            handler that prepared the request.

        Default implementation is a no-op so downstream addons can opt
        in by overriding without calling super.
        """
        return
