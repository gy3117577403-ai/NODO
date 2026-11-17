from odoo import api, fields, models
from odoo.exceptions import AccessError, ValidationError
from odoo.fields import Domain


ORDER_DRAFT_FIELDS = frozenset({
    'partner_id', 'partner_ref', 'currency_id', 'date_order', 'date_planned',
    'order_line', 'note', 'nodo_technical_user_id',
})
REVIEW_RELEVANT_FIELDS = frozenset({'partner_id', 'date_planned', 'nodo_technical_user_id'})


def without_other_defaults(records, names):
    return records.with_context({
        key: value for key, value in records.env.context.items()
        if not key.startswith('default_') or key[8:] in names
    })


class PurchaseOrder(models.Model):
    _name = 'purchase.order'
    _inherit = ['purchase.order', 'nodo.purchase.price.guard']

    _nodo_price_fields = frozenset({'amount_total', 'amount_total_cc', 'amount_untaxed', 'amount_tax', 'tax_totals'})
    # Tracked values for this field must also pass the current viewer's field
    # permission. Suppress the standard open tracking summary in emails.
    amount_untaxed = fields.Monetary(groups='base.group_user,base.group_portal')

    nodo_technical_user_id = fields.Many2one(
        'res.users', string='负责技术人员', check_company=True, copy=False, index=True,
    )
    nodo_reviewed_by_id = fields.Many2one('res.users', string='核对人', readonly=True, copy=False, check_company=True)
    nodo_reviewed_at = fields.Datetime(string='核对时间', readonly=True, copy=False)
    nodo_can_edit_draft = fields.Boolean(compute='_compute_nodo_purchase_controls')
    nodo_can_assign_technical = fields.Boolean(compute='_compute_nodo_purchase_controls')
    nodo_can_review_specs = fields.Boolean(compute='_compute_nodo_purchase_controls')
    nodo_can_confirm_purchase = fields.Boolean(compute='_compute_nodo_purchase_controls')

    @api.model
    def _nodo_purchase_scope(self):
        user = self.env.user
        if user._nodo_purchase_companywide():
            return Domain.TRUE
        assistant = user.has_group('nodo_supply.group_purchase_assistant')
        engineer = user.has_group('nodo_base.group_role_engineering')
        own_drafts = Domain('create_uid', '=', user.id) & Domain('state', '=', 'draft')
        if assistant and not engineer:
            return own_drafts
        assigned = Domain('nodo_technical_user_id', '=', user.id)
        if assistant or user.sudo().nodo_purchase_draft == 'allow':
            return assigned | own_drafts
        return assigned

    @api.model
    def _access_domain(self, operation):
        domain = super()._access_domain(operation)
        if self.env.su or not self.env.user._is_internal():
            return domain
        user = self.env.user
        permissions = user._nodo_purchase_permission_values()
        if not permissions['view']:
            return Domain.FALSE
        if operation == 'read':
            return domain & self._nodo_purchase_scope()
        if operation in ('create', 'write') and permissions['draft']:
            if user._nodo_purchase_keeps_native_admin_form():
                return domain
            drafts = Domain('state', '=', 'draft')
            return domain & drafts if operation == 'create' else domain & drafts & self._nodo_purchase_scope()
        if operation == 'unlink' and user._nodo_purchase_keeps_native_admin_form():
            return domain
        return Domain.FALSE

    @api.model
    def _nodo_purchase_controlled(self):
        return not self.env.su and self.env.user._is_internal() and not self.env.user._nodo_purchase_keeps_native_admin_form()

    @api.model
    def _nodo_require_purchase_action(self, key, message):
        if not self.env.su and not self.env.user._nodo_purchase_permission_values()[key]:
            raise AccessError(message)
        if self:
            self.check_access('read')

    @api.depends('state', 'nodo_technical_user_id')
    @api.depends_context('uid')
    def _compute_nodo_purchase_controls(self):
        user = self.env.user
        permissions = user._nodo_purchase_permission_values()
        can_assign = user._nodo_purchase_companywide()
        for order in self:
            order.nodo_can_edit_draft = permissions['draft'] and order.state == 'draft'
            order.nodo_can_assign_technical = order.nodo_can_edit_draft and can_assign
            order.nodo_can_review_specs = (
                permissions['review'] and order.nodo_technical_user_id == user
                and order.state in ('draft', 'sent')
            )
            order.nodo_can_confirm_purchase = permissions['confirm'] and order.state in ('draft', 'sent', 'to approve')

    @api.constrains('nodo_technical_user_id', 'company_id')
    def _check_nodo_technical_user(self):
        for order in self.sudo():
            reviewer = order.nodo_technical_user_id
            if reviewer and (not reviewer._is_internal() or order.company_id not in reviewer.company_ids):
                raise ValidationError('负责技术人员必须是单据所属公司的内部员工。')

    @api.model_create_multi
    def create(self, vals_list):
        if not self._nodo_purchase_controlled():
            return super().create(vals_list)
        self._nodo_require_purchase_action('draft', '你没有录入采购草稿的权限。')
        assigning = self.env.user._nodo_purchase_companywide()
        allowed = ORDER_DRAFT_FIELDS | {'company_id'}
        records = without_other_defaults(self, allowed - {'nodo_technical_user_id'})
        prepared = []
        for vals in vals_list:
            if vals.keys() - allowed:
                raise AccessError('采购草稿只能填写供应商、交期、明细等录单信息。')
            if vals.get('nodo_technical_user_id') and not assigning:
                raise AccessError('你没有分配负责技术人员的权限。')
            company_id = vals.get('company_id') or records.default_get(['company_id'])['company_id']
            if company_id not in self.env.companies.ids:
                raise AccessError('你无权在该公司录入采购草稿。')
            prepared.append({**vals, 'company_id': company_id, 'state': 'draft'})
        return super(PurchaseOrder, records).create(prepared).with_env(self.env)

    def write(self, vals):
        if vals and self._nodo_purchase_controlled():
            self._nodo_require_purchase_action('draft', '你没有修改采购草稿的权限。')
            if vals.keys() - ORDER_DRAFT_FIELDS or any(order.state != 'draft' for order in self):
                raise AccessError('只能修改有权录入的草稿，请使用采购单上的业务操作按钮。')
            if 'nodo_technical_user_id' in vals and not self.env.user._nodo_purchase_companywide():
                raise AccessError('你没有分配负责技术人员的权限。')
        result = super().write(vals)
        if REVIEW_RELEVANT_FIELDS & vals.keys():
            self._nodo_clear_review()
        if {'state', 'company_id', 'nodo_technical_user_id'} & vals.keys():
            self.env.transaction.invalidate_access_cache('purchase.order')
            self.env.transaction.invalidate_access_cache('purchase.order.line')
        return result

    def _nodo_clear_review(self):
        reviewed_drafts = self.sudo().filtered(lambda order: order.state in ('draft', 'sent') and order.nodo_reviewed_at)
        if reviewed_drafts:
            reviewed_drafts.write({'nodo_reviewed_by_id': False, 'nodo_reviewed_at': False})

    def action_nodo_review_specs(self):
        self.ensure_one()
        self._nodo_require_purchase_action('review', '你没有技术核对权限。')
        if self.nodo_technical_user_id != self.env.user or self.state not in ('draft', 'sent'):
            raise AccessError('只有负责该单的技术人员可以核对待下单的采购单。')
        if not self.order_line.filtered('product_id'):
            raise ValidationError('请先填写采购明细，再核对规格。')
        self.sudo().write({'nodo_reviewed_by_id': self.env.uid, 'nodo_reviewed_at': fields.Datetime.now()})
        return True

    def button_confirm(self):
        if self.env.su:
            return super().button_confirm()
        self._nodo_require_purchase_action('confirm', '你没有最终确认采购单的权限。')
        return super(PurchaseOrder, self.sudo()).button_confirm()

    def button_approve(self, force=False):
        if self.env.su:
            return super().button_approve(force=force)
        self._nodo_require_purchase_action('confirm', '你没有最终确认采购单的权限。')
        # The trusted call from button_confirm uses the native one-step path.
        if any(order.state != 'to approve' for order in self):
            raise ValidationError('当前状态下无法确认采购单。')
        return super(PurchaseOrder, self.sudo()).button_approve(force=force)

    def _approval_allowed(self):
        user = self.env.user
        if (
            self.env.su and user._nodo_purchase_permission_values()['confirm']
            and not user._nodo_purchase_keeps_native_admin_form()
        ):
            # A NODO employee cleared by the server can confirm in one step.
            return True
        return super()._approval_allowed()

    @api.depends('name', 'partner_ref', 'amount_total')
    @api.depends_context('show_total_amount', 'uid')
    def _compute_display_name(self):
        if self.env.context.get('show_total_amount') and not self.has_field_access(self._fields['amount_total'], 'read'):
            for order in self:
                order.display_name = f'{order.name} ({order.partner_ref})' if order.partner_ref else order.name
            return
        super()._compute_display_name()

    def get_portal_url(self, *args, **kwargs):
        if self._nodo_purchase_controlled():
            raise AccessError('请使用站内单据链接与同事协作。')
        return super().get_portal_url(*args, **kwargs)

    @api.model
    def _get_view_cache_key(self, view_id=None, view_type='form', **options):
        key = super()._get_view_cache_key(view_id, view_type, **options)
        if view_type in ('form', 'list'):
            return (*key, self._nodo_purchase_controlled(), self.env.user._nodo_purchase_permission_values()['draft'],
                    self.has_field_access(self._fields['amount_total'], 'read'))
        return key

    @api.model
    def _get_view(self, view_id=None, view_type='form', **options):
        if not self._nodo_purchase_controlled() or view_type not in ('form', 'list'):
            return super()._get_view(view_id, view_type, **options)
        view = self.env.ref(f'nodo_supply.purchase_collaboration_{view_type}', raise_if_not_found=False)
        arch, record = super()._get_view(view.id if view else view_id, view_type, **options)
        if not self.env.user._nodo_purchase_permission_values()['draft']:
            arch.set('create', '0')
        if not self.has_field_access(self._fields['amount_total'], 'read'):
            for node in arch.xpath("//field[@name='amount_total' or @name='price_unit']"):
                node.getparent().remove(node)
        return arch, record
