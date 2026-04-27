import logging

from odoo import SUPERUSER_ID
from odoo.exceptions import ValidationError
from odoo.http import Controller, request, route
from werkzeug.exceptions import BadRequest, Forbidden, NotFound

from odoo.addons.bwt_webhooks_core.exceptions import WebhookValidationError


_logger = logging.getLogger(__name__)


class WebhookController(Controller):
    def _is_non_empty_recordset(self, value):
        ids = getattr(value, "ids", None)
        return isinstance(ids, list) and bool(ids)

    def _resolve_endpoint(self, env, endpoint_path):
        """Return the active endpoint for path, or any endpoint by path.

        Active endpoints are preferred for normal traffic. When no active
        match exists, fall back to any endpoint with the same path so draft
        endpoints can still record rejected requests for auditability.
        """
        model = env["bwt.webhook.inbound.endpoint"]
        endpoint = model._find_active_endpoint_by_path(endpoint_path)
        if endpoint:
            return endpoint
        fallback = model.search([("path", "=", endpoint_path)], limit=1)
        return fallback if self._is_non_empty_recordset(fallback) else False

    @route(
        "/webhooks/in/<string:endpoint_path>",
        type="http",
        auth="public",
        methods=["POST"],
        csrf=False,
        save_session=False,
    )
    def inbound_webhook(self, endpoint_path, **kwargs):
        body = request.httprequest.get_data(cache=True) or b""
        headers = request.httprequest.headers
        automated_context = dict(request.env.context, webhook_automated_execution=True)
        request.update_env(user=SUPERUSER_ID, context=automated_context)

        # Use explicit env switches for both lookup and execution so
        # tests can stub separate env objects and runtime code stays under
        # SUPERUSER with webhook automation context.
        lookup_env = request.env(user=SUPERUSER_ID, context=automated_context)
        endpoint = self._resolve_endpoint(lookup_env, endpoint_path)
        if not endpoint:
            raise NotFound()

        execution_env = request.env(user=SUPERUSER_ID, context=automated_context)
        endpoint = execution_env["bwt.webhook.inbound.endpoint"].browse(endpoint.id)

        try:
            event = execution_env["bwt.webhook.inbound.event"]._receive_webhook_request(endpoint, body, headers)
        except WebhookValidationError as err:
            if getattr(err, "http_status_code", 400) == 403:
                raise Forbidden(str(err)) from err
            raise BadRequest(str(err)) from err
        except ValidationError as err:
            raise BadRequest(str(err)) from err

        _logger.info(
            "Stored inbound webhook event %s on endpoint %s.",
            event.id,
            endpoint.display_name,
        )
        return request.make_json_response({"status": "accepted", "event_id": event.id}, status=202)
