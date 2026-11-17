from odoo import api, models
from odoo.exceptions import ValidationError


class IrAttachment(models.Model):
    _inherit = 'ir.attachment'

    def _nodo_check_discuss_size(self):
        if self:
            limit_mb = self.env['discuss.channel']._nodo_file_limit_mb()
            if any(attachment.file_size > limit_mb * 1024**2 for attachment in self.sudo()):
                raise ValidationError(f'单个文件不能超过 {limit_mb} MB。')

    @api.constrains('file_size', 'res_model', 'res_id')
    def _nodo_check_discuss_attachment(self):
        self.filtered_domain([('res_model', '=', 'discuss.channel')])._nodo_check_discuss_size()
