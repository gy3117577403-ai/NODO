import hashlib
import json

from markupsafe import Markup

from odoo import Command, api, fields, models
from odoo.exceptions import AccessError, UserError, ValidationError
from odoo.fields import Domain

from ..services.quote_price import OriginalPricing, SETTINGS, checked_number
from .workflow import (
    APPROVAL, COSTING, COST_GROUPS, OUTPUT_STAGES, SALES, has_role, internal_change,
    require_role, workflow_change,
)


STAGES = [
    ('selection', '待选型'), ('costing', '待核算'), ('approval', '待批准'),
    ('approved', '已批准'), ('sent', '已发出'), ('accepted', '合同'), ('sale', '销售订单'),
]
COST_FIELDS = set(SETTINGS.values()) | {'nodo_cost_line_ids'}
HEADER_FIELDS = {
    'partner_id', 'partner_invoice_id', 'partner_shipping_id', 'client_order_ref',
    'commitment_date', 'validity_date', 'date_order', 'pricelist_id',
    'currency_id', 'payment_term_id', 'note', 'fiscal_position_id', 'document_tax_mode',
    'order_line', 'nodo_selection_ids', 'nodo_drawing_ids', 'team_id', 'warehouse_id',
}
CLIENT_FIELDS = HEADER_FIELDS | COST_FIELDS | {'nodo_acceptance_note', 'message_main_attachment_id'}
COST_TOTAL_FIELDS = {'margin', 'margin_percent'}


