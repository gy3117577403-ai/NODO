# addons

NODO 自研模块放在这里，每个模块一个文件夹（`nodo_base`、`nodo_crm`……）。开发环境把本目录只读挂载到容器的 `/mnt/extra-addons`。

规则见仓库根目录的 `AGENTS.md`：不复制 Odoo 核心文件进来改，只通过继承扩展。
