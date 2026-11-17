from collections import defaultdict
from itertools import islice

from markupsafe import Markup

from odoo import api, models
from odoo.exceptions import AccessError, MissingError, UserError
from odoo.fields import Domain


CARD_BATCH_LIMIT = 50
TARGET_LIMIT = 20


class DiscussRecord(models.AbstractModel):
    _name = 'nodo.discuss.record'
    _description = 'NODO 聊天单据卡片'

    @api.model
    def _nodo_card_models(self):
        """Model names and picker labels contributed by installed modules."""
        return {}

    def _card_model(self, model_name):
        model = self.env.get(model_name) if isinstance(model_name, str) else None
        if model is not None and not model._abstract and not model.is_transient():
            return model.with_context(active_test=False)
        return None

    def _readable_card_records(self, model_name, ids):
        model = self._card_model(model_name)
        if model is None:
            return {}
        try:
            return {record.id: record for record in model.search([('id', 'in', ids)])}
        except AccessError:
            return {}

    @api.readonly
    @api.model
    def get_record_card_types(self):
        if not self.env.user._is_internal():
            return []
        types = []
        for model_name, label in self._nodo_card_models().items():
            model = self._card_model(model_name)
            if model is not None and model.has_access('read'):
                types.append({'model': model_name, 'label': label})
        return types

    @api.readonly
    @api.model
    def get_record_cards(self, references):
        if not self.env.user._is_internal() or not isinstance(references, (list, tuple)):
            return []
        by_model = defaultdict(list)
        ordered_refs = {}
        for reference in islice(references, CARD_BATCH_LIMIT):
            if not isinstance(reference, dict):
                continue
            model, record_id = reference.get('model'), reference.get('id')
            if not isinstance(model, str) or not self._valid_id(record_id) or (model, record_id) in ordered_refs:
                continue
            ordered_refs[model, record_id] = None
            by_model[model].append(record_id)

        declared = self._nodo_card_models()
        for model, ids in by_model.items():
            for record_id, record in self._readable_card_records(model, ids).items():
                try:
                    data = record._nodo_discuss_card() if model in declared else self._default_card(record)
                    ordered_refs[model, record_id] = {
                        'model': model, 'id': record_id, 'title': data['title'],
                        'subtitle': data.get('subtitle', ''), 'status': data.get('status', ''),
                        'status_type': data.get('status_type', ''),
                    }
                except (AccessError, MissingError):
                    # An inaccessible and a missing record have the same response.
                    continue
        return [card for card in ordered_refs.values() if card is not None]

    def _default_card(self, record):
        label = self.env['ir.model']._get(record._name).name or record._description
        values = record.read(['display_name'], load=None)[0]
        return {'title': f"{label} {values['display_name']}"}

    def _check_internal(self):
        if not self.env.user._is_internal():
            raise AccessError('只有内部用户可以分享单据。')

    @staticmethod
    def _valid_id(record_id):
        return type(record_id) is int and 0 < record_id < 2**31

    def _check_share_record(self, model, record_id):
        self._check_internal()
        if (
            not isinstance(model, str)
            or not self._valid_id(record_id)
            or model not in self._nodo_card_models()
            or not self._readable_card_records(model, [record_id])
        ):
            raise AccessError('单据不可访问，无法发到聊天。')

    def _share_action(self, record):
        record.ensure_one()
        self._check_share_record(record._name, record.id)
        return {
            'type': 'ir.actions.client',
            'tag': 'nodo_share_record',
            'params': {'model': record._name, 'id': record.id},
        }

    def _target_channel_domain(self, kind):
        return [
            ('active', '=', True),
            ('channel_type', '=', kind),
            ('is_member', '=', True),
            ('default_display_mode', '=', False),
        ]

    @api.readonly
    @api.model
    def search_share_targets(self, kind, search_term=''):
        self._check_internal()
        channels = self.env['discuss.channel']
        term = search_term.strip()[:120] if isinstance(search_term, str) else ''
        if kind == 'person':
            partners = self.env['res.partner']
            domain = partners._nodo_chat_people_domain(channels)
            return partners.search_read(
                domain & (Domain('name', 'ilike', term) if term else Domain.TRUE),
                ['name'], limit=TARGET_LIMIT, order='name, id',
            )
        if kind not in ('group', 'channel'):
            return []
        matches = channels.search(self._target_channel_domain(kind), order='name, id')
        if term:
            term = term.casefold()
            matches = matches.filtered(lambda channel: term in channel.display_name.casefold())
        blocked = matches._nodo_channels_disallowing_posts(self.env.user)
        writable = matches.filtered(
            lambda channel: channel not in blocked and channel.parent_channel_id not in blocked
            and (not channel.is_readonly or channel.can_self_edit_readonly_channel)
        )
        return [{'id': channel.id, 'name': channel.display_name} for channel in writable[:TARGET_LIMIT]]

    @api.model
    def share_record(self, model, record_id, kind, target_id, note=''):
        self._check_share_record(model, record_id)
        if not self._valid_id(target_id) or kind not in ('person', 'group', 'channel'):
            raise AccessError('你无法在此会话发言。')
        if not isinstance(note, str) or len(note) > 2000:
            raise UserError('附言最多可输入 2000 个字符。')

        channels = self.env['discuss.channel']
        if kind == 'person':
            partners = self.env['res.partner']
            partner = partners.search(partners._nodo_chat_people_domain(channels) & Domain('id', '=', target_id))
            if not partner:
                raise AccessError('此联系人不可用，无法发到聊天。')
            channel = channels._get_or_create_chat(partner.ids)
        else:
            channel = channels.search(self._target_channel_domain(kind) + [('id', '=', target_id)])
        if not channel:
            raise AccessError('你无法在此会话发言。')
        channel._nodo_check_channel_post_access()
        if channel.is_readonly and not channel.can_self_edit_readonly_channel:
            raise AccessError('此频道为只读，无法发言。')

        # Post a link alone so the message carries no record fields to other members.
        body = Markup('<p><a href="%s">%s</a></p>') % (f'/odoo/{model}/{record_id}', '查看单据')
        if note := note.strip():
            body = (Markup('<p>%s</p>') % note).replace('\n', Markup('<br/>')) + body
        message = channel.message_post(body=body, message_type='comment', subtype_xmlid='mail.mt_comment')
        return {'channel_id': channel.id, 'message_id': message.id}
