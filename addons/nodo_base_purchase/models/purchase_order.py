from odoo import models
from odoo.tools.misc import format_amount


STATUS_TYPES = {
    'draft': 'warning',
    'sent': 'info',
    'to approve': 'warning',
    'purchase': 'success',
    'cancel': 'muted',
}


class PurchaseOrder(models.Model):
    _inherit = 'purchase.order'

    def _nodo_discuss_card(self):
        self.ensure_one()
        values = self.read(['name', 'partner_id', 'amount_total', 'currency_id', 'state'])[0]
        state = values['state']
        label = self.env._('采购询价单') if state in ('draft', 'sent') else self.env._('采购单')
        currency = self.env['res.currency'].browse(values['currency_id'][0])
        amount = format_amount(self.env, values['amount_total'], currency)
        return {
            'title': f"{label} {values['name']}",
            'subtitle': f"{values['partner_id'][1]} · {amount}",
            'status': dict(self._fields['state']._description_selection(self.env)).get(state, ''),
            'status_type': STATUS_TYPES.get(state, ''),
        }

    def action_nodo_share_to_chat(self):
        return self.env['nodo.discuss.record']._share_action(self)
