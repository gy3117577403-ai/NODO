# 在 odoo shell 中执行：为每类 NODO 角色各建一个测试用户（只建缺少的，不改已有用户）。
# 由 scripts/nodo.ps1 seed-users 调用；新建用户的随机密码打印到标准输出，由脚本写入本地账号文件。
import secrets

ROLES = [
    ("sales", "销售", "nodo_base.group_role_sales"),
    ("costing", "核算", "nodo_base.group_role_costing"),
    ("approval", "批准", "nodo_base.group_role_approval"),
    ("engineering", "技术", "nodo_base.group_role_engineering"),
    ("purchase", "采购", "nodo_base.group_role_purchase"),
    ("production", "生产", "nodo_base.group_role_production"),
    ("operator", "车间操作", "nodo_base.group_role_operator"),
    ("quality", "质检", "nodo_base.group_role_quality"),
]

Users = env["res.users"].with_context(no_reset_password=True)
for key, label, group_xmlid in ROLES:
    login = f"{key}@nodo.test"
    if Users.with_context(active_test=False).search_count([("login", "=", login)]):
        print("NODO_USER_EXISTS", login)
        continue
    password = "Nodo-" + secrets.token_hex(12)
    Users.create({
        "name": f"测试-{label}",
        "login": login,
        "email": login,
        "lang": "zh_CN",
        "tz": "Asia/Shanghai",
        "password": password,
        "group_ids": [(6, 0, [env.ref(group_xmlid).id])],
    })
    print("NODO_USER_CREATED", label, login, password)

env.cr.commit()
