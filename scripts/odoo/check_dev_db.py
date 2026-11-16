# 在 odoo shell 中执行：只读核对开发库状态，供 scripts/nodo.ps1 check 使用。
company = env.ref("base.main_company")
admin = env.ref("base.user_admin")
wanted = ["contacts", "crm", "sale_management", "purchase", "stock", "mrp", "mail"]
mods = env["ir.module.module"].search([("name", "in", wanted + ["l10n_cn", "account"])])
state = {m.name: m.state for m in mods}
langs = env["res.lang"].search([]).mapped("code")
print("NODO_CHECK company", company.name, company.country_id.code, company.currency_id.name)
print("NODO_CHECK admin", admin.login, admin.lang, admin.tz)
print("NODO_CHECK languages", ",".join(langs))
print("NODO_CHECK modules", ",".join(f"{k}={state.get(k, 'missing')}" for k in wanted + ["account", "l10n_cn"]))
print("NODO_CHECK demo", bool(env["ir.module.module"].search_count([("demo", "=", True)])))