class SaleOrder(models.Model):
    _inherit = 'sale.order'

    nodo_contract = fields.Boolean(string='NODO 报价', index=True, copy=False)
    nodo_quote_stage = fields.Selection(STAGES, string='报价阶段', default='selection', index=True, copy=False, readonly=True)
    nodo_selection_ids = fields.One2many('sale.order.line', 'order_id', string='单柜选型', copy=False)
    nodo_cost_line_ids = fields.One2many('sale.order.line', 'order_id', string='报价参数', groups=COST_GROUPS, copy=False)
    nodo_drawing_ids = fields.Many2many(
        'ir.attachment', 'nodo_contract_order_drawing_rel', 'order_id', 'attachment_id', string='报价图纸', copy=False,
    )
    nodo_active_version_id = fields.Many2one(
        'nodo.contract.quote.version', string='当前核算版本', groups=COST_GROUPS, check_company=True, copy=False,
    )
    nodo_quote_versions = fields.One2many(
        'nodo.contract.quote.version', 'order_id', string='核算与报价版本', groups=COST_GROUPS, copy=False,
    )
    nodo_version_number = fields.Integer(string='报价版本', copy=False, readonly=True)
    nodo_quote_ready = fields.Boolean(string='已核算', compute='_compute_nodo_quote_ready')
    nodo_can_edit_selection = fields.Boolean(compute='_compute_nodo_editable')
    nodo_can_edit_costs = fields.Boolean(compute='_compute_nodo_editable')
    nodo_can_record_acceptance = fields.Boolean(compute='_compute_nodo_editable')
    nodo_acceptance_note = fields.Text(string='客户确认凭据', copy=False)
    nodo_carbon_price = fields.Float(string='SECC 碳钢价（元/千克）', groups=COST_GROUPS, digits=(16, 4))
    nodo_galvanized_price = fields.Float(string='SGCC 镀锌板价（元/千克）', groups=COST_GROUPS, digits=(16, 4))
    nodo_stainless_304_price = fields.Float(string='SUS304 价格（元/千克）', groups=COST_GROUPS, digits=(16, 4))
    nodo_stainless_316_price = fields.Float(string='SUS316 价格（元/千克）', groups=COST_GROUPS, digits=(16, 4))
    nodo_waste_factor = fields.Float(string='废料系数', groups=COST_GROUPS, digits=(16, 4))

    @api.model
    def _access_domain(self, operation):
        domain = super()._access_domain(operation)
        if has_role(self.env, COSTING, APPROVAL):
            return domain
        scope = Domain('nodo_contract', '=', False)
        if has_role(self.env, SALES):
            scope |= Domain('user_id', '=', self.env.uid)
        return domain & scope

    @api.model
    def has_field_access(self, field, operation):
        if field.name in COST_TOTAL_FIELDS and has_role(self.env, SALES) and not has_role(self.env, COSTING, APPROVAL):
            return False
        return super().has_field_access(field, operation)

    @api.model
    def check_field_access(self, field, operation):
        if field.name in COST_TOTAL_FIELDS and not self.has_field_access(field, operation):
            raise AccessError('当前岗位无权查看成本与利润。')
        return super().check_field_access(field, operation)

    @api.depends_context('uid', 'lang')
    def _compute_extra_total_fields(self):
        hidden = self if has_role(self.env, SALES) and not has_role(self.env, COSTING, APPROVAL) else self.filtered('nodo_contract')
        super(SaleOrder, self - hidden)._compute_extra_total_fields()
        for order in hidden:
            order.extra_total_fields = []

    @api.depends('nodo_active_version_id')
    def _compute_nodo_quote_ready(self):
        for order in self:
            order.nodo_quote_ready = bool(order.sudo().nodo_active_version_id)

    @api.depends('nodo_quote_stage')
    @api.depends_context('uid')
    def _compute_nodo_editable(self):
        seller = has_role(self.env, SALES)
        costing = has_role(self.env, COSTING)
        for order in self:
            order.nodo_can_edit_selection = seller and order.nodo_quote_stage == 'selection'
            order.nodo_can_edit_costs = costing and order.nodo_quote_stage == 'costing'
            order.nodo_can_record_acceptance = seller and order.nodo_quote_stage == 'sent'

    @api.model_create_multi
    def create(self, vals_list):
        if not any(vals.get('nodo_contract', self.env.context.get('default_nodo_contract')) for vals in vals_list):
            return super().create(vals_list)
        require_role(self.env, SALES)
        allowed = HEADER_FIELDS | {'nodo_contract', 'user_id', 'company_id'}
        if any(vals.keys() - allowed
               for vals in vals_list if vals.get('nodo_contract', self.env.context.get('default_nodo_contract'))):
            raise AccessError('新建报价只能保存选型草稿。')
        records = self.browse()
        clean = self.with_context({k: v for k, v in self.env.context.items() if not k.startswith('default_')})
        for vals in vals_list:
            if not vals.get('nodo_contract', self.env.context.get('default_nodo_contract')):
                records += super().create(vals)
                continue
            company = vals.get('company_id') or clean.env.company.id
            if company not in self.env.companies.ids or (vals.get('user_id') and vals['user_id'] != self.env.uid):
                raise AccessError('只能在有权操作的公司创建本人的报价。')
            prepared = {**vals, 'nodo_contract': True, 'state': 'draft', 'user_id': self.env.uid,
                        'company_id': company, 'require_signature': False, 'prepayment_percent': 0}
            records += super(SaleOrder, clean).create(prepared).with_env(self.env)
        return records

    def write(self, vals):
        if internal_change():
            return super().write(vals)
        if 'nodo_contract' in vals:
            raise AccessError('报价归属由创建入口确定。')
        managed = self.filtered('nodo_contract')
        if not managed or not vals:
            return super().write(vals)
        managed.check_access('write')
        if vals.keys() - CLIENT_FIELDS:
            raise AccessError('请使用报价流程按钮修改阶段与版本。')
        if HEADER_FIELDS & vals.keys():
            managed._nodo_check_selection_edit()
        if COST_FIELDS & vals.keys():
            managed._nodo_check_cost_edit()
        if any(command[0] != Command.UPDATE or command[1] not in managed.order_line.ids
               for command in (vals.get('nodo_cost_line_ids') or [])):
            raise AccessError('核算只能修改原有选型行的系数和运费。')
        if 'nodo_acceptance_note' in vals:
            managed._nodo_lock()
            managed._nodo_check_stage(('sent',), SALES)
        result = super().write(vals)
        if COST_FIELDS & vals.keys():
            managed._nodo_clear_price()
        return result

    def _nodo_check_stage(self, stages, *roles):
        require_role(self.env, *roles)
        self.check_access('write')
        for order in self:
            if not order.nodo_contract or order.nodo_quote_stage not in stages:
                raise UserError('当前报价阶段不允许此操作。')
            if order.company_id not in self.env.companies:
                raise AccessError('你无权操作此报价所属公司。')

    def _nodo_check_selection_edit(self):
        if self and not internal_change():
            self._nodo_check_stage(('selection',), SALES)
            self._nodo_lock()
            self._nodo_check_stage(('selection',), SALES)

    def _nodo_check_cost_edit(self):
        if self and not internal_change():
            self._nodo_check_stage(('costing',), COSTING)
            self._nodo_lock()
            self._nodo_check_stage(('costing',), COSTING)

    def copy_data(self, default=None):
        if self.filtered('nodo_contract'):
            raise UserError('请新建单柜报价，重新核算和批准。')
        return super().copy_data(default=default)

    @api.constrains('nodo_drawing_ids')
    def _nodo_check_drawing_links(self):
        for order in self.filtered('nodo_contract'):
            if order.nodo_drawing_ids.filtered(
                lambda attachment: attachment.res_model != 'sale.order' or attachment.res_id != order.id
                or (attachment.company_id and attachment.company_id != order.company_id)
            ):
                raise ValidationError('只能关联从当前报价上传的图纸。')

    def _nodo_lock(self):
        if self:
            self.flush_recordset(['nodo_quote_stage'])
            self.env.cr.execute(
                'SELECT id FROM sale_order WHERE id IN %s ORDER BY id FOR UPDATE', [tuple(self.ids)],
            )
            self.invalidate_recordset(['nodo_quote_stage'], flush=False)

    def _nodo_write(self, vals):
        with workflow_change():
            return self.sudo().write(vals)

    def _nodo_clear_price(self):
        with workflow_change():
            orders = self.sudo()
            for order in orders.filtered('nodo_active_version_id'):
                order.order_line.filtered(lambda line: not line.display_type).write({
                    'price_unit': 0, 'technical_price_unit': 0, 'discount': 0,
                    'nodo_generated_remark': False,
                })
            orders.write({'nodo_active_version_id': False, 'nodo_version_number': 0})

    def _nodo_overrides(self):
        self.ensure_one()
        result = {}
        for key, name in SETTINGS.items():
            amount = self.sudo()[name]
            if amount and (not checked_number(amount) or amount <= 0):
                raise ValidationError('材料价格及废料系数须为正数。')
            if amount:
                result[key] = amount
        return result

    @api.constrains(*SETTINGS.values())
    def _check_nodo_overrides(self):
        for order in self.filtered('nodo_contract'):
            order._nodo_overrides()

    def _nodo_rows(self):
        self.ensure_one()
        products = self.order_line.filtered(lambda line: not line.display_type)
        if not products:
            raise ValidationError('请添加至少一条单柜产品明细。')
        if self.currency_id.name != 'CNY':
            raise ValidationError('原计价服务以人民币计价，请选择人民币价目表。')
        return [line._nodo_pricing_row() for line in products.sorted(lambda r: (r.sequence, r.id))]

    def _nodo_fingerprint(self):
        self.ensure_one()
        order = self.sudo().with_context(lang='zh_CN')
        rows = order._nodo_rows()
        for row in rows:
            # The rule calculation date is captured in the raw request. An
            # approved quote must remain reproducible on subsequent days.
            row.pop('date', None)
        payload = {
            'company': order.company_id.id, 'customer': order.partner_id.id,
            'currency': order.currency_id.id, 'pricelist': order.pricelist_id.id,
            'tax_mode': order.document_tax_mode, 'delivery': str(order.commitment_date or ''),
            'reference': order.client_order_ref or '', 'drawings': sorted(order.nodo_drawing_ids.ids),
            'validity': str(order.validity_date or ''), 'terms': order.payment_term_id.id,
            'note': str(order.note or ''), 'overrides': order._nodo_overrides(), 'rows': rows,
            'amounts': [(line.id, line.price_unit, line.discount, line.price_subtotal, line.price_total, sorted(line.tax_ids.ids))
                        for line in order.order_line.sorted('id') if not line.display_type],
        }
        return hashlib.sha256(json.dumps(payload, ensure_ascii=False, sort_keys=True, allow_nan=False).encode()).hexdigest()

    def _nodo_document(self, number):
        self.ensure_one()
        order = self.sudo().with_context(lang='zh_CN')
        lines = [line._nodo_customer_row() for line in order.order_line.sorted(lambda r: (r.sequence, r.id))
                 if not line.display_type]
        tax_included = order.document_tax_mode == 'tax_included'
        total = order.currency_id.round(sum(line['total'] for line in lines))
        if order.currency_id.compare_amounts(total, order.amount_total if tax_included else order.amount_untaxed):
            raise ValidationError('对客明细合计与订单金额不同，请核对税种和舍入规则后重新核算。')
        return {
            'number': order.name,
            'version': number, 'seller': order.company_id.name, 'buyer': order.partner_id.name,
            'date': fields.Datetime.context_timestamp(self, order.date_order).strftime('%Y-%m-%d'),
            'delivery': fields.Datetime.context_timestamp(self, order.commitment_date).strftime('%Y-%m-%d') if order.commitment_date else '',
            'currency': 'CNY', 'tax_included': tax_included,
            'payment_terms': order.payment_term_id.name or '',
            'lines': lines, 'total': total,
        }

    def _nodo_calculate(self, rows, overrides):
        key = f'nodo_contract.pricing.config.{self.company_id.id}'
        config_path = self.env['ir.config_parameter'].sudo().get_str(key)
        return OriginalPricing(config_path).calculate(rows, overrides)

    def action_nodo_submit_costing(self):
        self.ensure_one()
        self._nodo_check_stage(('selection',), SALES)
        self._nodo_lock()
        self._nodo_check_stage(('selection',), SALES)
        self._nodo_rows()
        self._nodo_write({'nodo_quote_stage': 'costing'})
        return True

    def action_nodo_calculate(self):
        self.ensure_one()
        self._nodo_check_stage(('costing',), COSTING)
        fingerprint = self._nodo_fingerprint()
        rows = self.with_context(lang='zh_CN')._nodo_rows()
        results = self._nodo_calculate(rows, self._nodo_overrides())
        self._nodo_lock()
        self._nodo_check_stage(('costing',), COSTING)
        if fingerprint != self._nodo_fingerprint() or set(results) != {row['line'] for row in rows}:
            raise ValidationError('选型或计价条件已经变化，请核对后重新计算。')
        if any(not checked_number(result.get('price_unit')) or result['price_unit'] <= 0
               or not result.get('response', {}).get('quote_line_id') for result in results.values()):
            raise ValidationError('原报价服务未返回完整有效的价格。')
        versions = self.env['nodo.contract.quote.version'].sudo()
        number = (versions.search([('order_id', '=', self.id)], order='number desc', limit=1).number or 0) + 1
        with workflow_change():
            for line in self.sudo().order_line.filtered(lambda item: item.id in results):
                result = results[line.id]
                price = result['price_unit']
                line.write({'price_unit': price, 'technical_price_unit': price, 'discount': 0,
                            'nodo_generated_remark': result.get('remark') or False})
        cost_groups = []
        for row in rows:
            values = results[row['line']]['item']['quote_cost_display']['values']
            detail = Markup('').join(Markup('<li>{}：{}</li>').format(label, val if val is not None else '—')
                                     for label, val in values.items())
            cost_groups.append(Markup('<h4>{}</h4><ul>{}</ul>').format(row['name'], detail))
        version = versions.create({
            'order_id': self.id, 'name': f'{self.name} / V{number}', 'number': number,
            'fingerprint': self._nodo_fingerprint(), 'calculated_by': self.env.uid,
            'customer_document': self._nodo_document(number),
            'pricing_data': {str(line_id): result for line_id, result in results.items()},
            'cost_summary': Markup('').join(cost_groups),
        })
        self._nodo_write({'nodo_active_version_id': version.id, 'nodo_version_number': number})
        return {'type': 'ir.actions.client', 'tag': 'display_notification',
                'params': {'type': 'success', 'message': '原报价计算完成，报价版本已保存。',
                           'next': {'type': 'ir.actions.client', 'tag': 'reload'}}}

    def _nodo_current_version(self, approved=False):
        self.ensure_one()
        version = self.sudo().nodo_active_version_id
        if not version or version.fingerprint != self._nodo_fingerprint() or (approved and not version.approved_at):
            raise UserError('当前单柜规格或金额缺少有效报价版本，请先核算并完成批准。')
        return version

    def action_nodo_submit_approval(self):
        self.ensure_one()
        self._nodo_check_stage(('costing',), SALES, COSTING)
        self._nodo_lock()
        self._nodo_check_stage(('costing',), SALES, COSTING)
        self._nodo_current_version()
        self._nodo_write({'nodo_quote_stage': 'approval'})
        return True

    def action_nodo_approve(self):
        self.ensure_one()
        self._nodo_check_stage(('approval',), APPROVAL)
        self._nodo_lock()
        self._nodo_check_stage(('approval',), APPROVAL)
        self._nodo_current_version().write({'approved_by': self.env.uid, 'approved_at': fields.Datetime.now()})
        self._nodo_write({'nodo_quote_stage': 'approved'})
        return True

    def action_nodo_return_selection(self):
        self.ensure_one()
        self.check_access('write')
        self._nodo_lock()
        roles = (SALES, COSTING, APPROVAL) if self.nodo_quote_stage == 'costing' else (APPROVAL,)
        self._nodo_check_stage(('costing', 'approval', 'approved', 'sent', 'accepted'), *roles)
        self._nodo_clear_price()
        self._nodo_write({'nodo_quote_stage': 'selection', 'state': 'draft', 'nodo_acceptance_note': False})
        return True

    def action_nodo_mark_sent(self):
        self.ensure_one()
        self._nodo_check_stage(('approved',), SALES)
        self._nodo_lock()
        self._nodo_check_stage(('approved',), SALES)
        version = self._nodo_current_version(approved=True)
        version.write({'sent_by': self.env.uid, 'sent_at': fields.Datetime.now()})
        self._nodo_write({'nodo_quote_stage': 'sent', 'state': 'sent'})
        return True

    def action_nodo_accept(self):
        self.ensure_one()
        self._nodo_check_stage(('sent',), SALES)
        self._nodo_lock()
        self._nodo_check_stage(('sent',), SALES)
        note = (self.nodo_acceptance_note or '').strip()
        if not note:
            raise ValidationError('请填写客户确认依据。')
        self._nodo_current_version(approved=True).write({
            'accepted_by': self.env.uid, 'accepted_at': fields.Datetime.now(), 'acceptance_note': note,
        })
        self._nodo_write({'nodo_quote_stage': 'accepted'})
        return True

    def action_confirm(self):
        managed = self.filtered('nodo_contract')
        if not managed:
            return super().action_confirm()
        managed._nodo_check_stage(('accepted',), APPROVAL)
        managed._nodo_lock()
        managed._nodo_check_stage(('accepted',), APPROVAL)
        for order in managed:
            if not order._nodo_current_version(approved=True).accepted_at:
                raise UserError('请先登记客户接受的报价版本。')
        standard = self - managed
        if standard:
            super(SaleOrder, standard).action_confirm()
        with workflow_change():
            result = super(SaleOrder, managed.with_context(send_email=False).sudo()).action_confirm()
            managed.sudo().write({'nodo_quote_stage': 'sale'})
        return result

    def _nodo_customer_document(self):
        self.ensure_one()
        self.check_access('read')
        require_role(self.env, SALES, COSTING, APPROVAL)
        if not self.nodo_contract or self.nodo_quote_stage not in OUTPUT_STAGES:
            raise UserError('请先批准报价，再生成对客文件。')
        return self._nodo_current_version(approved=True).customer_document

    def action_nodo_quote_pdf(self):
        self._nodo_customer_document()
        return self.env.ref('nodo_contract.action_customer_quote_pdf').report_action(self, config=False)

    def action_nodo_quote_excel(self):
        self._nodo_customer_document()
        return {'type': 'ir.actions.act_url', 'url': f'/nodo/contract/quotes/{self.id}/xlsx', 'target': 'download'}

    def action_nodo_open_quote(self):
        self.ensure_one()
        self.check_access('read')
        if not self.nodo_contract:
            raise UserError('请选择单柜报价。')
        return {
            'type': 'ir.actions.act_window', 'res_model': self._name, 'res_id': self.id,
            'views': [(self.env.ref('nodo_contract.nodo_quote_form').id, 'form')], 'target': 'current',
        }

    def action_quotation_send(self):
        if self.filtered('nodo_contract'):
            raise UserError('请下载已批准的客户报价，发送后在报价上登记。')
        return super().action_quotation_send()

    def action_quotation_sent(self):
        if self.filtered('nodo_contract'):
            raise UserError('请使用 NODO 报价的登记发送按钮。')
        return super().action_quotation_sent()

    def action_preview_sale_order(self):
        if self.filtered('nodo_contract'):
            raise UserError('请使用 NODO 报价的对客文件入口。')
        return super().action_preview_sale_order()

    def _portal_ensure_token(self):
        if self.filtered('nodo_contract'):
            raise UserError('NODO 单柜报价通过已批准的对客文件交付。')
        return super()._portal_ensure_token()

    def _nodo_check_native_report(self):
        self.ensure_one()
        if self.nodo_contract and self.nodo_quote_stage != 'sale':
            raise UserError('请使用已批准的 NODO 客户报价文件。')
        return True
