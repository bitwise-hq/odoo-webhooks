import logging

from odoo import SUPERUSER_ID
from odoo.exceptions import ValidationError
from odoo.http import Controller, request, route
from werkzeug.exceptions import BadRequest, Forbidden, NotFound

from ..exceptions import WebhookValidationError


_logger = logging.getLogger(__name__)


class WebhookController(Controller):
    @route('/webhooks/in/<string:endpoint_path>', type='http', auth='public', methods=['POST'], csrf=False, save_session=False)
    def inbound_webhook(self, endpoint_path, **kwargs):
        body = request.httprequest.get_data(cache=True) or b''
        headers = request.httprequest.headers
        automated_context = dict(request.env.context, webhook_automated_execution=True)
        lookup_env = request.env(user=SUPERUSER_ID, context=automated_context)
        endpoint = lookup_env['webhook.endpoint']._find_active_endpoint_by_path(endpoint_path)
        if not endpoint:
            raise NotFound()

        execution_env = request.env(user=SUPERUSER_ID, context=automated_context)
        endpoint_execution = execution_env['webhook.endpoint'].browse(endpoint.id)

        try:
            event = execution_env['webhook.inbound.event']._receive_webhook_request(endpoint_execution, body, headers)
        except WebhookValidationError as err:
            if getattr(err, 'http_status_code', 400) == 403:
                raise Forbidden(str(err)) from err
            raise BadRequest(str(err)) from err
        except ValidationError as err:
            raise BadRequest(str(err)) from err

        _logger.info(
            'Stored inbound webhook event %s on endpoint %s.',
            event.id,
            endpoint.display_name,
        )
        return request.make_json_response({'status': 'accepted', 'event_id': event.id}, status=202)