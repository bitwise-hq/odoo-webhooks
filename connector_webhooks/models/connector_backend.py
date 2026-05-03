from odoo import api, fields, models
from odoo.exceptions import ValidationError


class ConnectorBackend(models.AbstractModel):
    _inherit = "connector.backend"

    webhook_endpoint_id = fields.Many2one(
        "webhook.inbound.endpoint",
        string="Inbound Endpoint",
        readonly=True,
        copy=False,
        check_company=True,
        ondelete="set null",
    )
    outbound_endpoint_id = fields.Many2one(
        "webhook.outbound.endpoint",
        string="Outbound Endpoint",
        readonly=True,
        copy=False,
        check_company=True,
        ondelete="set null",
    )
    inbound_handler_id = fields.Many2one(
        "webhook.handler",
        related="webhook_endpoint_id.handler_id",
        string="Inbound Handler",
        readonly=True,
    )
    outbound_handler_id = fields.Many2one(
        "webhook.handler",
        related="outbound_endpoint_id.handler_id",
        string="Outbound Handler",
        readonly=True,
    )
    route_path = fields.Char(related="webhook_endpoint_id.route_path", readonly=True)
    outbound_target_url = fields.Char(
        related="outbound_endpoint_id.target_url",
        readonly=True,
    )

    @api.model
    def _selection_connector_backend_models(self):
        model_selection = []
        for model_name in sorted(self.env):
            if model_name == "connector.backend":
                continue
            model = self.env[model_name]
            inherits = getattr(model, "_inherit", []) or []
            if isinstance(inherits, str):
                inherits = [inherits]
            if "connector.backend" not in inherits:
                continue
            if getattr(model, "_abstract", False):
                continue
            model_selection.append((model_name, model._description or model_name))
        return model_selection

    def _get_connector_backend_reference(self):
        self.ensure_one()
        return f"{self._name},{self.id}" if self.id else False

    def _ensure_webhook_link(self, field_name):
        self.ensure_one()
        if not getattr(self, field_name) and hasattr(self, "_sync_webhook_configuration"):
            self._sync_webhook_configuration()
        return getattr(self, field_name)

    def action_view_inbound_endpoint(self):
        self.ensure_one()
        endpoint = self._ensure_webhook_link("webhook_endpoint_id")
        if not endpoint:
            raise ValidationError(
                self.env._("No inbound webhook endpoint is linked to this backend.")
            )
        action = self.env.ref("webhooks.action_webhook_endpoint").read()[0]
        action["res_id"] = endpoint.id
        action["view_mode"] = "form"
        action["views"] = [
            (self.env.ref("webhooks.view_webhook_endpoint_form").id, "form")
        ]
        return action

    def action_view_outbound_endpoint(self):
        self.ensure_one()
        endpoint = self._ensure_webhook_link("outbound_endpoint_id")
        if not endpoint:
            raise ValidationError(
                self.env._("No outbound webhook endpoint is linked to this backend.")
            )
        action = self.env.ref("webhooks.action_webhook_outbound_endpoint").read()[0]
        action["res_id"] = endpoint.id
        action["view_mode"] = "form"
        action["views"] = [
            (
                self.env.ref("webhooks.view_webhook_outbound_endpoint_form").id,
                "form",
            )
        ]
        return action