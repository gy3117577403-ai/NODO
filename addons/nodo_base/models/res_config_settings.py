from odoo import models


class ResConfigSettings(models.TransientModel):
    _inherit = 'res.config.settings'

    def _get_view(self, view_id=None, view_type='form', **options):
        """隐藏设置页里的企业版推广项（upgrade_boolean 字段所在的整行设置）。

        只加 invisible，不删除节点，避免其他修饰符引用到的字段缺失。
        """
        arch, view = super()._get_view(view_id, view_type, **options)
        if view_type == 'form':
            for field in arch.iter('field'):
                if field.get('widget') != 'upgrade_boolean':
                    continue
                setting = next(field.iterancestors('setting'), None)
                (setting if setting is not None else field).set('invisible', '1')
        return arch, view
