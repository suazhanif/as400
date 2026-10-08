import json

from odoo import api, fields, models


class Ls400ApiLog(models.Model):
    _name = 'as400.api.log'
    _description = 'AS400 API Call Log'
    _order = 'create_date desc'

    name = fields.Char(compute='_compute_name', store=True)
    direction = fields.Selection(
        [('inbound', 'Inbound (AS400 -> Odoo)'), ('outbound', 'Outbound (Odoo -> AS400)')],
        required=True, readonly=True)
    endpoint = fields.Char(required=True, readonly=True)
    company_id = fields.Many2one('res.company', readonly=True)
    status = fields.Selection(
        [('success', 'Success'), ('error', 'Error')],
        default='success', readonly=True)
    http_status = fields.Integer(readonly=True)
    request_payload = fields.Text(readonly=True)
    response_payload = fields.Text(readonly=True)
    error_message = fields.Text(readonly=True)
    res_model = fields.Char(readonly=True)
    res_id = fields.Integer(readonly=True)

    @api.depends('endpoint', 'direction', 'status')
    def _compute_name(self):
        for rec in self:
            rec.name = f"[{rec.status}] {rec.endpoint} ({rec.direction})"

    @api.model
    def log(self, direction, endpoint, company=None, request_payload=None,
             response_payload=None, status='success', http_status=None,
             error_message=None, res_model=None, res_id=None):
        """Best-effort logger - a logging failure must never break the actual
        integration call, so this always runs in its own cursor-safe sudo call."""

        def _safe(value):
            if value is None:
                return False
            if isinstance(value, (dict, list)):
                try:
                    return json.dumps(value, default=str, ensure_ascii=False)
                except Exception:
                    return str(value)
            return str(value)

        try:
            return self.sudo().create({
                'direction': direction,
                'endpoint': endpoint,
                'company_id': company.id if company else False,
                'request_payload': _safe(request_payload),
                'response_payload': _safe(response_payload),
                'status': status,
                'http_status': http_status,
                'error_message': error_message,
                'res_model': res_model,
                'res_id': res_id,
            })
        except Exception:
            return False
