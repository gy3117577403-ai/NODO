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
        with_price = self.has_field_access(self._fields['amount_total'], 'read')
        field_names = ['name', 'partner_id', 'state']
        if with_price:
            field_names.extend(('amount_total', 'currency_id'))
        values = self.read(field_names)[0]
        state = values['state']
        label = self.env._('采购询价单') if state in ('draft', 'sent') else self.env._('采购单')
        subtitle = values['partner_id'][1]
        if with_price:
            currency = self.env['res.currency'].browse(values['currency_id'][0])
            subtitle = f"{subtitle} · {format_amount(self.env, values['amount_total'], currency)}"
        return {
            'title': f"{label} {values['name']}",
            'subtitle': subtitle,
            'status': dict(self._fields['state']._description_selection(self.env)).get(state, ''),
            'status_type': STATUS_TYPES.get(state, ''),
        }

    def action_nodo_share_to_chat(self):
        return self.env['nodo.discuss.record']._share_action(self)
