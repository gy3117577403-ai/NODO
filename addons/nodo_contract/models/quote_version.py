from odoo import fields, models

from .workflow import COST_GROUPS


class QuoteVersion(models.Model):
    _name = 'nodo.contract.quote.version'
    _description = '单柜报价版本'
    _order = 'order_id, number desc'
    _rec_name = 'name'
    _check_company_auto = True

    order_id = fields.Many2one('sale.order', string='报价', required=True, ondelete='restrict', index=True, check_company=True)
    company_id = fields.Many2one(related='order_id.company_id', store=True, index=True)
    number = fields.Integer(string='版本号', required=True)
    name = fields.Char(string='版本', required=True)
    fingerprint = fields.Char(required=True, groups=COST_GROUPS)
    calculated_by = fields.Many2one('res.users', string='核算员', required=True)
    approved_by = fields.Many2one('res.users', string='批准人')
    approved_at = fields.Datetime(string='批准时间')
    sent_by = fields.Many2one('res.users', string='发出登记人')
    sent_at = fields.Datetime(string='发出时间')
    accepted_by = fields.Many2one('res.users', string='客户确认登记人')
    accepted_at = fields.Datetime(string='客户确认时间')
    acceptance_note = fields.Text(string='客户确认依据')
    customer_document = fields.Json(string='对客快照', required=True, groups=COST_GROUPS)
    pricing_data = fields.Json(string='原计价快照', groups=COST_GROUPS, required=True)
    cost_summary = fields.Html(string='原报价与成本', sanitize=True, groups=COST_GROUPS)

    _unique_order_number = models.Constraint('UNIQUE(order_id, number)', '此报价的版本号已经存在。')
