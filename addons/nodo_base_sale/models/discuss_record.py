from odoo import api, models


class DiscussRecord(models.AbstractModel):
    _inherit = 'nodo.discuss.record'

    @api.model
    def _nodo_card_models(self):
        return {**super()._nodo_card_models(), 'sale.order': self.env._('报价单和销售订单')}
