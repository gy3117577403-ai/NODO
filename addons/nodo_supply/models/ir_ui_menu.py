from odoo import api, models


class IrUiMenu(models.Model):
    _inherit = 'ir.ui.menu'

    @api.model
    def _visible_menu_ids(self, debug=False):
        visible = super()._visible_menu_ids(debug=debug)
        menus = {
            menu.id for xmlid in ('menu_supply_root', 'menu_purchase_collaboration')
            if (menu := self.env.ref(f'nodo_supply.{xmlid}', raise_if_not_found=False))
        }
        # The upstream cache groups employees with the same groups. A personal
        # switch can make these two menus differ even for identical groups.
        if self.env.user._is_internal() and self.env['purchase.order'].has_access('read'):
            return visible | menus
        return visible - menus
