from odoo import fields, models


class ResUsers(models.Model):
    _inherit = "res.users"

    webhook_allowed_partner_ids = fields.Many2many(
        "res.partner",
        "res_users_webhook_partner_rel",
        "user_id",
        "partner_id",
        string="Allowed Webhook Partners",
        domain="[('is_company', '=', True)]",
        help="Partner-scoped webhook records are visible to this user only when the record partner is in this list. Company-scoped webhook records stay visible through company rules.",
    )
