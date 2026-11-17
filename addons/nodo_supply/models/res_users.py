from odoo import api, fields, models
from odoo.exceptions import AccessError


PERMISSION_MODES = [('inherit', '岗位默认'), ('allow', '能'), ('deny', '否')]
PERMISSION_LABELS = {
    'view': '查看采购基础信息',
    'price': '查看采购价格',
    'draft': '录入采购草稿',
    'review': '技术核对',
    'confirm': '确认采购单',
}
PERMISSION_FIELDS = {f'nodo_purchase_{key}': key for key in PERMISSION_LABELS}


def purchase_permission(key):
    return fields.Selection(
        PERMISSION_MODES, string=PERMISSION_LABELS[key], default='inherit',
        required=True, groups='base.group_system', copy=False,
    )


class ResUsers(models.Model):
    _inherit = 'res.users'

    nodo_purchase_view = purchase_permission('view')
    nodo_purchase_price = purchase_permission('price')
    nodo_purchase_draft = purchase_permission('draft')
    nodo_purchase_review = purchase_permission('review')
    nodo_purchase_confirm = purchase_permission('confirm')
    nodo_purchase_view_status = fields.Char(compute='_compute_nodo_purchase_status', groups='base.group_system')
    nodo_purchase_price_status = fields.Char(compute='_compute_nodo_purchase_status', groups='base.group_system')
    nodo_purchase_draft_status = fields.Char(compute='_compute_nodo_purchase_status', groups='base.group_system')
    nodo_purchase_review_status = fields.Char(compute='_compute_nodo_purchase_status', groups='base.group_system')
    nodo_purchase_confirm_status = fields.Char(compute='_compute_nodo_purchase_status', groups='base.group_system')
    nodo_permission_change_ids = fields.One2many(
        'nodo.user.permission.change', 'user_id', string='权限变更记录', groups='base.group_system',
    )

    def _nodo_purchase_companywide(self):
        self.ensure_one()
        user = self.sudo()
        return user._is_system() or user.has_group('nodo_supply.group_purchase_manager') or user.has_group(
            'nodo_supply.group_purchase_buyer',
        )

    def _nodo_purchase_permission_values(self):
        self.ensure_one()
        user = self.sudo()
        if not user._is_internal():
            return dict.fromkeys(PERMISSION_LABELS, False)
        buyer = user._nodo_purchase_companywide()
        assistant = user.has_group('nodo_supply.group_purchase_assistant')
        engineer = user.has_group('nodo_base.group_role_engineering')
        defaults = {
            'view': buyer or assistant or engineer,
            'price': buyer or assistant or engineer,
            'draft': buyer or assistant,
            'review': engineer or user._is_system(),
            'confirm': buyer,
        }
        values = {}
        for field_name, key in PERMISSION_FIELDS.items():
            mode = user[field_name]
            values[key] = defaults[key] if mode == 'inherit' else mode == 'allow'
        if not values['view']:
            return dict.fromkeys(values, False)
        return values

    def _nodo_purchase_keeps_native_admin_form(self):
        self.ensure_one()
        return self._is_system() and all(self.sudo()[field_name] == 'inherit' for field_name in PERMISSION_FIELDS)

    @api.depends('group_ids', *PERMISSION_FIELDS)
    def _compute_nodo_purchase_status(self):
        for user in self:
            values = user._nodo_purchase_permission_values()
            for field_name, key in PERMISSION_FIELDS.items():
                if not user._is_internal():
                    source = '仅适用于内部员工'
                elif key != 'view' and not values['view']:
                    source = '基础查看已关闭'
                else:
                    source = '岗位默认' if user[field_name] == 'inherit' else '个人设置'
                user[f'{field_name}_status'] = f"{'能' if values[key] else '否'} · {source}"

    def _nodo_check_permission_manager(self):
        if not (self.env.user._is_system() or self.env.user._is_superuser()):
            raise AccessError('只有系统管理员可以修改员工个人权限。')

    @api.model_create_multi
    def create(self, vals_list):
        if any(PERMISSION_FIELDS.keys() & values.keys() for values in vals_list):
            self._nodo_check_permission_manager()
        users = super().create(vals_list)
        for user in users.sudo():
            for field_name in PERMISSION_FIELDS:
                user._nodo_log_permission_change(field_name, 'inherit')
        return users

    def write(self, vals):
        changed_fields = PERMISSION_FIELDS.keys() & vals.keys()
        if not changed_fields:
            return super().write(vals)
        self._nodo_check_permission_manager()
        before = {
            (user.id, field_name): user[field_name]
            for user in self.sudo() for field_name in changed_fields
        }
        result = super().write(vals)
        for user in self.sudo():
            for field_name in changed_fields:
                user._nodo_log_permission_change(field_name, before[user.id, field_name])
        self.env.transaction.invalidate_access_cache()
        if 'nodo_purchase_view' in changed_fields:
            self.env.transaction.invalidate_ormcache()
        return result

    def _nodo_log_permission_change(self, field_name, before):
        self.ensure_one()
        after = self[field_name]
        if before != after:
            self.env['nodo.user.permission.change'].sudo().create({
                'company_id': self.company_id.id,
                'user_id': self.id,
                'permission_name': PERMISSION_LABELS[PERMISSION_FIELDS[field_name]],
                'old_mode': before,
                'new_mode': after,
            })


class NodoUserPermissionChange(models.Model):
    _name = 'nodo.user.permission.change'
    _description = '员工个人权限变更'
    _order = 'id desc'
    _rec_name = 'permission_name'

    company_id = fields.Many2one('res.company', required=True, index=True)
    user_id = fields.Many2one('res.users', string='员工', index=True, ondelete='set null')
    permission_name = fields.Char(string='权限项目', required=True)
    old_mode = fields.Selection(PERMISSION_MODES, string='调整前', required=True)
    new_mode = fields.Selection(PERMISSION_MODES, string='调整后', required=True)
