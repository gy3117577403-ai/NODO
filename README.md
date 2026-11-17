# NODO

NODO 是面向电气成套、钣金机柜、光伏配电工厂的垂直智能制造平台，基于 Odoo 社区版 20.0（LGPLv3）二次开发。产品界面不使用 Odoo 名称和标志，技术文档和许可证声明中如实注明。覆盖询盘、报价、合同、采购与库存、生产执行和质量管控，不包含财务模块。

## 当前状态

阶段 0：工程底座，开发者自检完成，待用户验收（记录见 `docs/验收/阶段0验收记录.md`）。

| 任务 | 内容 | 状态 |
|---|---|---|
| P0-1 | 把本机预览环境移到 `_preview/` | 已完成 |
| P0-2 | 建仓库和项目文档 | 已完成 |
| P0-3 | NODO 开发环境（Docker、中文字体、开发库） | 已完成 |
| P0-4 | `nodo_base`：品牌与角色 | 已完成（残留项见 `docs/品牌残留.md`） |
| P0-5 | 测试与验收 | 已完成自检：17 个测试通过，中文报价单 PDF 正常 |

## 开发环境

需要 Docker Desktop。在仓库根目录的 PowerShell 中运行：

```powershell
powershell -ExecutionPolicy Bypass -File scripts\nodo.ps1 init      # 生成 .env 和 config/odoo.conf，已存在则跳过
powershell -ExecutionPolicy Bypass -File scripts\nodo.ps1 build     # 构建镜像
powershell -ExecutionPolicy Bypass -File scripts\nodo.ps1 init-db   # 首次：创建开发库 nodo_dev
powershell -ExecutionPolicy Bypass -File scripts\nodo.ps1 up        # 启动
powershell -ExecutionPolicy Bypass -File scripts\nodo.ps1 stop      # 停止，数据保留
```

其他命令：`logs`、`check`（核对开发库）、`install <模块>`、`update <模块>`、`seed-users`（每个角色一个测试用户）、`test <模块>`、`shell`。不带参数运行可查看说明。

首次搭建后依次运行 `install nodo_base` 和 `seed-users`。

采购协作试点运行 `install nodo_supply` 和 `seed-supply-pilot`，操作步骤见 [采购协作权限验收](docs/验收/采购协作权限验收.md)。

在开发库验证人员档案流程时运行 `install nodo_staff_import` 并使用虚构名单。人员确认表和试点导入步骤见 [人员档案接入](docs/手册/管理员/人员档案接入.md)。

员工入门、采购与技术协作、管理员权限配置和开发交接见 [NODO 使用与维护手册](docs/手册/README.md)。

- 地址 http://127.0.0.1:8079 ，只绑定本机
- 管理员账号和密码在 `config/dev-accounts.local.md`（本地生成，不提交）
- 开发库 `nodo_dev`：简体中文、时区 Asia/Shanghai、公司「NODO」（中国，人民币），不含演示数据；已安装联系人、CRM、销售、采购、库存、制造、讨论
- Compose 项目 `nodo-dev`，数据卷 `nodo-dev_odoo-data`、`nodo-dev_pg-data`，网段 `10.239.70.0/28`
- `test <模块>` 会新建一个一次性测试库 `nodo_test_<时间>`，测试结束后自动删除，不影响 `nodo_dev`

### 中文字体

官方镜像已带 Noto CJK 字体，但没有语言标记时汉字会回退到日文字形（`Noto Sans CJK JP`）。`Dockerfile` 设定 `FC_LANG=zh-cn`，构建时校验汉字回退到简体中文字形。已用 wkhtmltopdf 实测：官方镜像生成的 PDF 嵌入 `NotoSansCJKjp`，NODO 镜像嵌入 `NotoSansCJKsc`。

### 打印地址

打印 PDF 时 wkhtmltopdf 会回连 Odoo 下载样式。默认用浏览器访问的地址，在 Docker 里连不上，单据会丢失样式。开发库已把系统参数 `report.url` 设为容器内地址 `http://localhost:8069`（`init-db` 会自动设置）。以后部署到服务器时同样要设置。

## 目录

```
NODO/
├─ AGENTS.md            开发约定，所有参与开发的人和工具都要遵守
├─ DESIGN.md            设计规范
├─ Dockerfile           NODO 镜像（官方镜像 + 简体中文字形设定）
├─ docker-compose.yml   开发环境
├─ .env.example         环境变量模板
├─ config/
│  └─ odoo.conf.example 配置模板（生成的 odoo.conf 不提交）
├─ addons/
│  ├─ nodo_base/        品牌、主题、八类角色、讨论与通用单据卡片（必装）
│  ├─ nodo_base_sale/   报价和销售订单卡片、发到聊天（安装基础和销售后自动安装）
│  ├─ nodo_base_purchase/ 采购询价单和采购单卡片、发到聊天（安装基础和采购后自动安装）
│  ├─ nodo_supply/     采购岗位、员工个人权限和采购单协作
│  └─ nodo_staff_import/ 员工档案预检、导入和批次记录
├─ scripts/
│  ├─ nodo.ps1          开发环境命令
│  └─ odoo/             在 odoo shell 中执行的初始化和核对脚本
├─ docs/
│  ├─ 开发方案.md        阶段划分、模块和技术路线
│  ├─ 权限矩阵.md        八类角色的权限和用户决定
│  ├─ 品牌残留.md        仍会出现上游名称的位置
│  ├─ 手册/             员工、管理员与开发人员使用说明
│  └─ 验收/             验收截图
└─ _preview/            本机预览环境和安装包构建目录，不纳入版本管理
```

## 本机预览环境

`_preview/` 里是 Odoo 社区版 20.0 的本机预览，含演示数据，只用于对照参考，和 NODO 开发环境互不影响。

- 地址 http://127.0.0.1:8069
- 启动和停止方法见 `_preview/README.md`
- `_preview/.native-client-build/payload/server` 是官方 20.0 源码，开发时只读查阅，不修改、不复制进 `addons/`
- 该目录含预览环境的明文密码，已被 `.gitignore` 排除，不得提交或分发
