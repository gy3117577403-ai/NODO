from odoo import api, fields, models
from odoo.exceptions import UserError, ValidationError

from odoo.addons.nodo_draw.models.workbench import guard


class DrawAccessory(models.Model):
    _inherit = 'nodo.draw.accessory'
    _rec_names_search = ('code', 'name')

    @api.depends('code', 'name', 'version')
    def _compute_display_name(self):
        for item in self:
            item.display_name = f'{item.code} · {item.name} · V{item.version:02}'


class AuxiliaryPrice(models.Model):
    _inherit = 'nodo.cost.auxiliary.price'
    _check_company_auto = True

    cad_model_id = fields.Many2one(
        'nodo.draw.accessory', string='模型版本', groups='base.group_system',
        check_company=True, ondelete='restrict', domain=[('state', '!=', 'retired')], copy=False,
    )
    cad_model_label = fields.Char(string='关联型号', compute='_compute_cad_model_label', compute_sudo=True)
    cad_model_status = fields.Selection(
        [('unlinked', '待关联模型'), ('available', '已关联'),
         ('pending', '待工程核对'), ('retired', '模型已停用')],
        string='模型状态', compute='_compute_cad_model_status', store=True,
    )

    @api.depends('cad_model_id.display_name')
    def _compute_cad_model_label(self):
        for item in self:
            item.cad_model_label = item.cad_model_id.display_name if item.cad_model_id else False

    @api.depends('cad_model_id.state')
    def _compute_cad_model_status(self):
        for item in self:
            item.cad_model_status = item.cad_model_id.state or 'unlinked'

    @api.constrains('cad_model_id')
    def _check_cad_model_status(self):
        if any(item.sudo().cad_model_id.state == 'retired' for item in self):
            raise ValidationError('请选择尚未停用的模型版本。')

    def _read_linked_cad_model(self):
        self.ensure_one()
        guard(self.env)
        self.check_access('read')
        model = self.sudo().cad_model_id.with_env(self.env)
        if model:
            model.check_access('read')
        return model

    def auxiliary_model_preview(self):
        model = self._read_linked_cad_model()
        if not model:
            return {'status': 'unlinked'}
        if model.state == 'retired':
            return {'status': 'retired'}
        if model.company_id != self.env.company:
            return {'status': 'other_company'}
        card = model._card()
        return {'status': 'ready' if card['mesh'] else 'no_mesh', 'model': card}

    def action_open_cad_model(self):
        model = self._read_linked_cad_model()
        if not model or model.state == 'retired':
            raise UserError('当前辅料没有可查看的模型版本。')
        if model.company_id != self.env.company:
            raise UserError('请切换到此辅料所属公司后查看模型。')
        action = self.env['ir.actions.actions']._for_xml_id('nodo_draw.action_accessory_library')
        return dict(action, params={'modelId': model.id})
