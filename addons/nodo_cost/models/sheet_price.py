from decimal import Decimal, ROUND_HALF_UP

from odoo import api, fields, models
from odoo.exceptions import AccessError

from ..materials import CATEGORIES, stock_key


class SheetPrice(models.Model):
    _name = 'nodo.cost.sheet.price'
    _description = '板料成本'
    _order = 'category, thickness_mm, grade, supply_condition, id'

    company_id = fields.Many2one('res.company', string='公司', required=True, index=True,
                                 default=lambda self: self.env.company)
    category = fields.Selection(CATEGORIES, string='板材类别', required=True)
    grade = fields.Char(string='牌号', size=120)
    supply_condition = fields.Char(string='来料状态或镀层', size=120)
    thickness_mm = fields.Float(string='板厚（mm）', digits=(8, 3), required=True)
    price_per_kg = fields.Float(string='单价（元/kg）', digits=(14, 4), required=True)
    basis = fields.Selection([('trial', '测试价'), ('business', '业务价')], string='价格性质',
                             required=True, default='trial')
    source_note = fields.Char(string='价格依据')
    active = fields.Boolean(string='启用', default=True)

    _positive_gauge = models.Constraint("CHECK(thickness_mm > 0 AND thickness_mm < 'Infinity'::numeric)", '板厚须大于零。')
    _positive_price = models.Constraint("CHECK(price_per_kg > 0 AND price_per_kg < 'Infinity'::numeric)", '每公斤板料单价须大于零。')
    _unique_stock = models.UniqueIndex(
        "(company_id, category, thickness_mm, lower(trim(coalesce(grade, ''))), "
        "lower(trim(coalesce(supply_condition, '')))) WHERE active",
        '本公司已有这条板料规格的有效价格，请在原记录中改价。',
    )

    @api.depends('category', 'grade', 'supply_condition', 'thickness_mm')
    def _compute_display_name(self):
        names = dict(CATEGORIES)
        for record in self:
            record.display_name = ' · '.join(filter(None, [names.get(record.category), record.grade,
                record.supply_condition, f'{record.thickness_mm:g} mm']))

    def _notify_workbenches(self):
        # The inherited role channels carry only an invalidation. Prices are read under the user's company rules.
        roles = self.env.ref('nodo_base.group_role_engineering') | self.env.ref('base.group_system')
        roles._bus_send('nodo.cost/sheet_prices_changed', {})

    @api.model_create_multi
    def create(self, vals_list):
        # Release the unique active specification when an archive and its replacement share a transaction.
        self.flush_model(['active', 'company_id', 'category', 'thickness_mm', 'grade', 'supply_condition'])
        records = super().create(vals_list)
        records._notify_workbenches()
        return records

    def write(self, vals):
        if 'company_id' in vals and not self.env.su and vals['company_id'] not in self.env.companies.ids:
            raise AccessError('只能在获授权的公司内维护板料成本。')
        result = super().write(vals)
        self._notify_workbenches()
        return result

    def unlink(self):
        result = super().unlink()
        self._notify_workbenches()
        return result

    def _rates_for(self, company, items):
        prices = self.search([('company_id', '=', company.id), ('category', 'in', list({k[0] for k in items})),
                              ('thickness_mm', 'in', list({k[3] for k in items}))])
        return {stock_key(p.category, p.grade, p.supply_condition, p.thickness_mm): p for p in prices}

    def _sheet_costs(self, company, rows):
        rates = self._rates_for(company, [row['stock'] for row in rows])
        lines = {}
        raw_total = Decimal(0)
        missing = trial = 0
        for row in rows:
            rate = rates.get(row['stock'])
            if not rate:
                lines[row['key']] = None
                missing += 1
                continue
            amount = Decimal(str(row['weight'])) * Decimal(str(rate.price_per_kg))
            raw_total += amount
            trial += int(rate.basis == 'trial')
            lines[row['key']] = dict(unit=rate.price_per_kg, basis=rate.basis,
                                     amount=float(amount.quantize(Decimal('.001'), rounding=ROUND_HALF_UP)))
        total = None if missing else float(raw_total.quantize(Decimal('.01'), rounding=ROUND_HALF_UP))
        return dict(lines=lines, total=total, missing=missing, trial=trial)
