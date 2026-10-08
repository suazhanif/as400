import json
import logging
from datetime import timedelta

from odoo import fields, http
from odoo.http import request

_logger = logging.getLogger(__name__)

DEFAULT_INVOICE_LOOKBACK_DAYS = 35
DEFAULT_ASSET_LOOKBACK_DAYS = 90



class As400Controller(http.Controller):

    # ------------------------------------------------------------------
    # Helpers
    # ------------------------------------------------------------------

    def _get_payload(self):
        try:
            return request.get_json_data()
        except Exception:
            try:
                return json.loads(request.httprequest.data or b'{}')
            except Exception:
                return {}

    def _json(self, data, status=200):
        response = request.make_json_response(data)
        response.status_code = status
        return response

    def _authenticate(self):
        api_key = request.httprequest.headers.get('X-API-Key')
        config = request.env['as400.config'].sudo()._get_by_key(api_key)
        if not config:
            return None, self._json({'error': 'Unauthorized: invalid or missing X-API-Key header.'}, 401)
        return config, None

    def _find_product(self, material_code):
        Product = request.env['product.product'].sudo()
        product = Product.search([('as400_material_code', '=', material_code)], limit=1)
        if not product:
            product = Product.search(['|', ('default_code', '=', material_code),
                                       ('barcode', '=', material_code)], limit=1)
        return product

    def _is_whole_number(self, quantity):
        try:
            return float(quantity) == int(float(quantity))
        except (TypeError, ValueError):
            return False

    def _apply_single_stock_update(self, config, company, item):
        """Applies one {material_code, quantity, location_code, material_name,
        lpo_number} update. Returns a per-item result dict; never raises - the
        caller decides whether an individual failure should affect the batch."""
        material_code = item.get('material_code')
        quantity = item.get('quantity')

        if not material_code or quantity is None:
            return {'material_code': material_code, 'status': 'error',
                    'error': '"material_code" and "quantity" are required.'}

        if not self._is_whole_number(quantity):
            return {'material_code': material_code, 'status': 'error',
                    'error': f'Quantity must be a whole number (no decimals). Received: {quantity}.'}
        quantity = int(quantity)

        product = self._find_product(material_code)
        if not product:
            return {'material_code': material_code, 'status': 'error',
                    'error': f'No product found for material_code "{material_code}". '
                             f'No product is auto-created - double check the code.'}

        # Optional verification-only check: flag a mismatch, never auto-rename.
        warning = None
        material_name = item.get('material_name')
        if material_name and product.name and material_name.strip().lower() != product.name.strip().lower():
            warning = (f'Product name mismatch: LS400 sent "{material_name}", Odoo has "{product.name}". '
                       f'Quantity was still updated - verify material_code is correct if this is unexpected.')

        location_code = item.get('location_code')
        location = request.env['stock.location'].sudo()
        if location_code:
            location = location.search(
                [('complete_name', '=ilike', location_code), ('company_id', '=', company.id)], limit=1)
        if not location:
            location = config.default_location_id
        if not location:
            return {'material_code': material_code, 'status': 'error',
                    'error': 'No location specified and no default location configured for this company.'}

        lpo_number = item.get('lpo_number')
        before_move_ids = set(request.env['stock.move'].sudo().search(
            [('product_id', '=', product.id)]).ids)

        try:
            with request.env.cr.savepoint():
                quant = request.env['stock.quant'].sudo().with_company(company).search([
                    ('product_id', '=', product.id),
                    ('location_id', '=', location.id),
                    ('company_id', '=', company.id),
                ], limit=1)
                if not quant:
                    quant = request.env['stock.quant'].sudo().with_company(company).create({
                        'product_id': product.id,
                        'location_id': location.id,
                        'company_id': company.id,
                    })
                quant.inventory_quantity = quantity
                quant.action_apply_inventory()

                if lpo_number:
                    new_moves = request.env['stock.move'].sudo().search([
                        ('product_id', '=', product.id),
                        ('id', 'not in', list(before_move_ids)),
                    ])
                    if new_moves:
                        new_moves.write({'origin': lpo_number})
        except Exception as exc:
            return {'material_code': material_code, 'status': 'error', 'error': str(exc)}

        result = {
            'material_code': material_code,
            'status': 'ok',
            'product': product.display_name,
            'location': location.complete_name,
            'quantity_set': quantity,
        }
        if lpo_number:
            result['lpo_number'] = lpo_number
        if warning:
            result['warning'] = warning
        return result

    # ------------------------------------------------------------------
    # 1) LS400 -> Odoo : bulk stock quantity update
    # ------------------------------------------------------------------
    @http.route('/api/as400/stock/update', type='http', auth='public',
                methods=['POST'], csrf=False)
    def stock_update(self, **kwargs):
        config, error = self._authenticate()
        if error:
            return error
        company = config.company_id
        payload = self._get_payload()
        Log = request.env['as400.api.log']

        # Accept either {"updates": [...]}  or a single {"material_code": ..., "quantity": ...}
        if isinstance(payload, dict) and 'updates' in payload:
            items = payload.get('updates') or []
        elif isinstance(payload, dict) and 'material_code' in payload:
            items = [payload]
        else:
            items = payload if isinstance(payload, list) else []

        if not items:
            msg = {'error': 'Provide either {"updates": [...]} with one or more items, '
                             'or a single {"material_code": ..., "quantity": ...} object.'}
            Log.log('inbound', '/api/as400/stock/update', company=company,
                    request_payload=payload, status='error', error_message=msg['error'])
            return self._json(msg, 400)

        results = [self._apply_single_stock_update(config, company, item) for item in items]
        error_count = sum(1 for r in results if r['status'] == 'error')

        response = {
            'result': 'ok' if error_count == 0 else 'partial' if error_count < len(results) else 'error',
            'total': len(results),
            'success_count': len(results) - error_count,
            'error_count': error_count,
            'results': results,
        }
        overall_status = 'success' if error_count == 0 else 'error'
        Log.log('inbound', '/api/as400/stock/update', company=company,
                request_payload=payload, response_payload=response, status=overall_status)

        http_status = 200 if error_count < len(results) else 400
        return self._json(response, http_status)

    # ------------------------------------------------------------------
    # 2) LS400 -> Odoo : daily pull of consumption (WH/Stock -> Production)
    # ------------------------------------------------------------------
    @http.route('/api/as400/stock/consumption', type='http', auth='public',
                methods=['GET'], csrf=False)
    def stock_consumption(self, **kwargs):
        config, error = self._authenticate()
        if error:
            return error
        company = config.company_id
        Log = request.env['as400.api.log']

        if not config.consumption_location_ids:
            msg = {'error': 'No Consumption Destination Locations configured for this company.'}
            Log.log('inbound', '/api/as400/stock/consumption', company=company,
                    status='error', error_message=msg['error'])
            return self._json(msg, 400)

        date_from = kwargs.get('date_from') or (
            fields.Datetime.to_string(config.last_consumption_sync) if config.last_consumption_sync else False)
        date_to = kwargs.get('date_to') or fields.Datetime.to_string(fields.Datetime.now())

        domain = [
            ('state', '=', 'done'),
            ('company_id', '=', company.id),
            ('location_dest_id', 'in', config.consumption_location_ids.ids),
        ]
        if date_from:
            domain.append(('date', '>=', date_from))
        domain.append(('date', '<=', date_to))

        moves = request.env['stock.move'].sudo().search(domain)

        lines = []
        for move in moves:
            lines.append({
                'move_id': move.id,
                'date': fields.Datetime.to_string(move.date),
                'material_code': move.product_id.as400_material_code
                                  or move.product_id.default_code or '',
                'product_name': move.product_id.display_name,
                'quantity': move.product_uom_qty,
                'uom': move.product_uom.name,
                'source_location': move.location_id.complete_name,
                'destination_location': move.location_dest_id.complete_name,
                'reference': move.reference,
            })

        response = {
            'result': 'ok',
            'period_from': date_from,
            'period_to': date_to,
            'count': len(lines),
            'consumption': lines,
        }

        if not kwargs.get('date_from') and not kwargs.get('date_to'):
            config.last_consumption_sync = date_to

        Log.log('inbound', '/api/as400/stock/consumption', company=company,
                request_payload=dict(kwargs), response_payload=response, status='success')
        return self._json(response, 200)

    # ------------------------------------------------------------------
    # 3) LS400 -> Odoo : pull paid & posted invoices (monthly, or a custom window)
    # ------------------------------------------------------------------
    @http.route('/api/as400/invoices', type='http', auth='public',
                methods=['GET'], csrf=False)
    def invoices_pull(self, **kwargs):
        config, error = self._authenticate()
        if error:
            return error
        company = config.company_id
        Log = request.env['as400.api.log']

        manual_window = bool(kwargs.get('date_from') or kwargs.get('date_to'))

        domain = [
            ('move_type', '=', 'out_invoice'),
            ('state', '=', 'posted'),
            ('payment_state', 'in', ('paid', 'in_payment')),
            ('company_id', '=', company.id),
        ]

        if manual_window:
            # Reconciliation / backfill mode: filter by actual timestamps and
            # allow re-returning invoices already marked as synced.
            date_from = kwargs.get('date_from') or fields.Datetime.to_string(
                fields.Datetime.now() - timedelta(days=DEFAULT_INVOICE_LOOKBACK_DAYS))
            date_to = kwargs.get('date_to') or fields.Datetime.to_string(fields.Datetime.now())
            domain += [('write_date', '>=', date_from), ('write_date', '<=', date_to)]
        else:
            # Automatic mode: anything not yet marked as sent to AS400.
            # Using a flag instead of a timestamp avoids a self-referential bug -
            # marking an invoice synced would otherwise bump its own write_date
            # into the next call's window and cause it to reappear indefinitely.
            date_from = fields.Datetime.to_string(config.last_invoice_sync) if config.last_invoice_sync else False
            date_to = fields.Datetime.to_string(fields.Datetime.now())
            domain += [('as400_synced', '=', False)]

        invoices = request.env['account.move'].sudo().search(domain)
        data = [inv._as400_build_payload() for inv in invoices]

        response = {
            'result': 'ok',
            'period_from': date_from,
            'period_to': date_to,
            'count': len(data),
            'invoices': data,
        }

        if not manual_window:
            if invoices:
                invoices.write({'as400_synced': True, 'as400_synced_date': fields.Datetime.now()})
            config.last_invoice_sync = date_to

        Log.log('inbound', '/api/as400/invoices', company=company,
                request_payload=dict(kwargs), response_payload=response, status='success')
        return self._json(response, 200)
    # ------------------------------------------------------------------
    # 4) LS400 -> Odoo : push a new/updated asset
    # ------------------------------------------------------------------
    # ------------------------------------------------------------------
    # 4) LS400 <-> Odoo : push a new/updated asset (POST), or pull current
    #    asset data for a back-sync into LS400 (GET) - same endpoint.
    # ------------------------------------------------------------------
    @http.route('/api/as400/assets', type='http', auth='public',
                methods=['GET', 'POST'], csrf=False)
    def assets_endpoint(self, **kwargs):
        config, error = self._authenticate()
        if error:
            return error
        company = config.company_id

        if request.httprequest.method == 'GET':
            return self._assets_pull(config, company, kwargs)
        return self._assets_push(config, company)

    def _assets_pull(self, config, company, kwargs):
        Log = request.env['as400.api.log']
        Asset = request.env['account.asset'].sudo()

        ref = kwargs.get('as400_asset_ref')
        response = {}

        if ref:
            # Single-asset lookup, e.g. to refresh one record on demand.
            assets = Asset.search([
                ('company_id', '=', company.id),
                ('as400_asset_ref', '=', ref),
            ])
        else:
            if kwargs.get('date_from'):
                date_from = kwargs.get('date_from')
            elif config.last_asset_sync:
                date_from = fields.Datetime.to_string(config.last_asset_sync)
            else:
                date_from = fields.Datetime.to_string(
                    fields.Datetime.now() - timedelta(days=DEFAULT_ASSET_LOOKBACK_DAYS))
            date_to = kwargs.get('date_to') or fields.Datetime.to_string(fields.Datetime.now())

            assets = Asset.search([
                ('company_id', '=', company.id),
                ('as400_asset_ref', '!=', False),
                ('write_date', '>=', date_from),
                ('write_date', '<=', date_to),
            ])

            response['period_from'] = date_from
            response['period_to'] = date_to

            if not kwargs.get('date_from') and not kwargs.get('date_to'):
                config.last_asset_sync = date_to

        data = [a._as400_build_payload() for a in assets]
        response.update({'result': 'ok', 'count': len(data), 'assets': data})

        Log.log('inbound', '/api/as400/assets [GET]', company=company,
                request_payload=dict(kwargs), response_payload=response, status='success')
        return self._json(response, 200)

    def _assets_push(self, config, company):
        payload = self._get_payload()
        Log = request.env['as400.api.log']

        try:
            asset, created, warnings = request.env['account.asset']._as400_create_or_update(payload, company)
        except Exception as exc:
            Log.log('inbound', '/api/as400/assets [POST]', company=company,
                    request_payload=payload, status='error', error_message=str(exc))
            return self._json({'error': str(exc)}, 400)

        response = {
            'result': 'created' if created else 'updated',
            'asset_id': asset.id,
            'asset_name': asset.display_name,
            'warnings': warnings,
        }
        Log.log('inbound', '/api/as400/assets [POST]', company=company,
                request_payload=payload, response_payload=response,
                status='success', res_model='account.asset', res_id=asset.id)
        return self._json(response, 201 if created else 200)