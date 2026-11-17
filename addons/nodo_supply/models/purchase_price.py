from odoo import api, models
from odoo.exceptions import AccessError


class NodoPurchasePriceGuard(models.AbstractModel):
    _name = 'nodo.purchase.price.guard'
    _description = '采购价格字段权限'

    _nodo_price_fields = frozenset()

    @api.model
    def _nodo_check_employee_field(self, field):
        return (
            not self.env.su and self.env.user._is_internal()
            and (field.name in self._nodo_price_fields or field.name == 'access_token')
        )

    @api.model
    def has_field_access(self, field, operation):
        if self._nodo_check_employee_field(field):
            user = self.env.user
            if field.name == 'access_token':
                return user._nodo_purchase_keeps_native_admin_form()
            # Do not memoize a personal grant as unconditional field access.
            return user._nodo_purchase_permission_values()['price'] and self._has_field_access(field, operation)
        return super().has_field_access(field, operation)

    @api.model
    def check_field_access(self, field, operation):
        if self._nodo_check_employee_field(field):
            if not self.has_field_access(field, operation):
                raise AccessError('你没有查看或修改采购价格及相关资料的权限。')
            return
        return super().check_field_access(field, operation)
