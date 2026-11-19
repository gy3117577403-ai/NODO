import assert from "node:assert/strict";
import { test } from "node:test";
import { collectQuickJumpEntries, searchQuickJumpEntries } from "../src/quick_jump_search.js";

const management = {
    id: 2, appID: 1, xmlid: "hr.menu_hr_employee_payroll", name: "管理", actionID: 20,
};
const directory = {
    id: 3, appID: 1, xmlid: "hr.menu_hr_employee", name: "目录", actionID: 30,
};
const plans = {
    id: 5, appID: 1, xmlid: "hr.menu_config_plan_plan", name: "员工计划", actionID: 50,
};
const configuration = { id: 4, appID: 1, name: "配置", childrenTree: [plans] };
const employeeApp = {
    id: 1, appID: 1, xmlid: "hr.menu_hr_root", name: "员工", actionID: 20,
    childrenTree: [management, directory, configuration],
};
const discuss = {
    id: 6, appID: 6, xmlid: "mail.menu_root_discuss", name: "讨论", actionID: 60,
};
const settings = {
    id: 7, appID: 7, xmlid: "base.menu_administration", name: "设置", actionID: 70,
};

const adminEntries = collectQuickJumpEntries([
    { app: employeeApp, icon: "groups" },
    { app: discuss, icon: "forum" },
    { app: settings, icon: "settings" },
]);

test("nodo quick jump searches the names and paths of real actionable menus", () => {
    const [roster] = searchQuickJumpEntries(adminEntries, "员工名单");
    assert.equal(roster.menu, management);
    assert.equal(roster.path, "员工 → 管理");
    assert.equal(searchQuickJumpEntries(adminEntries, "管理")[0].menu, management);
    assert.equal(searchQuickJumpEntries(adminEntries, "员工计划")[0].menu, plans);
    assert.equal(searchQuickJumpEntries(adminEntries, "员工 / 配置 / 计划")[0].menu, plans);
    assert.equal(searchQuickJumpEntries(adminEntries, "员工")[0].menu, employeeApp);
    assert.equal(adminEntries.some(({ menu }) => menu === configuration), false);
});

test("nodo quick jump adds no results for menus absent from the user's tree", () => {
    const staffEntries = collectQuickJumpEntries([
        { app: { ...employeeApp, actionID: 30, childrenTree: [directory] }, icon: "groups" },
        { app: discuss, icon: "forum" },
    ]);
    for (const query of ["员工名单", "员工计划", "设置"]) {
        assert.deepEqual(searchQuickJumpEntries(staffEntries, query), []);
    }
    assert.equal(searchQuickJumpEntries(staffEntries, "员工目录")[0].menu, directory);
    assert.equal(searchQuickJumpEntries(staffEntries, "讨论")[0].menu, discuss);
});

test("nodo quick jump shows at most six default entries without app-home duplicates", () => {
    const extraApps = [8, 9, 10].map((id) => ({
        app: { id, appID: id, name: `应用 ${id}`, actionID: id * 10 },
        icon: "apps",
    }));
    const entries = [...adminEntries, ...collectQuickJumpEntries(extraApps)];
    const defaults = searchQuickJumpEntries(entries, "  ");
    assert.equal(defaults.length, 6);
    assert.deepEqual(defaults.slice(0, 4).map(({ menu }) => menu), [
        management, directory, plans, discuss,
    ]);
    assert.equal(defaults.some(({ menu }) => menu === employeeApp), false);
});

test("nodo quick jump keeps same-named functions distinct by menu path", () => {
    const sameNamed = { id: 8, appID: 7, name: "目录", actionID: 30 };
    const entries = collectQuickJumpEntries([
        { app: employeeApp, icon: "groups" },
        { app: { ...settings, childrenTree: [sameNamed] }, icon: "settings" },
    ]);
    const results = searchQuickJumpEntries(entries, "目录");
    assert.deepEqual(results.map(({ path }) => path), ["员工 → 目录", "设置 → 目录"]);
});

test("nodo quick jump presents a same-named app and child with the same action once", () => {
    const commonAction = { id: 9, appID: 6, name: "讨论", actionID: 60 };
    const entries = collectQuickJumpEntries([
        { app: { ...discuss, childrenTree: [commonAction] }, icon: "forum" },
    ]);
    assert.deepEqual(searchQuickJumpEntries(entries, "讨论").map(({ menu }) => menu.id), [discuss.id]);
});
