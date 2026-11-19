const MENU_LABELS = new Map([
    ["hr.menu_hr_employee_payroll", "员工名单"],
    ["hr.menu_hr_employee", "员工目录"],
    ["hr.menu_config_plan_plan", "员工计划"],
]);

const MENU_ALIASES = new Map([
    ["purchase.menu_purchase_form_action", ["采购单"]],
    ["sale.menu_sale_order", ["销售订单"]],
]);

export function collectQuickJumpEntries(apps) {
    const entries = [];
    const seen = new Set();
    function visit(menu, parents, icon) {
        const path = [...parents, menu];
        const label = MENU_LABELS.get(menu.xmlid) ?? menu.name;
        const key = `${menu.appID}:${menu.actionID}:${label}`;
        if (menu.actionID && !seen.has(key)) {
            seen.add(key);
            const branch = path[1]?.childrenTree?.length ? path[1] : null;
            entries.push({
                menu,
                icon,
                label,
                branch,
                path: parents.length ? path.map(({ name }) => name).join(" → ") : "",
            });
        }
        for (const child of menu.childrenTree ?? []) {
            visit(child, path, icon);
        }
    }
    for (const { app, icon } of apps) {
        visit(app, [], icon);
    }
    return entries;
}

export function groupQuickJumpFunctions(entries, appId) {
    const groups = new Map();
    for (const entry of entries) {
        const { menu, branch } = entry;
        if (menu.appID !== appId || menu.id === appId) {
            continue;
        }
        const id = branch?.id ?? appId;
        if (!groups.has(id)) {
            groups.set(id, { id, label: branch?.name, entries: [] });
        }
        groups.get(id).entries.push(entry);
    }
    return [...groups.values()];
}

function normalize(value) {
    return value.normalize("NFKC").trim().toLowerCase();
}

export function searchQuickJumpEntries(entries, value) {
    const query = normalize(value);
    const words = query.split(/[\s/→>]+/).filter(Boolean);
    if (!words.length) {
        return [];
    }
    const matches = [];
    for (const entry of entries) {
        const aliases = MENU_ALIASES.get(entry.menu.xmlid) ?? [];
        const names = [entry.label, entry.menu.name, ...aliases].map(normalize);
        const path = normalize(entry.path);
        if (!words.every((word) => names.some((name) => name.includes(word)) || path.includes(word))) {
            continue;
        }
        let rank = 3;
        if (names.includes(query)) {
            rank = 0;
        } else if (names.some((name) => name.startsWith(query))) {
            rank = 1;
        } else if (names.some((name) => name.includes(query))) {
            rank = 2;
        }
        matches.push({ entry, rank });
    }
    return matches.sort((a, b) => a.rank - b.rank).map(({ entry }) => entry);
}
