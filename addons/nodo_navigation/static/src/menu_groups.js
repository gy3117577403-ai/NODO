const GROUPS = [
    ["collaboration", "协同"],
    ["operations", "业务"],
    ["organization", "组织"],
    ["other", "更多应用"],
    ["system", "系统"],
];

const APPS = new Map(Object.entries({
    "mail.menu_root_discuss": ["collaboration", "forum"],
    "calendar.mail_menu_calendar": ["collaboration", "calendar_today"],
    "spreadsheet_dashboard.spreadsheet_dashboard_menu_root": ["collaboration", "bar_chart"],
    "crm.crm_menu_root": ["operations", "handshake"],
    "sale.sale_menu_root": ["operations", "description"],
    "nodo_supply.menu_supply_root": ["operations", "assignment"],
    "purchase.menu_purchase_root": ["operations", "shopping_bag"],
    "stock.menu_stock_root": ["operations", "inventory_2"],
    "mrp.menu_mrp_root": ["operations", "precision_manufacturing"],
    "nodo_draw.menu_root": ["operations", "design_services"],
    "contacts.menu_contacts": ["organization", "contact_page"],
    "hr.menu_hr_root": ["organization", "groups"],
    "base.menu_management": ["system", "extension"],
    "base.menu_administration": ["system", "settings"],
}));

export function groupApplications(apps) {
    const groups = new Map(GROUPS.map(([key, label]) => [key, { key, label, items: [] }]));
    for (const app of apps) {
        const [key, icon] = APPS.get(app.xmlid) ?? ["other", "apps"];
        groups.get(key).items.push({ app, icon });
    }
    return [...groups.values()].filter((group) => group.items.length > 0);
}
