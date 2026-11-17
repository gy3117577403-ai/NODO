from odoo import api, models
from odoo.fields import Domain


class NodoPurchaseAnalysisGuard(models.AbstractModel):
    _name = 'nodo.purchase.analysis.guard'
    _description = '采购金额汇总权限'

    @api.model
    def _access_domain(self, operation):
        if not self.env.su and self.env.user._is_internal():
            user = self.env.user
            # These SQL views include amounts independently of the order fields.
            if not user._nodo_purchase_companywide() or not user._nodo_purchase_permission_values()['price']:
                return Domain.FALSE
        return super()._access_domain(operation)


class PurchaseReport(models.Model):
    _name = 'purchase.report'
    _inherit = ['purchase.report', 'nodo.purchase.analysis.guard']


class PurchaseBillUnion(models.Model):
    _name = 'purchase.bill.union'
    _inherit = ['purchase.bill.union', 'nodo.purchase.analysis.guard']


class PurchaseBillLineMatch(models.Model):
    _name = 'purchase.bill.line.match'
    _inherit = ['purchase.bill.line.match', 'nodo.purchase.analysis.guard']


class IrActionsReport(models.Model):
    _inherit = 'ir.actions.report'

    def _nodo_check_purchase_report(self, report_ref, docids):
        if self.env.user._is_internal() and self._get_report(report_ref).model == 'purchase.order':
            orders = self.env['purchase.order'].sudo(False).browse(docids)
            orders._nodo_require_purchase_action('price', '你没有查看采购价格的权限，无法打印包含金额的单据。')

    def _render_qweb_pdf_prepare_streams(self, report_ref, data, res_ids=None):
        self._nodo_check_purchase_report(report_ref, res_ids)
        return super()._render_qweb_pdf_prepare_streams(report_ref, data, res_ids=res_ids)

    def _render_qweb_html(self, report_ref, docids, data=None):
        self._nodo_check_purchase_report(report_ref, docids)
        return super()._render_qweb_html(report_ref, docids, data=data)
