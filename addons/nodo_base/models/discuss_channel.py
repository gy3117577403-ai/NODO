from odoo import models

from .res_partner import nodo_text_avatar_svg


class DiscussChannel(models.Model):
    _inherit = 'discuss.channel'

    def _generate_avatar(self):
        """频道和群聊的默认头像改用 NODO 色板加首字（上游是随机颜色）。上传了图片的不受影响。"""
        if self.channel_type == 'channel' or (
            self.channel_type == 'group' and self.default_display_mode != 'video_full_screen'
        ):
            return nodo_text_avatar_svg(self.display_name, f'{self.channel_type}-{self.id}')
        return super()._generate_avatar()
