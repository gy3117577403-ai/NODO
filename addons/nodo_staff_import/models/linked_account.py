from odoo import api, models
from odoo.addons.base.models.res_users import check_identity
from odoo.exceptions import AccessError, LockError, ValidationError
from odoo.fields import Command


class HrEmployee(models.Model):
    _inherit = 'hr.employee'

    def _nodo_linked_user(self, user_id=None, *, operation='read'):
        self.ensure_one()
        if not self.env.user.has_group('base.group_system'):
            raise AccessError('只有系统管理员可以管理员工账号。')
        self.check_access('read')
        user = self.user_id
        if not user or (user_id is not None and user.id != user_id):
            raise ValidationError('该员工的关联用户已变化，请重新打开员工详情。')
        user.check_access(operation)
        return user

    def _nodo_linked_account_summary(self, user):
        return {
            'id': self.id,
            'name': self.name,
            'number': self.nodo_personnel_number or '',
            'department': self.department_id.complete_name or '',
            'state': 'active' if user.active else 'disabled',
            'status': '已开通' if user.active else '已停用',
        }

    def _nodo_business_privileges(self):
        return self.env['res.groups.privilege'].search([
            ('category_id', '=', self.env.ref('nodo_base.module_category_nodo_roles').id),
            ('group_ids', '!=', False),
        ], order='sequence, id')

    def _nodo_linked_role_data(self, user, privileges):
        direct = user.group_ids
        effective = user.all_group_ids
        return [{
            'id': privilege.id,
            'name': privilege.name,
            'choices': [{'id': group.id, 'name': group.name} for group in privilege.group_ids.sorted('sequence')],
            'direct': (privilege.group_ids & direct).ids,
            'inherited': (privilege.group_ids & (effective - direct)).mapped('name'),
        } for privilege in privileges]

    @api.readonly
    def nodo_linked_account_info(self):
        user = self._nodo_linked_user()
        can_edit_roles = user._is_internal()
        return {
            'employee': self._nodo_linked_account_summary(user),
            'userId': user.id,
            'login': user.login,
            'roles': self._nodo_linked_role_data(user, self._nodo_business_privileges()) if can_edit_roles else [],
            'canEditRoles': can_edit_roles,
            'multipleCompanies': len(user.company_ids) > 1,
        }

    def nodo_save_linked_roles(self, user_id, original, selected):
        user = self._nodo_linked_user(user_id, operation='write')
        if not user._is_internal():
            raise ValidationError('只有内部用户可以配置业务角色。')
        try:
            self.lock_for_update(allow_referencing=True)
            user.lock_for_update(allow_referencing=True)
        except LockError as error:
            raise ValidationError('员工账号正在更新，请稍后重试。') from error
        self.invalidate_recordset(['user_id'])
        self._nodo_linked_user(user_id, operation='write')
        user.invalidate_recordset(['group_ids'])

        privileges = self._nodo_business_privileges()
        allowed = set(privileges.group_ids.ids)
        for selection in (original, selected):
            if not isinstance(selection, list) or any(type(group_id) is not int for group_id in selection):
                raise ValidationError('请重新打开业务角色。')
            if set(selection) - allowed:
                raise ValidationError('请选择 NODO 业务角色。')
        current = set(user.group_ids.ids) & allowed
        if current != set(original):
            raise ValidationError('业务角色已被更新，请关闭后重新打开。')
        selected = set(selected)
        for privilege in privileges:
            options = set(privilege.group_ids.ids)
            chosen = options & selected
            if len(chosen) > 1 and chosen != options & current:
                raise ValidationError(f'「{privilege.name}」只能选择一项。')
        commands = [Command.unlink(group_id) for group_id in sorted(current - selected)]
        commands += [Command.link(group_id) for group_id in sorted(selected - current)]
        if commands:
            user.write({'group_ids': commands})
        return self._nodo_linked_role_data(user, privileges)

    @api.readonly
    def action_nodo_open_linked_user_settings(self, user_id):
        user = self._nodo_linked_user(user_id)
        return user.with_context(nodo_linked_employee_id=False, default_create_employee_id=self.id).get_record_default_action()

    def action_nodo_linked_password(self, user_id):
        user = self._nodo_linked_user(user_id, operation='write')
        action = self._nodo_linked_password_after_identity(user.id)
        if action['res_model'] == 'res.users.identitycheck':
            action['name'] = '验证管理员身份'
            action['views'] = [(self.env.ref('nodo_staff_import.staff_identitycheck_form').id, 'form')]
            action['context'] = {**action.get('context', {}), **self._nodo_linked_password_context(user)}
        return action

    def _nodo_linked_password_context(self, user):
        return {'nodo_account_summary': self._nodo_linked_account_summary(user), 'nodo_account_login': user.login}

    @check_identity
    def _nodo_linked_password_after_identity(self, user_id):
        user = self._nodo_linked_user(user_id, operation='write')
        context = self._nodo_linked_password_context(user)
        if user.id == self.env.uid:
            action = user.preference_change_password()
            action.update(name='修改密码', views=[(self.env.ref('nodo_staff_import.staff_change_own_password_form').id, 'form')],
                          context={**action.get('context', {}), **context})
            return action
        wizard = self.env['change.password.wizard'].with_context(active_model='res.users', active_ids=user.ids).create({})
        return {
            'type': 'ir.actions.act_window', 'name': '修改密码', 'target': 'new',
            'res_model': 'change.password.user', 'res_id': wizard.user_ids.id,
            'views': [(self.env.ref('nodo_staff_import.staff_change_member_password_form').id, 'form')],
            'context': context,
        }


class ResUsers(models.Model):
    _inherit = 'res.users'

    @api.readonly
    def get_record_default_action(self, access_uid=None):
        employee_id = self.env.context.get('nodo_linked_employee_id')
        if not employee_id or access_uid or not self.env.user.has_group('base.group_system'):
            return super().get_record_default_action(access_uid=access_uid)
        self.ensure_one()
        employee = self.env['hr.employee'].browse(employee_id)
        employee._nodo_linked_user(self.id)
        action = self.env['ir.actions.act_window']._for_xml_id('nodo_staff_import.staff_linked_account_action')
        action['res_id'] = employee.id
        return action
