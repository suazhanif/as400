import uuid

from odoo import api, fields, models


class Ls400Config(models.Model):
    _name = 'as400.config'
    _description = 'AS400 Integration Configuration'
    _rec_name = 'company_id'

    company_id = fields.Many2one(
        'res.company', string='Company', required=True,
        default=lambda self: self.env.company)
    active = fields.Boolean(default=True,
        help='Untick to disable the AS400 integration for this company. '
             'All inbound calls authenticated with this key will then be rejected.')

    inbound_api_key = fields.Char(
        string='Inbound API Key', required=True, copy=False,
        default=lambda self: uuid.uuid4().hex,
        help='AS400 must send this value in the "X-API-Key" header on every call to our APIs. '
             'This key is also how we identify which company the call belongs to - '
             'never accept a company_id supplied by the caller.')
    default_location_id = fields.Many2one(
        'stock.location', string='Default Receiving Location',
        domain="[('usage', '=', 'internal'), ('company_id', 'in', (company_id, False))]",
        help='Location updated when AS400 pushes a quantity update without specifying one '
             '(e.g. WH/Stock).')
    consumption_location_ids = fields.Many2many(
        'stock.location', string='Consumption Destination Locations',
        domain="[('usage', '=', 'production'), ('company_id', 'in', (company_id, False))]",
        help='Validated stock moves whose destination is one of these locations are reported '
             'to AS400 as "consumption" in the daily pull.')
    last_consumption_sync = fields.Datetime(
        string='Last Consumption Sync', readonly=True,
        help='Consumption moves validated after this timestamp are included in the next pull.')
    last_invoice_sync = fields.Datetime(
        string='Last Invoice Sync', readonly=True,
        help='Invoices last returned to AS400 via /api/as400/invoices. '
             'The next automatic pull (no date_from/date_to given) starts from here.')
    last_asset_sync = fields.Datetime(
        string='Last Asset Sync', readonly=True,
        help='Assets last returned to AS400 via GET /api/as400/assets. '
             'The next automatic pull (no date_from/date_to given) starts from here.')

    _sql_constraints = [
        ('company_uniq', 'unique(company_id)',
         'Only one AS400 configuration is allowed per company.'),
    ]

    def action_regenerate_key(self):
        self.ensure_one()
        self.inbound_api_key = uuid.uuid4().hex

    @api.model
    def _get_by_key(self, api_key):
        if not api_key:
            return self.browse()
        return self.sudo().search([('inbound_api_key', '=', api_key), ('active', '=', True)], limit=1)