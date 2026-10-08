from odoo import _, api, fields, models
from odoo.exceptions import UserError


class AccountAsset(models.Model):
    _inherit = 'account.asset'

    as400_asset_ref = fields.Char(
        string='AS400 Asset Reference', index=True, copy=False,
        help='Unique ID of this asset in AS400. Used to match repeated pushes to the same '
             'asset instead of creating duplicates.')

    _sql_constraints = [
        ('as400_asset_ref_uniq', 'unique(as400_asset_ref)',
         'This AS400 Asset Reference is already linked to another asset.'),
    ]

    def _as400_find_by_name(self, model, name, company):
        if not name:
            return self.env[model].browse()
        domain = [('name', '=ilike', name)]
        if 'company_id' in self.env[model]._fields:
            domain += ['|', ('company_id', '=', company.id), ('company_id', '=', False)]
        return self.env[model].sudo().search(domain, limit=1)

    def _as400_find_location(self, company, code=None, name=None):
        Location = self.env['asset.location'].sudo()
        if code:
            domain = [('code', '=ilike', code)]
            if 'company_id' in Location._fields:
                domain += ['|', ('company_id', '=', company.id), ('company_id', '=', False)]
            record = Location.search(domain, limit=1)
            if not record and 'full_code' in Location._fields:
                domain2 = [('full_code', '=ilike', code)]
                if 'company_id' in Location._fields:
                    domain2 += ['|', ('company_id', '=', company.id), ('company_id', '=', False)]
                record = Location.search(domain2, limit=1)
            if record:
                return record
        if name:
            return self._as400_find_by_name('asset.location', name, company)
        return Location.browse()

    def _as400_build_payload(self):
        self.ensure_one()
        return {
            'as400_asset_ref': self.as400_asset_ref,
            'asset_id': self.id,
            'asset_name': self.name,
            'asset_code': self.asset_code,
            'employee_code': self.employee_code,
            'location_code': self.location_code,
            'customer_id': self.customer_id.id or False,
            'customer_name': self.customer_id.name or False,
            'responsible_id': self.responsible_id.id or False,
            'responsible_name': self.responsible_id.name or False,
            'updated_at': fields.Datetime.to_string(self.write_date),
        }

    def _as400_find_customer(self, vals, company, warnings):
        Partner = self.env['res.partner'].sudo()
        if vals.get('customer_id'):
            try:
                candidate = Partner.browse(int(vals['customer_id']))
            except (ValueError, TypeError):
                warnings.append(_('customer_id "%s" is not a valid ID - field left empty.') % vals['customer_id'])
                return Partner.browse()
            if candidate.exists():
                return candidate
            warnings.append(_('customer_id %s does not exist - field left empty.') % vals['customer_id'])
            return Partner.browse()
        if vals.get('customer_name'):
            record = self._as400_find_by_name('res.partner', vals['customer_name'], company)
            if not record:
                warnings.append(_('customer_id "%s" was not found - field left empty.') % vals['customer_name'])
            return record
        return Partner.browse()

    @api.model
    def _as400_create_or_update(self, vals, company):
        """Create or update an asset from an AS400 payload. Unresolved
        name/code-based references (customer/department/location/manufacturer)
        are left blank and reported back in `warnings` rather than failing
        the whole call."""
        warnings = []
        ref = vals.get('as400_asset_ref')
        if not ref:
            raise UserError(_('as400_asset_ref is required to create or update an asset.'))

        write_vals = {
            'as400_asset_ref': ref,
            'company_id': company.id,
            'asset_type': vals.get('asset_type') or 'physical',
            'asset_code': vals.get('asset_code'),
            'qr_code': vals.get('qr_code'),
            'serial_no': vals.get('serial_no'),
            'facility_code': vals.get('facility_code'),
            'asset_category': vals.get('asset_category'),
            'purchase_date': vals.get('purchase_date'),
            'purchase_price': vals.get('purchase_price'),
            'warranty_start_date': vals.get('warranty_start_date'),
            'warranty_end_date': vals.get('warranty_end_date'),
        }
        write_vals = {k: v for k, v in write_vals.items() if v is not None}

        customer = self._as400_find_customer(vals, company, warnings)
        if customer:
            write_vals['customer_id'] = customer.id

        location = self._as400_find_location(
            company, code=vals.get('location_code'), name=vals.get('location_name'))
        if location:
            write_vals['location_id'] = location.id
        elif vals.get('location_code') or vals.get('location_name'):
            warnings.append(_('location_id "%s" was not found - field left empty.')
                             % (vals.get('location_code') or vals.get('location_name')))

        for key, model, field in (
            ('manufacturer_name', 'res.partner', 'manufacturer_id'),
            ('service_provider_name', 'res.partner', 'service_provider_id'),
            ('department_name', 'hr.department', 'department_id'),
        ):
            name = vals.get(key)
            if not name:
                continue
            record = self._as400_find_by_name(model, name, company)
            if record:
                write_vals[field] = record.id
            else:
                warnings.append(_('%s "%s" was not found - field left empty.') % (field, name))

        asset = self.sudo().search(
            [('as400_asset_ref', '=', ref), ('company_id', '=', company.id)], limit=1)
        if asset:
            asset.write(write_vals)
            created = False
        else:
            asset = self.sudo().create(write_vals)
            created = True

        # Applied last and separately: 'name' is not in account.asset's
        # auto-rename trigger list, so this sticks even though the write()
        # above may have just regenerated 'name' from location/asset_code/etc.
        explicit_name = vals.get('name')
        if explicit_name:
            asset.write({'name': explicit_name})

        return asset, created, warnings