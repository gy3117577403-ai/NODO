# 在 odoo shell 中执行：阶段 0 验收用，生成一张中文报价单并导出 PDF。
# 客户和产品均为虚构。产品名按成品呈现，不带「测试」字样；客户名待用户确认（见阶段 0 验收记录）。
# 可以重复执行，会复用已有记录。
import os

OUT_DIR = "/var/lib/odoo/nodo-acceptance"
REF = "NODO-P0-5"

Partner = env["res.partner"]
partner = Partner.search([("name", "=", "【测试】华东示例成套设备有限公司")], limit=1) or Partner.create({
    "name": "【测试】华东示例成套设备有限公司",
    "is_company": True,
    "country_id": env.ref("base.cn").id,
    "city": "示例市",
    "street": "示例路 1 号（虚构地址）",
    "lang": "zh_CN",
})

Product = env["product.product"]
def product(name, price):
    return Product.search([("name", "=", name)], limit=1) or Product.create({
        "name": name, "list_price": price, "type": "consu",
    })

lines = [
    (product("GGD 低压配电柜柜体 800×600×2200", 4680.0), 3),
    (product("冷轧钢板折弯件 1.5mm 喷塑 RAL7035", 268.0), 12),
    (product("光伏并网箱 3 进 1 出 镀锌板", 1950.0), 2),
]

order = env["sale.order"].search([("client_order_ref", "=", REF)], limit=1)
if not order:
    order = env["sale.order"].create({
        "partner_id": partner.id,
        "user_id": env.ref("base.user_admin").id,
        "client_order_ref": REF,
        "note": "交货期：合同签订后 15 个工作日。本报价单为系统验收测试数据，非真实报价。",
        "order_line": [(0, 0, {"product_id": p.id, "product_uom_qty": q}) for p, q in lines],
    })
# shell 以系统账号运行，销售员默认会是系统机器人；改为测试管理员
order.user_id = env.ref("base.user_admin")

pdf, _fmt = env["ir.actions.report"].with_context(lang="zh_CN")._render_qweb_pdf("sale.action_report_saleorder", order.ids)
os.makedirs(OUT_DIR, exist_ok=True)
path = os.path.join(OUT_DIR, "quote.pdf")
with open(path, "wb") as fh:
    fh.write(pdf)
env.cr.commit()
print("NODO_QUOTE_OK", order.name, order.amount_total, order.currency_id.name, path, len(pdf))
