from odoo import api, http
from odoo.http import request
from odoo.http.stream import Stream

from odoo.addons.web.controllers.binary import Binary

NODO_LOGO = 'nodo_base/static/img/nodo-wordmark.png'


class NodoBinary(Binary):
    """公司还没上传 logo 时，门户和公共页面顶部显示 NODO 字标，而不是上游的「Your logo」占位图。

    只影响 /logo、/logo.png、/web/binary/company_logo 这几个网址；打印件直接读取公司 logo 字段，不受影响。
    """

    @http.route()
    def company_logo(self, dbname=None, **kw):
        if request.db:
            try:
                env = request.env(user=request.session.uid or api.SUPERUSER_ID, su=True)
                company_id = (kw or {}).get('company')
                company = env['res.company'].browse(int(company_id)) if company_id else env.user.company_id
                if company.exists() and company.uses_default_logo:
                    return Stream.from_path(NODO_LOGO).get_response()
            except (ValueError, TypeError):
                pass
        return super().company_logo(dbname=dbname, **kw)
