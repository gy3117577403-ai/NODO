from odoo import api, models


class DiscussRecord(models.AbstractModel):
    _inherit = 'nodo.discuss.record'

    @api.model
    def _nodo_card_models(self):
        return {
            **super()._nodo_card_models(),
            'purchase.order': self.env._('采购询价单和采购单'),
        }
