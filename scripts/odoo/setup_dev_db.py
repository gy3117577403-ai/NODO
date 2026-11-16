# 在 odoo shell 中执行：初始化开发库 nodo_dev 的公司、语言和管理员。
# 由 scripts/nodo.ps1 init-db 调用；管理员密码通过环境变量传入，不写进本文件。
# 可以重复执行。
import os

password = os.environ.get("NODO_ADMIN_PASSWORD")
if not password:
    raise SystemExit("NODO_ADMIN_PASSWORD 未设置")

lang = env["res.lang"].with_context(active_test=False).search([("code", "=", "zh_CN")])
if not lang.active:
    raise SystemExit("简体中文没有启用，请检查 db init 的 --language 参数")

cny = env.ref("base.CNY")
if not cny.active:
    cny.active = True

company = env.ref("base.main_company")
company.write({
    "name": "NODO 测试公司",
    "country_id": env.ref("base.cn").id,
    "currency_id": cny.id,
})

admin = env.ref("base.user_admin")
admin.write({
    "name": "NODO 管理员（测试）",
    "login": "admin@nodo.test",
    "email": "admin@nodo.test",
    "lang": "zh_CN",
    "tz": "Asia/Shanghai",
    "password": password,
})

# 打印 PDF 时 wkhtmltopdf 要回连 Odoo 下载样式。默认用浏览器访问的地址（宿主机 127.0.0.1:8079），
# 在容器里连不上，单据会没有样式。改为容器内地址。
env["ir.config_parameter"].set_str("report.url", "http://localhost:8069")

env["ir.default"].set("res.partner", "lang", "zh_CN")
env["ir.default"].set("res.partner", "tz", "Asia/Shanghai")

env.cr.commit()
print("NODO_SETUP_OK", company.name, company.country_id.code, company.currency_id.name, admin.login, admin.lang, admin.tz)
