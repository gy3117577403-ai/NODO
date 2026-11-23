import hashlib
import json

from odoo import fields, models
from odoo.exceptions import UserError

from odoo.addons.nodo_base.sheet_materials import MATERIALS
from odoo.addons.nodo_cost.materials import stock_key
from odoo.addons.nodo_draw.models import specification
from odoo.addons.nodo_draw.models.workbench import read_json


def part_stock(parameters, part, thickness):
    part = 'door' if part == 'door_right' else part
    group = MATERIALS['parts'][part]
    material = parameters.get('materials', {})
    choice = material.get('parts', {}).get(part, material.get(group, {'category': MATERIALS['groups'][group]}))
    return stock_key(choice['category'], choice.get('grade'), choice.get('condition'), thickness)


class DrawDesign(models.Model):
    _inherit = 'nodo.draw.design'

    sheet_cost_sequence = fields.Integer(string='板料核算版次', readonly=True, copy=False)

    def sheet_price_choices(self):
        self._check_read()
        return self.env['nodo.cost.sheet.price'].search_read([('company_id', '=', self.company_id.id)],
            ['category', 'grade', 'supply_condition', 'thickness_mm', 'price_per_kg', 'basis', 'display_name'])

    def _sheet_calculation(self, usage_id):
        self._check_read()
        jobs = self.env['nodo.draw.job']
        usage = jobs.search([('id', '=', usage_id), ('design_id', '=', self.id),
            ('edit_number', '=', self.edit_number), ('preview_user_id', '=', self.env.uid),
            ('operation', '=', 'sheet_usage')], limit=1)
        if not usage:
            raise UserError('请重新打开当前版本的板料用量。')
        model = jobs.search([('token', '=', usage.payload['model_token']), ('design_id', '=', self.id),
                             ('edit_number', '=', self.edit_number), ('operation', 'in', ('preview', 'build'))], limit=1)
        status = read_json(usage._folder() / 'status.json')
        if not model or status.get('state') != 'done' or status.get('files', {}).get('usage') != 'usage.json':
            raise UserError('当前板料用量尚未就绪。')
        data = read_json(usage._folder() / status['run'] / 'usage.json')
        if not data.get('rows'):
            raise UserError('板料清单读取失败，请重新打开用量表。')
        parameters = model.payload['parameters']
        rows = [dict(key=r['key'], weight=r['weight'], stock=part_stock(parameters, r['key'], r['thickness']))
                for r in data['rows']]
        prices = self.env['nodo.cost.sheet.price']._sheet_costs(self.company_id, rows)
        columns = ('key', 'name', 'code', 'material', 'thickness', 'quantity', 'area', 'weight', 'needs_review')
        detail = []
        for measured, item in zip(data['rows'], rows):
            rate = prices['lines'][item['key']]
            detail.append({**{k: measured.get(k) for k in columns}, 'stock': list(item['stock']),
                           **(rate or {})})
        geometry = {k: parameters.get(k) for k in ('width', 'depth', 'height', 'configuration', 'thickness', 'materials', 'holes')}
        snapshot = dict(source=self.source, source_version=self.source_version, design_name=self.name,
                        edit=self.edit_number, geometry=geometry, area_basis='outer_including_holes', rows=detail,
                        **{k: data.get(k) for k in ('area', 'weight', 'density', 'pieces')},
                        total=prices['total'], trial=prices['trial'])
        encoded = json.dumps(snapshot, sort_keys=True, ensure_ascii=False, separators=(',', ':'), allow_nan=False)
        prices['fingerprint'] = hashlib.sha256(encoded.encode()).hexdigest()
        return prices, snapshot

    def current_sheet_costs(self, usage_id):
        prices, _snapshot = self._sheet_calculation(usage_id)
        return prices

    def save_sheet_cost_version(self, expected, usage_id, fingerprint):
        self._lock_editor(expected)
        prices, snapshot = self._sheet_calculation(usage_id)
        if prices['missing']:
            raise UserError('请补齐板料单价后再保存核算版本。')
        if fingerprint != prices['fingerprint']:
            raise UserError('用量或价格已变化，请核对最新金额后再保存。')
        if (any(snapshot[k] is None for k in ('area', 'weight', 'density', 'pieces')) or
                any(any(v is None for v in row.values()) for row in snapshot['rows'])):
            raise UserError('展开用量明细不完整，请更新预览后再保存。')
        saved = specification.parameters(self.settings, self.library, 0)
        if any(saved.get(k) != v for k, v in snapshot['geometry'].items()):
            raise UserError('当前预览和已保存的柜体参数不同，请先保存设计并更新预览。')
        versions = self.env['nodo.draw.sheet.cost.version']
        latest = versions.search([('design_id', '=', self.id)], limit=1)
        if latest and latest.fingerprint == fingerprint:
            return latest.id
        number = (latest.number or 0) + 1
        # A real row update serializes concurrent saves under PostgreSQL repeatable read.
        # The independent engineering edit number and its CAD jobs keep their identity.
        self.sudo().write({'sheet_cost_sequence': number})
        return versions.sudo().create(dict(design_id=self.id, company_id=self.company_id.id, number=number,
                                           fingerprint=fingerprint, payload=snapshot)).id

    def sheet_cost_versions(self):
        self._check_read()
        versions = self.env['nodo.draw.sheet.cost.version'].search([('design_id', '=', self.id)])
        return [v._header() for v in versions]

    def read_sheet_cost_version(self, version_id):
        self._check_read()
        versions = self.env['nodo.draw.sheet.cost.version']
        version = versions.search([('id', '=', version_id), ('design_id', '=', self.id)], limit=1)
        if not version:
            raise UserError('此柜体没有该核算版本。')
        previous = versions.search([('design_id', '=', self.id), ('number', '<', version.number)], limit=1)
        return {**version._header(), 'snapshot': version.payload,
                'comparison': version._compare(previous) if previous else None}
