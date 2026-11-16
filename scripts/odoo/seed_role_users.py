# 在 odoo shell 中执行：为每类 NODO 角色各建一个测试用户（只建缺少的，不改已有用户）。
# 由 scripts/nodo.ps1 seed-users 调用；新建用户的随机密码打印到标准输出，由脚本写入本地账号文件。
import secrets

# (登录名前缀, 角色, 界面显示的姓名, 角色组)。姓名按成品呈现，不带「测试」等字样。
ROLES = [
    ("sales", "销售", "销售专员", "nodo_base.group_role_sales"),
    ("costing", "核算", "成本核算", "nodo_base.group_role_costing"),
    ("approval", "批准", "审批负责人", "nodo_base.group_role_approval"),
    ("engineering", "技术", "技术工程师", "nodo_base.group_role_engineering"),
    ("purchase", "采购", "采购专员", "nodo_base.group_role_purchase"),
    ("production", "生产", "生产主管", "nodo_base.group_role_production"),
    ("operator", "车间操作", "车间操作工", "nodo_base.group_role_operator"),
    ("quality", "质检", "质检专员", "nodo_base.group_role_quality"),
]

Users = env["res.users"].with_context(no_reset_password=True)
for key, label, display_name, group_xmlid in ROLES:
    login = f"{key}@nodo.test"
    if Users.with_context(active_test=False).search_count([("login", "=", login)]):
        print("NODO_USER_EXISTS", login)
        continue
    password = "Nodo-" + secrets.token_hex(12)
    Users.create({
        "name": display_name,
        "login": login,
        "email": login,
        "lang": "zh_CN",
        "tz": "Asia/Shanghai",
        "password": password,
        "group_ids": [(6, 0, [env.ref(group_xmlid).id])],
    })
    print("NODO_USER_CREATED", label, login, password)

env.cr.commit()
