import base64
import hashlib

from markupsafe import escape

from odoo import api, models
from odoo.addons.mail.tools.discuss import Store
from odoo.exceptions import AccessError
from odoo.fields import Domain
from odoo.tools import BinaryBytes

# 自动生成头像的底色：品牌绿色系，保证白字清晰（对比度均 ≥ 4.5:1）
NODO_AVATAR_COLORS = ['#1F4F46', '#2F6F62', '#3B6E8F', '#5A5F8F', '#7A5C3E', '#3E6B4F', '#6B4E71', '#4A5D63']
GENERATED_AVATAR_MARK = b'font-size="96" text-anchor="middle"'
CHAT_ROLE_KEYS = ('sales', 'costing', 'approval', 'engineering', 'purchase', 'production', 'operator', 'quality')
CHAT_PEOPLE_LIMIT = 15


def nodo_avatar_color(seed):
    """按种子（姓名、频道编号等）固定取一个 NODO 色板颜色。"""
    digest = hashlib.sha256(str(seed or '').encode('utf-8')).digest()
    return NODO_AVATAR_COLORS[digest[0] % len(NODO_AVATAR_COLORS)]


def nodo_text_avatar_svg(text, seed):
    initial = escape((text or '')[:1].upper())
    return BinaryBytes((
        '<?xml version="1.0" encoding="UTF-8" ?>'
        '<svg height="180" width="180" xmlns="http://www.w3.org/2000/svg">'
        f'<rect fill="{nodo_avatar_color(seed)}" height="180" width="180"/>'
        f'<text fill="#ffffff" font-size="96" text-anchor="middle" x="90" y="125" font-family="sans-serif">{initial}</text>'
        '</svg>'
    ).encode(), filename='avatar.svg')


class ResPartner(models.Model):
    _inherit = 'res.partner'

    @api.model
    def _nodo_chat_roles(self):
        group_ids = [self.env.ref(f'nodo_base.group_role_{key}').id for key in CHAT_ROLE_KEYS]
        # sudo: only read the public-facing labels of the eight known NODO role groups.
        groups = self.env['res.groups'].sudo().browse(group_ids)
        return {
            key: (group.id, group.privilege_id.name)
            for key, group in zip(CHAT_ROLE_KEYS, groups)
        }

    def _store_partner_fields(self, res: Store.FieldList):
        super()._store_partner_fields(res)
        res.from_method('_store_nodo_chat_roles_fields', internal=True)

    def _store_nodo_chat_roles_fields(self, res: Store.FieldList):
        roles = self._nodo_chat_roles()
        bot_id = self.env.ref('base.partner_root').id
        # sudo: group membership is read only for the partners already selected for this Store.
        internal_users = self.sudo().user_ids.filtered(lambda user: user.active and not user.share)

        def role_names(partner):
            users = partner.sudo().user_ids & internal_users
            if not users or partner.id == bot_id:
                return None
            group_ids = set(users.all_group_ids.ids)
            return [label for group_id, label in roles.values() if group_id in group_ids]

        res.attr('nodo_chat_roles', role_names)

    def _store_nodo_chat_invite_fields(self, res: Store.FieldList):
        res.extend(['active', 'name', 'partner_share'])
        res.from_method('_store_avatar_fields')
        res.from_method('_store_im_status_fields', internal=True)
        # sudo: Discuss uses the main user of each selectable partner to create a group chat.
        res.one('main_user_id', '_store_main_user_fields', sudo=True)
        res.from_method('_store_nodo_chat_roles_fields', internal=True)

    def _nodo_chat_people_domain(self, channel):
        return (
            self._get_channel_invite_domain(channel)
            & Domain('id', 'not in', [self.env.user.partner_id.id, self.env.ref('base.partner_root').id])
            & Domain('user_ids', 'any', Domain('active', '=', True) & Domain('share', '=', False))
        )

    @api.readonly
    @api.model
    def nodo_search_chat_people(self, search_term='', role='', channel_id=None):
        if not self.env.user._is_internal():
            raise AccessError('只有内部用户可以查找聊天成员。')

        channel = self.env['discuss.channel']
        if channel_id:
            channel = channel.search([
                ('id', '=', channel_id),
                ('channel_type', 'in', ['chat', 'group']),
                ('is_member', '=', True),
            ])
            if not channel:
                raise AccessError('你无法在这个对话中查找新成员。')

        roles = self._nodo_chat_roles()
        eligible_user = Domain('active', '=', True) & Domain('share', '=', False)
        domain = self._nodo_chat_people_domain(channel)
        if role:
            if role not in roles:
                domain = Domain.FALSE
            else:
                role_user = eligible_user & Domain('all_group_ids', 'in', [roles[role][0]])
                domain &= Domain('user_ids', 'any', role_user)

        term = (search_term or '').strip()
        if term:
            search_domain = Domain('name', 'ilike', term)
            matching_roles = [group_id for group_id, name in roles.values() if term.casefold() in name.casefold()]
            if matching_roles:
                role_user = eligible_user & Domain('all_group_ids', 'in', matching_roles)
                search_domain |= Domain('user_ids', 'any', role_user)
            domain &= search_domain

        partners = self.search(domain, limit=CHAT_PEOPLE_LIMIT + 1, order='name, id')
        page = partners[:CHAT_PEOPLE_LIMIT]
        return {
            'partner_ids': page.ids,
            'has_more': len(partners) > CHAT_PEOPLE_LIMIT,
            'role_options': [{'key': key, 'label': label} for key, (_, label) in roles.items()],
            'store_data': Store().add(page, '_store_nodo_chat_invite_fields'),
        }

    def _avatar_generate_svg(self):
        """按姓名首字生成头像，底色从 NODO 色板中按姓名固定取一个。"""
        name = self[self._avatar_name_field] or ''
        return nodo_text_avatar_svg(name, name)

    def _nodo_has_generated_avatar(self):
        """头像是否为系统按姓名自动生成的（而不是用户上传的图片）。"""
        self.ensure_one()
        raw = self.image_1920
        if not raw:
            return False
        # Odoo 20 的二进制字段值是附件对象，内容在 .content；兼容旧版本的 bytes / base64
        raw = getattr(raw, 'content', raw)
        if not raw:
            return False
        data = bytes(raw) if isinstance(raw, (bytes, bytearray)) else str(raw).encode()
        if not data.lstrip().startswith(b'<'):
            try:
                data = base64.b64decode(data)
            except ValueError:
                return False
        return data.lstrip().startswith(b'<?xml') and GENERATED_AVATAR_MARK in data

    def write(self, vals):
        # 改名后，自动生成的头像跟着换首字（清空后由系统按新名字即时生成）；用户上传的头像不动。
        if 'name' in vals and 'image_1920' not in vals:
            generated = self.filtered(lambda p: p._nodo_has_generated_avatar())
            res = super().write(vals)
            if generated:
                super(ResPartner, generated).write({'image_1920': False})
            return res
        return super().write(vals)
