from decimal import Decimal, ROUND_HALF_UP

from odoo import api, fields, models
from odoo.exceptions import UserError


def raw_amount(row):
    return Decimal(str(row['weight'])) * Decimal(str(row['unit'])) if row else Decimal(0)


class SheetCostVersion(models.Model):
    _name = 'nodo.draw.sheet.cost.version'
    _description = '板料核算版本'
    _order = 'number desc'
    _rec_name = 'number'
    _check_company_auto = True

    design_id = fields.Many2one('nodo.draw.design', required=True, index=True, ondelete='restrict', check_company=True)
    company_id = fields.Many2one('res.company', required=True, index=True)
    number = fields.Integer(string='核算版次', required=True)
    fingerprint = fields.Char(required=True)
    payload = fields.Json(string='保存时的板料明细', required=True)
    _unique_number = models.Constraint('UNIQUE(design_id, number)', '该柜体的核算版次已存在。')

    def write(self, vals):
        raise UserError('已保存的板料核算版本只读。')

    @api.ondelete(at_uninstall=False)
    def _unlink_except_uninstall(self):
        raise UserError('已保存的板料核算版本须保留。')

    def _header(self):
        return dict(id=self.id, number=self.number, saved_at=fields.Datetime.to_string(self.create_date),
                    saved_by=self.create_uid.display_name)

    def _compare(self, previous):
        old = {r['key']: r for r in previous.payload['rows']}
        new = {r['key']: r for r in self.payload['rows']}
        changes = []
        for key in dict.fromkeys([*new, *old]):
            before, after = old.get(key), new.get(key)
            if before == after:
                continue
            delta = raw_amount(after) - raw_amount(before)
            changes.append(dict(key=key, name=(after or before)['name'], before=before, after=after,
                                delta=float(delta.quantize(Decimal('.001'), rounding=ROUND_HALF_UP))))
        difference = Decimal(str(self.payload['total'])) - Decimal(str(previous.payload['total']))
        return dict(number=previous.number, total=previous.payload['total'], delta=float(difference), lines=changes)
