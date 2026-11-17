from odoo import models
from odoo.tools.misc import format_amount


STATUS_TYPES = {'draft': 'warning', 'sent': 'info', 'sale': 'success', 'cancel': 'muted'}


class SaleOrder(models.Model):
    _inherit = 'sale.order'

    def _nodo_discuss_card(self):
        self.ensure_one()
        values = self.read(['name', 'partner_id', 'amount_total', 'currency_id', 'state'])[0]
        state = values['state']
        label = self.env._('销售订单') if state == 'sale' else self.env._('报价单')
        currency = self.env['res.currency'].browse(values['currency_id'][0])
        amount = format_amount(self.env, values['amount_total'], currency)
        customer = values['partner_id'][1]
        return {
            'title': f"{label} {values['name']}",
            'subtitle': f'{customer} · {amount}',
            'status': dict(self._fields['state']._description_selection(self.env)).get(state, ''),
            'status_type': STATUS_TYPES.get(state, ''),
        }

    def action_nodo_share_to_chat(self):
        return self.env['nodo.discuss.record']._share_action(self)
