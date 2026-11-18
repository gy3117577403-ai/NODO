from odoo import api, models
from odoo.addons.mail.tools.discuss import Store
from odoo.addons.nodo_base.models.res_partner import CHAT_PEOPLE_LIMIT
from odoo.exceptions import AccessError
from odoo.fields import Domain


class ResPartner(models.Model):
    _inherit = 'res.partner'

    def _nodo_staff_chat_channel(self, channel_id):
        if not self.env.user._is_internal():
            raise AccessError('只有内部用户可以查找讨论成员。')
        channels = self.env['discuss.channel']
        if not channel_id:
            return channels
        channel = channels.search([('id', '=', channel_id)], limit=1)
        if (
            not channel
            or channel.default_display_mode == 'video_full_screen'
            or (channel.channel_type != 'channel' and not channel.is_member)
        ):
            raise AccessError('你无法管理这个对话的成员。')
        return channel

    def _nodo_staff_chat_users(self, channel):
        domain = (
            Domain('active', '=', True)
            & Domain('share', '=', False)
            & Domain('company_ids', 'in', [self.env.company.id])
        )
        if channel.group_public_id:
            domain &= Domain('all_group_ids', 'in', channel.group_public_id.ids)
        return domain

    def _nodo_staff_chat_partners(self, users):
        excluded = self.env.user.partner_id | self.env.ref('base.partner_root')
        return (
            Domain('active', '=', True)
            & Domain('id', 'not in', excluded.ids)
            & Domain('user_ids', 'any', users)
        )

    def _nodo_staff_chat_employees(self, domain):
        # Only public employee records from the current company supply department metadata.
        return self.env['hr.employee.public'].search(
            Domain('active', '=', True) & Domain('company_id', '=', self.env.company.id) & domain,
            order='id',
        )

    @api.model
    @api.readonly
    def nodo_search_chat_people(self, search_term='', role='', channel_id=None, department_id=None):
        channel = self._nodo_staff_chat_channel(channel_id)
        users = self._nodo_staff_chat_users(channel)
        roles = self._nodo_chat_roles()
        departments = self.env['hr.department'].search([
            ('active', '=', True), ('company_id', 'in', [False, self.env.company.id]),
        ]).sorted(lambda dept: (dept.complete_name, dept.id))

        if role:
            users &= Domain('all_group_ids', 'in', [roles[role][0]]) if role in roles else Domain.FALSE
        if department_id:
            selection = Domain('department_id', 'child_of', department_id) if department_id in departments.ids else Domain.FALSE
            users &= Domain('id', 'in', self._nodo_staff_chat_employees(selection).user_id.ids)

        domain = self._nodo_staff_chat_partners(users)
        if channel:
            domain &= Domain('channel_ids', 'not in', channel.ids)
        term = (search_term or '').strip().casefold()
        if term:
            role_matches = [group_id for group_id, label in roles.values() if term in label.casefold()]
            dept_matches = departments.filtered(lambda dept: term in dept.complete_name.casefold())
            dept_users = self._nodo_staff_chat_employees(Domain('department_id', 'in', dept_matches.ids)).user_id
            matching_user = Domain('all_group_ids', 'in', role_matches) | Domain('id', 'in', dept_users.ids)
            domain &= Domain('name', 'ilike', term) | Domain('user_ids', 'any', users & matching_user)

        partners = self.search(domain, limit=CHAT_PEOPLE_LIMIT + 1, order='name, id')
        page = partners[:CHAT_PEOPLE_LIMIT]
        department_labels = {}
        for employee in self._nodo_staff_chat_employees(
            Domain('user_id.partner_id', 'in', page.ids) & Domain('department_id', '!=', False)
        ):
            department_labels.setdefault(employee.user_id.partner_id.id, employee.department_id.complete_name)

        store = Store().add(page, '_store_nodo_chat_invite_fields')
        store.add(page, lambda res: res.attr('nodo_chat_department', lambda partner: department_labels.get(partner.id, '')))
        return {
            'partner_ids': page.ids,
            'has_more': len(partners) > CHAT_PEOPLE_LIMIT,
            'role_options': [{'key': key, 'label': label} for key, (_, label) in roles.items()],
            'department_options': [{'id': dept.id, 'label': dept.complete_name} for dept in departments],
            'store_data': store,
        }
