from odoo import models
from odoo.addons.mail.tools.discuss import Store
from odoo.exceptions import AccessError
from odoo.fields import Domain


class DiscussChannel(models.Model):
    _inherit = 'discuss.channel'

    def nodo_add_staff_members(self, partner_ids):
        self.ensure_one()
        people = self.env['res.partner']
        channel = people._nodo_staff_chat_channel(self.id)
        if channel.channel_type not in ('channel', 'group'):
            raise AccessError('请从频道或群聊添加成员。')

        # Recheck chosen accounts. Existing members are valid on a retry, but are not added twice.
        eligible_users = people._nodo_staff_chat_users(channel)
        partners = people.search(people._nodo_staff_chat_partners(eligible_users) & Domain('id', 'in', partner_ids))
        if set(partner_ids) != set(partners.ids):
            raise AccessError('部分同事已停用或不符合频道权限，请重新选择。')

        added = channel._add_members(partners=partners, post_joined_message=False)
        return {
            'added_count': len(added),
            'store_data': Store().add(channel, ['member_count']).add(added, '_store_member_fields'),
        }
