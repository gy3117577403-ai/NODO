from odoo import api, fields, models
from odoo.exceptions import AccessError, ValidationError


UNITS = [('piece', '件'), ('set', '套'), ('metre', '米')]
VARIANTS = [('common', '通用'), ('steel', '普钢配置'), ('stainless', '不锈钢配置')]
KINDS = [('any', '单门和双门'), ('single', '单开门'), ('double', '双开门')]
PRICE_TOPIC = 'nodo.cost/auxiliary_prices_changed'


class AuxiliaryPrice(models.Model):
    _name = 'nodo.cost.auxiliary.price'
    _description = '辅材单价'
    _order = 'name, code, variant, id'

    company_id = fields.Many2one('res.company', string='公司', required=True, index=True,
                                 default=lambda self: self.env.company)
    code = fields.Char(string='物料编码', required=True, size=100, index=True)
    name = fields.Char(string='物料名称', required=True, size=120)
    variant = fields.Selection(VARIANTS, string='配置规格', required=True, default='common')
    scope = fields.Selection(KINDS, string='适用柜型', required=True, default='any')
    unit = fields.Selection(UNITS, string='计价单位', required=True, default='piece')
    price_per_unit = fields.Float(string='辅材单价（元）', digits=(14, 4), required=True, default=0)
    basis = fields.Selection([('reference', '参考价'), ('business', '业务价')], string='价格性质',
                             required=True, default='reference')
    source_note = fields.Char(string='价格依据', size=240)
    selectable = fields.Boolean(string='允许自选', default=True)
    active = fields.Boolean(string='启用', default=True)

    _unique_item = models.Constraint('UNIQUE(company_id,code,variant)', '该公司已有此物料及规格，请维护原记录。')
    _valid_price = models.Constraint("CHECK(price_per_unit >= 0 AND price_per_unit < 'Infinity'::numeric)",
                                     '辅材单价须为有限的非负金额。')

    def _notify_workbenches(self):
        roles = self.env.ref('nodo_base.group_role_engineering') | self.env.ref('base.group_system')
        roles._bus_send(PRICE_TOPIC, {})

    @api.model_create_multi
    def create(self, vals_list):
        vals_list = [dict(vals, code=(vals.get('code') or '').strip().upper()) for vals in vals_list]
        if any(not vals['code'] for vals in vals_list):
            raise ValidationError('请填写辅材物料编码。')
        if not self.env.su and any(vals.get('company_id', self.env.company.id) not in self.env.companies.ids
                                   for vals in vals_list):
            raise AccessError('只能在获授权的公司维护辅材单价。')
        records = super().create(vals_list)
        records._notify_workbenches()
        return records

    def write(self, vals):
        # Saved selections refer to the purchasing identity and its quantity unit.
        self.check_access('write')
        vals = dict(vals)
        if 'code' in vals:
            vals['code'] = (vals['code'] or '').strip().upper()
        identity = {'code', 'company_id', 'variant', 'unit'} & vals.keys()
        for item in self:
            for field in identity:
                old = item.company_id.id if field == 'company_id' else item[field]
                if vals[field] != old:
                    raise ValidationError('已建档物料的采购标识固定。规格或单位变化时，请为新规格登记独立编码。')
        result = super().write(vals)
        self._notify_workbenches()
        return result
