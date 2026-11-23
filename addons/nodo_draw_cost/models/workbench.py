from odoo import models
from odoo.exceptions import UserError

from odoo.addons.nodo_base.sheet_materials import MATERIALS
from odoo.addons.nodo_cost.materials import stock_key
from odoo.addons.nodo_draw.models.workbench import read_json


def part_stock(parameters, part, thickness):
    part = 'door' if part == 'door_right' else part
    group = MATERIALS['parts'][part]
    material = parameters.get('materials', {})
    choice = material.get('parts', {}).get(part, material.get(group, {'category': MATERIALS['groups'][group]}))
    return stock_key(choice['category'], choice.get('grade'), choice.get('condition'), thickness)


class DrawDesign(models.Model):
    _inherit = 'nodo.draw.design'

    def sheet_price_choices(self):
        self._check_read()
        return self.env['nodo.cost.sheet.price'].search_read([('company_id', '=', self.company_id.id)],
            ['category', 'grade', 'supply_condition', 'thickness_mm', 'price_per_kg', 'basis', 'display_name'])

    def current_sheet_costs(self, usage_id):
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
        return self.env['nodo.cost.sheet.price']._sheet_costs(self.company_id, rows)
