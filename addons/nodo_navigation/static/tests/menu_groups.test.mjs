import assert from "node:assert/strict";
import { test } from "node:test";
import { groupApplications } from "../src/menu_groups.js";

test("nodo navigation groups visible apps by menu identity", () => {
    const chat = { id: 1, xmlid: "mail.menu_root_discuss", name: "内部沟通" };
    const employees = { id: 2, xmlid: "hr.menu_hr_root", name: "员工" };
    const purchase = { id: 3, xmlid: "nodo_supply.menu_supply_root", name: "采购协作" };

    const groups = groupApplications([employees, purchase, chat]);

    assert.deepEqual(groups.map(({ key }) => key), ["collaboration", "operations", "organization"]);
    assert.deepEqual(groups.flatMap(({ items }) => items.map(({ app }) => app)), [chat, purchase, employees]);
});

test("nodo navigation preserves unfamiliar entries and places system tools last", () => {
    const settings = { id: 1, xmlid: "base.menu_administration", name: "设置" };
    const unfamiliar = { id: 2, xmlid: "extra.menu", name: "员工" };
    const noExternalId = { id: 3, name: "厂内工作台" };

    const groups = groupApplications([settings, unfamiliar, noExternalId]);

    assert.deepEqual(groups.map(({ key }) => key), ["other", "system"]);
    assert.deepEqual(groups[0].items.map(({ app }) => app), [unfamiliar, noExternalId]);
    assert.deepEqual(groups[1].items.map(({ app }) => app), [settings]);
});

test("nodo navigation has no synthetic or empty entries", () => {
    assert.deepEqual(groupApplications([]), []);
});
