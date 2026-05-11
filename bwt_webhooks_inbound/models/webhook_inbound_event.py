import hashlib
import json
import logging
import traceback

from psycopg2 import IntegrityError

from odoo import SUPERUSER_ID, api, fields, models
from odoo.addons.queue_job.exception import RetryableJobError
from odoo.exceptions import ValidationError

from odoo.addons.bwt_webhooks_core.exceptions import (
    WebhookPayloadValidationError,
    WebhookValidationError,
)
from odoo.addons.bwt_webhooks_core.services.conditions import (
    UnsupportedOperator,
    decode_literal_value,
    evaluate_condition,
)

_logger = logging.getLogger(__name__)


class WebhookInboundEvent(models.Model):
    _name = "bwt.webhook.inbound.event"
    _inherit = ["mail.thread", "mail.activity.mixin"]
    _description = "Inbound Webhook Event"
    _order = "received_at desc, id desc"
    _check_company_auto = True

    _sql_constraints = [
        (
            "endpoint_dedupe_uniq",
            "unique(endpoint_id, delivery_identity_key)",
            "The webhook delivery has already been stored for this endpoint.",
        ),
    ]

    name = fields.Char(
        required=True,
        default=lambda self: self.env._("Inbound Webhook Event"),
    )
    endpoint_id = fields.Many2one(
        "bwt.webhook.inbound.endpoint",
        required=True,
        ondelete="cascade",
        index=True,
        check_company=True,
    )
    handler_id = fields.Many2one(
        "bwt.webhook.handler",
        ondelete="set null",
        index=True,
        check_company=True,
        tracking=True,
    )
    company_id = fields.Many2one("res.company", required=True, index=True)
    received_at = fields.Datetime(required=True, default=fields.Datetime.now, index=True)
    processed_at = fields.Datetime(index=True)
    processing_seconds = fields.Float(
        string="Processing Time (s)",
        compute="_compute_processing_seconds",
        store=True,
        readonly=True,
        aggregator="avg",
        help="Seconds between reception and processing completion.",
    )
    state = fields.Selection(
        selection=[
            ("received", "Received"),
            ("processing", "Processing"),
            ("done", "Done"),
            ("error", "Error"),
            ("dead_letter", "Dead Letter"),
            ("rejected", "Rejected"),
        ],
        required=True,
        default="received",
        index=True,
        tracking=True,
        help="Lifecycle of the inbound event. Reset failed or dead-letter events back to Received before queueing them again. Rejected events stay blocked until the endpoint configuration is corrected.",
    )
    topic = fields.Char(index=True)
    event_type = fields.Char(index=True)
    event_id = fields.Char(index=True)
    delivery_id = fields.Char(index=True)
    notification_id = fields.Char(index=True)
    idempotency_key = fields.Char(
        index=True,
        help="Resolved explicit idempotency key semantic, when configured by the endpoint.",
    )
    delivery_identity_key = fields.Char(
        index=True,
        help="Internal exact-delivery identity key used for duplicate detection.",
    )
    delivery_identity_source = fields.Selection(
        selection=[
            ("delivery_id", "Delivery Identity"),
            ("idempotency_key", "Explicit Idempotency Key"),
            ("body_sha256", "Raw Body SHA256"),
        ],
        index=True,
        help="Which semantic actually supplied the exact-delivery identity for this record.",
    )
    replay_identity_key = fields.Char(
        index=True,
        help="Business-event identity used to link distinct deliveries of the same event.",
    )
    replay_identity_source = fields.Selection(
        selection=[
            ("event_id", "Business Event Identity"),
            ("idempotency_key", "Explicit Idempotency Key"),
        ],
        index=True,
        help="Which semantic supplied the replay identity for this record, when replay linking is enabled.",
    )
    delivery_kind = fields.Selection(
        selection=[
            ("primary", "Primary Delivery"),
            ("replay", "Replay Delivery"),
        ],
        required=True,
        default="primary",
        index=True,
        help="Whether this record is the first stored delivery for its replay identity or a later replay/redelivery.",
    )
    replayed_from_event_id = fields.Many2one(
        "bwt.webhook.inbound.event",
        string="Replay Of",
        ondelete="set null",
        index=True,
        check_company=True,
        tracking=True,
    )
    signature = fields.Char()
    signature_timestamp_raw = fields.Char(string="Signature Timestamp")
    occurred_at_raw = fields.Char(string="Occurred At")
    tenant_key = fields.Char(index=True)
    version = fields.Char()
    resource_reference = fields.Char(index=True)
    handler_selector = fields.Char()
    resolved_values_json = fields.Text(
        required=True,
        default="{}",
        help="Serialized snapshot of all resolved built-in and custom values extracted during intake.",
    )
    body_sha256 = fields.Char(required=True, index=True)
    request_body = fields.Text(required=True)
    request_headers_json = fields.Text(required=True)
    payload_json = fields.Text(required=True)
    processing_note = fields.Text()
    processing_error = fields.Text()
    matched_inbound_rule_id = fields.Many2one(
        "bwt.webhook.inbound.handler.rule",
        string="Matched Rule",
        ondelete="set null",
        index=True,
        tracking=True,
    )
    rule_execution_ids = fields.One2many(
        "bwt.webhook.inbound.rule.execution",
        "event_id",
        string="Rule Executions",
        help="Per-rule execution log captured when a model-driven inbound handler processes this event.",
    )
    rejection_category = fields.Char(index=True)
    rejection_reason = fields.Text()
    queue_job_identity_key = fields.Char(
        compute="_compute_queue_job_identity_key",
        help="Identity key used when enqueuing background processing for this event.",
    )
    queue_job_ids = fields.Many2many(
        "queue.job",
        compute="_compute_queue_job_observability",
        string="Queue Jobs",
        help="Background queue jobs created to process this inbound event.",
    )
    queue_job_count = fields.Integer(compute="_compute_queue_job_count", store=True, compute_sudo=False)
    latest_queue_job_id = fields.Many2one(
        "queue.job",
        compute="_compute_queue_job_observability",
        string="Latest Queue Job",
    )
    latest_queue_job_state = fields.Char(compute="_compute_queue_job_observability")

    def _compute_queue_job_identity_key(self):
        for event in self:
            event.queue_job_identity_key = event._get_queue_job_identity_key() if event.id else False

    @api.depends("received_at", "processed_at")
    def _compute_processing_seconds(self):
        for event in self:
            if event.received_at and event.processed_at:
                received_dt = fields.Datetime.to_datetime(event.received_at)
                processed_dt = fields.Datetime.to_datetime(event.processed_at)
                event.processing_seconds = max((processed_dt - received_dt).total_seconds(), 0.0)
            else:
                event.processing_seconds = 0.0

    @api.depends("queue_job_identity_key")
    def _compute_queue_job_observability(self):
        job_model = self.env["queue.job"]
        jobs_by_key = {}
        identity_keys = [key for key in self.mapped("queue_job_identity_key") if key]
        if identity_keys:
            jobs = job_model.search(
                [
                    ("identity_key", "in", identity_keys),
                    ("model_name", "=", "bwt.webhook.inbound.event"),
                    ("method_name", "=", "process_event"),
                ],
                order="date_created desc, id desc",
            )
            for job in jobs:
                jobs_by_key.setdefault(job.identity_key, job_model.browse())
                jobs_by_key[job.identity_key] |= job
        for event in self:
            jobs = jobs_by_key.get(event.queue_job_identity_key, job_model.browse())
            event.queue_job_ids = jobs
            event.latest_queue_job_id = jobs[:1]
            event.latest_queue_job_state = jobs[:1].state if jobs else False

    @api.depends("queue_job_identity_key")
    def _compute_queue_job_count(self):
        job_model = self.env["queue.job"]
        identity_keys = [key for key in self.mapped("queue_job_identity_key") if key]
        counts = {}
        if identity_keys:
            jobs = job_model.search(
                [
                    ("identity_key", "in", identity_keys),
                    ("model_name", "=", "bwt.webhook.inbound.event"),
                    ("method_name", "=", "process_event"),
                ]
            )
            for job in jobs:
                counts[job.identity_key] = counts.get(job.identity_key, 0) + 1
        for event in self:
            event.queue_job_count = counts.get(event.queue_job_identity_key, 0)

    def _get_queue_job_identity_key(self):
        self.ensure_one()
        return f"webhook_inbound_event_process:{self.id}" if self.id else False

    def _get_queue_job_action_domain(self):
        self.ensure_one()
        if not self.queue_job_identity_key:
            return [("id", "=", 0)]
        return [
            ("identity_key", "=", self.queue_job_identity_key),
            ("model_name", "=", "bwt.webhook.inbound.event"),
            ("method_name", "=", "process_event"),
        ]

    def action_view_queue_jobs(self):
        self.ensure_one()
        action = self.env.ref("queue_job.action_queue_job").read()[0]
        action["name"] = self.env._("Inbound Queue Jobs")
        action["domain"] = self._get_queue_job_action_domain()
        return action

    @api.model
    def _parse_payload(self, body_text, *, raise_on_invalid=False):
        if not body_text:
            return {}
        try:
            return json.loads(body_text)
        except json.JSONDecodeError as err:
            if raise_on_invalid:
                raise WebhookPayloadValidationError(self.env._("The webhook payload must be valid JSON.")) from err
            return False

    @api.model
    def _serialize_headers(self, headers):
        return json.dumps(dict(headers.items()), indent=2, sort_keys=True)

    @api.model
    def _serialize_payload(self, payload):
        return json.dumps(payload, indent=2, sort_keys=True)

    @api.model
    def _serialize_resolved_values(self, metadata):
        return json.dumps(metadata or {}, indent=2, sort_keys=True)

    def get_resolved_values(self):
        self.ensure_one()
        if not self.resolved_values_json:
            return {}
        try:
            return json.loads(self.resolved_values_json)
        except json.JSONDecodeError:
            return {}

    def get_resolved_value(self, field_key, default=False):
        self.ensure_one()
        return self.get_resolved_values().get(field_key, default)

    @api.model
    def _prepare_create_values_from_request(
        self,
        endpoint,
        handler,
        body,
        headers,
        payload,
        resolved_values,
        metadata,
        *,
        delivery_identity_key,
        delivery_identity_source,
        replay_identity_key,
        replay_identity_source,
        delivery_kind,
        replayed_from_event,
    ):
        body_text = body.decode("utf-8", errors="replace")
        body_sha256 = hashlib.sha256(body).hexdigest()
        return {
            "name": metadata.get("event_type") or metadata.get("topic") or endpoint.display_name or self.env._("Inbound Webhook Event"),
            "endpoint_id": endpoint.id,
            "handler_id": handler.id if handler else False,
            "company_id": endpoint.company_id.id,
            "topic": metadata.get("topic"),
            "event_type": metadata.get("event_type"),
            "event_id": metadata.get("event_id"),
            "delivery_id": metadata.get("delivery_id"),
            "notification_id": metadata.get("notification_id"),
            "idempotency_key": metadata.get("idempotency_key"),
            "delivery_identity_key": delivery_identity_key,
            "delivery_identity_source": delivery_identity_source,
            "replay_identity_key": replay_identity_key,
            "replay_identity_source": replay_identity_source,
            "delivery_kind": delivery_kind,
            "replayed_from_event_id": replayed_from_event.id if replayed_from_event else False,
            "signature": metadata.get("signature"),
            "signature_timestamp_raw": metadata.get("signature_timestamp"),
            "occurred_at_raw": metadata.get("occurred_at"),
            "tenant_key": metadata.get("tenant_key"),
            "version": metadata.get("version"),
            "resource_reference": metadata.get("resource_reference"),
            "handler_selector": metadata.get("handler_selector"),
            "resolved_values_json": self._serialize_resolved_values(resolved_values),
            "body_sha256": body_sha256,
            "request_body": body_text,
            "request_headers_json": self._serialize_headers(headers),
            "payload_json": self._serialize_payload(payload),
            "state": "received",
        }

    @api.model
    def _log_rejected_request(
        self,
        endpoint,
        body,
        headers,
        *,
        payload=None,
        payload_parse_failed=False,
        rejection_category="validation",
        rejection_reason=None,
    ):
        body_text = body.decode("utf-8", errors="replace")
        body_sha256 = hashlib.sha256(body).hexdigest()
        if payload_parse_failed:
            stored_payload = {}
            payload_context = {}
        else:
            payload = payload if payload is not None else self._parse_payload(body_text)
            stored_payload = payload if payload is not None else {}
            payload_context = payload if payload is not None else {}
        resolved_values = endpoint._extract_resolved_values(body, headers, payload_context) if endpoint else {}
        metadata = endpoint._extract_inbound_metadata(body, headers, payload_context, resolved_values=resolved_values) if endpoint else {}
        delivery_identity_key = False
        delivery_identity_source = False
        replay_identity_key = False
        replay_identity_source = False
        if endpoint:
            try:
                delivery_identity_key, delivery_identity_source = endpoint._resolve_delivery_identity(body_sha256, metadata)
            except ValidationError:
                delivery_identity_key = False
                delivery_identity_source = False
            try:
                replay_identity_key, replay_identity_source = endpoint._resolve_replay_identity(metadata)
            except ValidationError:
                replay_identity_key = False
                replay_identity_source = False
        values = {
            "name": self.env._("Rejected Webhook Request"),
            "endpoint_id": endpoint.id if endpoint else False,
            "handler_id": False,
            "company_id": endpoint.company_id.id if endpoint else self.env.company.id,
            "topic": metadata.get("topic"),
            "event_type": metadata.get("event_type"),
            "event_id": metadata.get("event_id"),
            "delivery_id": metadata.get("delivery_id"),
            "notification_id": metadata.get("notification_id"),
            "idempotency_key": metadata.get("idempotency_key"),
            "delivery_identity_key": delivery_identity_key,
            "delivery_identity_source": delivery_identity_source,
            "replay_identity_key": replay_identity_key,
            "replay_identity_source": replay_identity_source,
            "delivery_kind": "primary",
            "replayed_from_event_id": False,
            "signature": metadata.get("signature"),
            "signature_timestamp_raw": metadata.get("signature_timestamp"),
            "occurred_at_raw": metadata.get("occurred_at"),
            "tenant_key": metadata.get("tenant_key"),
            "version": metadata.get("version"),
            "resource_reference": metadata.get("resource_reference"),
            "handler_selector": metadata.get("handler_selector"),
            "resolved_values_json": self._serialize_resolved_values(resolved_values),
            "body_sha256": body_sha256,
            "request_body": body_text,
            "request_headers_json": self._serialize_headers(headers),
            "payload_json": self._serialize_payload(stored_payload),
            "state": "rejected",
            "rejection_category": rejection_category,
            "rejection_reason": rejection_reason,
        }
        try:
            with self.env.cr.savepoint():
                return self.with_user(SUPERUSER_ID).create(values)
        except IntegrityError:
            existing = self.with_user(SUPERUSER_ID).search(
                [
                    ("endpoint_id", "=", values.get("endpoint_id")),
                    ("delivery_identity_key", "=", delivery_identity_key),
                ],
                limit=1,
            )
            _logger.info(
                "Rejected webhook request for endpoint %s has the same delivery_identity_key as an existing event %s; skipping duplicate rejected log.",
                values.get("endpoint_id"),
                existing.id,
            )
            return existing

    @api.model
    def _receive_webhook_request(self, endpoint, body, headers):
        endpoint.ensure_one()
        payload = None
        payload_was_parsed = False
        try:
            payload = self._parse_payload(body.decode("utf-8", errors="replace"), raise_on_invalid=True)
            payload_was_parsed = True
            resolved_values = endpoint._extract_resolved_values(body, headers, payload)
            metadata = endpoint._extract_inbound_metadata(body, headers, payload, resolved_values=resolved_values)
            endpoint._validate_inbound_request(body, headers, payload, metadata)

            body_sha256 = hashlib.sha256(body).hexdigest()
            delivery_identity_key, delivery_identity_source = endpoint._resolve_delivery_identity(body_sha256, metadata)
            replay_identity_key, replay_identity_source = endpoint._resolve_replay_identity(metadata)
            existing = self.search(
                [
                    ("endpoint_id", "=", endpoint.id),
                    ("delivery_identity_key", "=", delivery_identity_key),
                ],
                limit=1,
            )
            if existing:
                if existing.state in ("received", "error"):
                    existing._queue_processing()
                return existing

            replayed_from_event = False
            delivery_kind = "primary"
            if replay_identity_key:
                replayed_from_event = self.search(
                    [
                        ("endpoint_id", "=", endpoint.id),
                        ("replay_identity_key", "=", replay_identity_key),
                        ("state", "!=", "rejected"),
                    ],
                    order="received_at asc, id asc",
                    limit=1,
                )
                if replayed_from_event:
                    delivery_kind = "replay"

            handler = endpoint._resolve_handler(metadata)
            values = self._prepare_create_values_from_request(
                endpoint,
                handler,
                body,
                headers,
                payload,
                resolved_values,
                metadata,
                delivery_identity_key=delivery_identity_key,
                delivery_identity_source=delivery_identity_source,
                replay_identity_key=replay_identity_key,
                replay_identity_source=replay_identity_source,
                delivery_kind=delivery_kind,
                replayed_from_event=replayed_from_event,
            )
            try:
                with self.env.cr.savepoint():
                    event = self.create(values)
            except IntegrityError:
                event = self.search(
                    [
                        ("endpoint_id", "=", endpoint.id),
                        ("delivery_identity_key", "=", delivery_identity_key),
                    ],
                    limit=1,
                )

            if event.state in ("received", "error"):
                event._queue_processing()
            return event
        except (WebhookValidationError, ValidationError) as err:
            self._log_rejected_request(
                endpoint,
                body,
                headers,
                payload=payload if payload_was_parsed else None,
                payload_parse_failed=not payload_was_parsed,
                rejection_category=getattr(err, "rejection_category", "validation"),
                rejection_reason=str(err),
            )
            raise

    def _queue_processing(self):
        if self.filtered(lambda event: event.state not in ("received", "error")):
            raise ValidationError(self.env._("Only received or failed webhook events can be queued for processing."))
        for event in self:
            event.write({"processing_error": False})
            event.with_user(SUPERUSER_ID).with_delay(identity_key=event._get_queue_job_identity_key()).process_event()

    def action_queue_processing(self):
        self._queue_processing()
        return True

    def action_reset_to_received(self):
        for event in self:
            if event.state not in ("error", "dead_letter"):
                raise ValidationError(self.env._("Only failed or dead-letter webhook events can be reset to received."))
            event.write(
                {
                    "state": "received",
                    "processing_error": False,
                    "processing_note": False,
                    "processed_at": False,
                    "matched_inbound_rule_id": False,
                }
            )
        return True

    def _execute_model_driven_handler(self, handler):
        self.ensure_one()
        matched_rule = self._match_inbound_rule(handler)
        if not matched_rule:
            return {
                "status": "done",
                "note": self.env._(
                    "No inbound model-driven rule matched on handler %(handler)s. The event was stored only.",
                    handler=handler.display_name,
                ),
            }

        execution = self.env["bwt.webhook.inbound.rule.execution"].create(
            {
                "name": "%s / %s" % (self.display_name, matched_rule.display_name),
                "event_id": self.id,
                "rule_id": matched_rule.id,
                "state": "matched",
                "note": matched_rule.note or False,
            }
        )

        try:
            action = self._INBOUND_ACTION_DISPATCH[matched_rule.action_type]
            return action(self, matched_rule, execution)
        except Exception:
            execution.write(
                {
                    "state": "error",
                    "error": traceback.format_exc(),
                }
            )
            raise

    def _match_inbound_rule(self, handler):
        rules = handler.inbound_rule_ids.filtered("active").sorted(key=lambda record: (record.sequence, record.id))
        for rule in rules:
            if all(self._inbound_condition_matches(condition) for condition in rule.condition_ids.sorted(key=lambda record: (record.sequence, record.id))):
                return rule
        return False

    def _action_terminal(self, rule, execution, status):
        """Shared body for ``done``/``dead_letter`` rule actions."""
        execution.write({"state": "done"})
        return {
            "status": status,
            "note": rule.note or False,
            "matched_rule_id": rule.id,
        }

    def _action_done(self, rule, execution):
        return self._action_terminal(rule, execution, "done")

    def _action_dead_letter(self, rule, execution):
        return self._action_terminal(rule, execution, "dead_letter")

    def _action_retry(self, rule, execution):
        execution.write({"state": "done"})
        return {
            "status": "retry",
            "note": rule.note or False,
            "seconds": rule.retry_seconds or False,
            "matched_rule_id": rule.id,
        }

    def _action_record_mutation(self, rule, execution):
        """Handle ``create_record``/``update_record``/``upsert_record``."""
        model = self.env[rule.target_model_name]
        values = self._build_inbound_assignment_values(rule, target_kind="field")
        target_record = False
        if rule.action_type in ("update_record", "upsert_record"):
            domain = self._build_inbound_lookup_domain(rule)
            target_record = model.search(domain, limit=1)
        if rule.action_type == "create_record":
            target_record = model.create(values)
        elif rule.action_type == "update_record":
            if not target_record:
                raise ValidationError(
                    self.env._(
                        "No target record matched inbound update rule %(rule)s.",
                        rule=rule.display_name,
                    )
                )
            target_record.write(values)
        elif target_record:
            target_record.write(values)
        else:
            target_record = model.create(values)
        record_reference = "%s:%s" % (target_record._name, target_record.id)
        execution.write({"state": "done", "record_reference": record_reference})
        return {
            "status": "done",
            "note": rule.note or record_reference,
            "matched_rule_id": rule.id,
        }

    _INBOUND_ACTION_DISPATCH = {
        "done": _action_done,
        "dead_letter": _action_dead_letter,
        "retry": _action_retry,
        "create_record": _action_record_mutation,
        "update_record": _action_record_mutation,
        "upsert_record": _action_record_mutation,
    }

    def _decode_literal_value(self, value):
        return decode_literal_value(value)

    def _resolve_inbound_source_value(self, source_kind, source_expression=False, literal_value=False):
        self.ensure_one()
        if source_kind == "literal":
            return decode_literal_value(literal_value)
        if source_kind == "resolved_value":
            return self.get_resolved_value(source_expression)
        if source_kind in ("semantic_field", "event_field"):
            return getattr(self, source_expression)
        return False

    def _inbound_condition_matches(self, condition):
        actual_value = self._resolve_inbound_source_value(condition.source_kind, condition.source_expression)
        try:
            return evaluate_condition(actual_value, condition.operator, condition.expected_value)
        except UnsupportedOperator as exc:
            raise ValidationError(
                self.env._(
                    "Unsupported inbound rule condition operator %(operator)s.",
                    operator=exc.operator,
                )
            ) from exc

    def _build_inbound_lookup_domain(self, rule):
        self.ensure_one()
        domain = []
        for lookup in rule.lookup_ids.sorted(key=lambda record: (record.sequence, record.id)):
            value = self._resolve_inbound_source_value(lookup.source_kind, lookup.source_expression, lookup.literal_value)
            domain.append((lookup.target_field_name, "=", value))
        return domain

    def _build_inbound_assignment_values(self, rule, *, target_kind):
        self.ensure_one()
        values = {}
        for assignment in rule.assignment_ids.filtered(lambda record: record.target_kind == target_kind).sorted(key=lambda record: (record.sequence, record.id)):
            values[assignment.target_expression] = self._resolve_inbound_source_value(
                assignment.source_kind,
                assignment.source_expression,
                assignment.literal_value,
            )
        return values

    def process_event(self):
        for event in self:
            if event.state in ("done", "rejected", "dead_letter"):
                continue
            try:
                event.write({"state": "processing", "processing_error": False})
                if event.handler_id:
                    result = event.handler_id.execute_inbound(event)
                else:
                    result = event._invoke_inbound_dispatch()
                    if result is None:
                        event.write(
                            {
                                "state": "done",
                                "processed_at": fields.Datetime.now(),
                                "processing_note": self.env._("No handler was resolved. The event was stored only."),
                                "processing_error": False,
                            }
                        )
                        continue
                event._apply_inbound_result(result)
            except RetryableJobError:
                raise
            except Exception:
                event.write(
                    {
                        "state": "error",
                        "processing_error": traceback.format_exc(),
                    }
                )
                raise
        return True

    def _invoke_inbound_dispatch(self):
        """Extension point used when no ``handler_id`` is configured.

        Default returns ``None``, which causes :meth:`process_event` to
        mark the event as ``done`` with the standard "stored only"
        note. The connector overlay overrides this to dispatch
        directly to the linked connector backend's
        ``_handle_inbound_webhook_event`` and return its result dict.
        """
        self.ensure_one()
        return None

    def _apply_inbound_result(self, result):
        """Apply a handler/dispatcher result dict (or bool) to ``self``."""
        self.ensure_one()
        if isinstance(result, dict):
            status = result.get("status", "done")
            note = result.get("note") or result.get("message")
            matched_rule_id = result.get("matched_rule_id") or False
            if status == "retry":
                self.write(
                    {
                        "state": "received",
                        "processing_note": note or False,
                        "matched_inbound_rule_id": matched_rule_id,
                    }
                )
                raise RetryableJobError(
                    note or self.env._("Retry requested by handler."),
                    seconds=result.get("seconds"),
                )
            if status == "dead_letter":
                self.write(
                    {
                        "state": "dead_letter",
                        "processed_at": fields.Datetime.now(),
                        "processing_note": note or False,
                        "matched_inbound_rule_id": matched_rule_id,
                    }
                )
                return
            if status == "received":
                self.write(
                    {
                        "state": "received",
                        "processing_note": note or False,
                        "matched_inbound_rule_id": matched_rule_id,
                    }
                )
                return
            self.write(
                {
                    "state": "done",
                    "processed_at": fields.Datetime.now(),
                    "processing_note": note or False,
                    "matched_inbound_rule_id": matched_rule_id,
                }
            )
            return
        if result is False:
            self.write({"state": "received"})
            return
        self.write(
            {
                "state": "done",
                "processed_at": fields.Datetime.now(),
                "processing_note": False,
            }
        )
