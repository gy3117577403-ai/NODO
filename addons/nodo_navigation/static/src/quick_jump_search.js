const MENU_LABELS = new Map([
    ["hr.menu_hr_employee_payroll", "员工名单"],
    ["hr.menu_hr_employee", "员工目录"],
    ["hr.menu_config_plan_plan", "员工计划"],
]);

const COMMON_MENUS = [
    "hr.menu_hr_employee_payroll",
    "hr.menu_hr_employee",
    "hr.menu_config_plan_plan",
    "hr.menu_hr_department_kanban",
    "mail.menu_root_discuss",
    "nodo_supply.menu_purchase_collaboration",
];

function actionKey(menu) {
    return `${menu.appID}:${menu.actionID}`;
}

export function collectQuickJumpEntries(apps) {
    const entries = [];
    const seen = new Set();
    function visit(menu, parents, icon) {
        const names = [...parents, menu.name];
        const label = MENU_LABELS.get(menu.xmlid) ?? menu.name;
        const key = `${actionKey(menu)}:${label}`;
        if (menu.actionID && !seen.has(key)) {
            seen.add(key);
            entries.push({
                menu,
                icon,
                label,
                path: parents.length ? names.join(" → ") : "",
            });
        }
        for (const child of menu.childrenTree ?? []) {
            visit(child, names, icon);
        }
    }
    for (const { app, icon } of apps) {
        visit(app, [], icon);
    }
    return entries;
}

function commonEntries(entries) {
    const byMenu = new Map(entries.map((entry) => [entry.menu.xmlid, entry]));
    const preferred = COMMON_MENUS.map((key) => byMenu.get(key)).filter(Boolean);
    const appEntries = entries.filter(({ menu }) => menu.id === menu.appID);
    const seen = new Set();
    return [...preferred, ...appEntries].filter(({ menu }) => {
        const key = actionKey(menu);
        if (seen.has(key)) {
            return false;
        }
        seen.add(key);
        return true;
    }).slice(0, 6);
}

function normalize(value) {
    return value.normalize("NFKC").trim().toLowerCase();
}

export function searchQuickJumpEntries(entries, value) {
    const query = normalize(value);
    const words = query.split(/[\s/→>]+/).filter(Boolean);
    if (!words.length) {
        return commonEntries(entries);
    }
    const matches = [];
    for (const entry of entries) {
        const names = [normalize(entry.label), normalize(entry.menu.name)];
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
