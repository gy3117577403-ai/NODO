from io import BytesIO

import xlsxwriter

from odoo import http
from odoo.exceptions import AccessError, MissingError
from odoo.http import request
from odoo.http.stream import content_disposition


HEADERS = ('序号', '名称', '规格型号（宽×深×高）', '数量', '单位', '折后单价', '折后总价', '备注')


def customer_workbook(document):
    buffer = BytesIO()
    with xlsxwriter.Workbook(buffer, {'in_memory': True}) as workbook:
        sheet = workbook.add_worksheet('报价单')
        text = workbook.add_format({'font_name': 'Microsoft YaHei', 'valign': 'top', 'text_wrap': True})
        title = workbook.add_format({'font_name': 'Microsoft YaHei', 'font_size': 18, 'bold': True, 'align': 'center'})
        heading = workbook.add_format({'font_name': 'Microsoft YaHei', 'bold': True, 'bottom': 1})
        money = workbook.add_format({'font_name': 'Microsoft YaHei', 'valign': 'top', 'num_format': '#,##0.00'})
        tax = '含税' if document['tax_included'] else '未税'
        sheet.merge_range(0, 0, 0, 7, '报价单', title)
        for row, left, right in (
            (2, '买方：' + document['buyer'], '卖方：' + document['seller']),
            (3, f"编号：{document['number']} / V{document['version']}", '日期：' + document['date']),
            (4, '付款条款：' + document['payment_terms'], '交付日期：' + document['delivery']),
            (5, f"金额口径：人民币（{tax}）", ''),
        ):
            for start, value in ((0, left), (4, right)):
                if value:
                    sheet.merge_range(row, start, row, start + 3, '', text)
                    sheet.write_string(row, start, value, text)
        for col, label in enumerate(HEADERS):
            sheet.write_string(7, col, label, heading)
        for position, line in enumerate(document['lines'], 8):
            sheet.write_number(position, 0, position - 7, text)
            sheet.write_string(position, 1, line['name'], text)
            sheet.write_string(position, 2, line['specification'], text)
            sheet.write_number(position, 3, line['quantity'], text)
            sheet.write_string(position, 4, line['unit'], text)
            sheet.write_number(position, 5, line['unit_price'], money)
            sheet.write_number(position, 6, line['total'], money)
            sheet.write_string(position, 7, line['remark'], text)
            sheet.set_row(position, max(30, 15 * (1 + len(line['remark']) // 26 + line['remark'].count('\n'))))
        total_row = 8 + len(document['lines'])
        sheet.merge_range(total_row, 0, total_row, 5, '合计', heading)
        sheet.write_number(total_row, 6, document['total'], money)
        for index, width in enumerate((7, 22, 22, 8, 8, 16, 16, 34)):
            sheet.set_column(index, index, width)
        sheet.freeze_panes(8, 0)
        sheet.set_landscape()
        sheet.fit_to_pages(1, 0)
        sheet.repeat_rows(7)
    return buffer.getvalue()


class CustomerQuoteController(http.Controller):
    @http.route('/nodo/contract/quotes/<int:order_id>/xlsx', type='http', auth='user', methods=['GET'])
    def download(self, order_id):
        order = request.env['sale.order'].browse(order_id).exists()
        if not order:
            return request.not_found()
        try:
            document = order._nodo_customer_document()
        except (AccessError, MissingError):
            return request.not_found()
        filename = f"{document['number']}-V{document['version']}-客户报价.xlsx"
        return request.make_response(customer_workbook(document), headers=[
            ('Content-Type', 'application/vnd.openxmlformats-officedocument.spreadsheetml.sheet'),
            ('Content-Disposition', content_disposition(filename)),
            ('Cache-Control', 'private, no-store'),
        ])
