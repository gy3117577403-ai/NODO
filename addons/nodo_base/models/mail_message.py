from odoo import api, models


class MailMessage(models.Model):
    _inherit = 'mail.message'

    @api.model_create_multi
    def create(self, vals_list):
        # Direct ORM creation, including default_* values, must obey the same posting rule as Discuss.
        missing = {field for vals in vals_list for field in ('model', 'res_id') if field not in vals}
        defaults = self.default_get(list(missing)) if missing else {}
        channel_ids = {
            int(res_id)
            for vals in vals_list
            if vals.get('model', defaults.get('model')) == 'discuss.channel'
            and (res_id := vals.get('res_id', defaults.get('res_id')))
        }
        self.env['discuss.channel'].browse(channel_ids)._nodo_check_channel_post_access()
        return super().create(vals_list)
