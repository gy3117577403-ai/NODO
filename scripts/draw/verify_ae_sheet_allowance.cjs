// Technical-role acceptance on the existing AE-202 sample and its own drawing pack.
const assert = require("node:assert/strict");
const fs = require("node:fs");
const path = require("node:path");
const {chromium} = require("playwright");
const {call, signInRole} = require("./verify_sheet_costs.cjs");

const out = path.resolve(__dirname, "../../docs/验收/统一AE柜板料核算");
const expected = [
    ["wrap", "围板", 1, "1.135281", "13.368", "2.674", "16.042", "80.208"],
    ["top", "顶板", 1, "0.311183", "3.664", "0.733", "4.397", "21.985"],
    ["bottom", "底板", 1, "0.311182", "3.664", "0.733", "4.397", "21.985"],
    ["door", "左门板", 1, "0.384146", "6.031", "1.206", "7.237", "36.187"],
    ["door_right", "右门板", 1, "0.371068", "5.826", "1.165", "6.991", "34.955"],
    ["mount", "安装板", 1, "0.627239", "12.310", "2.462", "14.771", "73.857"],
    ["brace", "门内加强件", 4, "0.021724", "1.023", "0.205", "1.228", "6.139"],
];

async function checkRows(page) {
    await page.waitForFunction(() => document.querySelector("[data-total-cost]")?.textContent.includes("275.32"),
        null, {timeout:100000});
    const panel = page.getByRole("region", {name:"每台板料用量"});
    assert.match(await panel.innerText(), /测试价/);
    assert.match(await panel.innerText(), /7 种 · 10 件/);
    assert.match(await panel.innerText(), /1\.2（预留 20%）/);
    for (const [selector, value] of [["usage-weight","45.886"],["usage-loss","9.177"],["usage-billable","55.063"]]) {
        assert.equal((await panel.locator("[data-" + selector + "]").innerText()).replace(/\s/g, ""), value + "kg");
    }
    const rows = panel.locator("[data-usage-key]");
    assert.equal(await rows.count(), expected.length);
    for (const [key, name, quantity, area, base, loss, billable, cost] of expected) {
        const row = panel.locator('[data-usage-key="' + key + '"]');
        assert.equal(await row.getByRole("button").getAttribute("aria-label"), "选择" + name + "并查看展开图");
        assert.deepEqual((await row.locator("td").allTextContents()).slice(1),
            [String(quantity),area,base,loss,billable,"5.00",cost]);
    }
    assert.deepEqual(await rows.filter({hasText:"待校核"}).evaluateAll(rr => rr.map(r=>r.dataset.usageKey)),
        ["door","door_right","brace"]);
}

async function selectSheet(page, name, key) {
    await page.getByRole("button", {name:"选择" + name + "并查看展开图", exact:true}).click();
    await page.waitForFunction(key => {
        const image = document.querySelector('[data-flat-key="' + key + '"] img');
        return image?.complete && image.naturalWidth > 0 && image.src.endsWith("/" + key);
    }, key);
}

async function verify() {
    fs.mkdirSync(out, {recursive:true});
    const browser = await chromium.launch({channel:"chrome"});
    try {
        const ctx = await signInRole(browser, "engineering");
        const model = "nodo.draw.design";
        const designs = (await call(ctx, model, "list_designs", [])).filter(d => d.source === "AE-202");
        assert.equal(designs.length, 1);
        const id = designs[0].id, url = "http://127.0.0.1:8079/odoo/technical-workbench?design=" + id + "&tab=parts";
        const read = (method, ...args) => call(ctx, model, method, [[id], ...args]);
        const before = await read("workspace");
        assert.equal(before.sheet_profile.number, "AE00.1000.700.300");
        const legacy = new Map();
        for (const v of await read("sheet_cost_versions")) {
            const s = (await read("read_sheet_cost_version", v.id)).snapshot;
            if (!s.waste_factor) legacy.set(v.id, s);
        }
        const page = await ctx.newPage(), errors = [];
        page.on("pageerror", error => errors.push(error.message));
        await page.setViewportSize({width:1680,height:1000});
        await page.goto(url);
        await checkRows(page);
        await selectSheet(page, "左门板", "door");
        await page.locator(".nd-three-host:not([hidden]) canvas").waitFor({state:"visible"});
        await page.screenshot({path:path.join(out,"逐件板料与左门展开.png"), animations:"disabled"});
        await selectSheet(page, "围板", "wrap");
        await page.getByRole("button",{name:"查看展开原图"}).click();
        await page.waitForFunction(() => {
            const img = document.querySelector('[data-flat-key="wrap"] img');
            return img?.src.includes("/reference/double/") && img.complete && img.naturalWidth > 0;
        });
        assert.match(await page.locator(".nd-source-note").innerText(), /0\.0109/);
        await page.screenshot({path:path.join(out,"围板同版展开原图.png"), animations:"disabled"});
        await page.getByRole("button",{name:"保存核算版本",exact:true}).click();
        const dialog = page.getByRole("dialog");
        await dialog.locator("[data-version-total]").filter({hasText:"275.32"}).waitFor();
        const version = Number(await dialog.locator("[data-version-number]").getAttribute("data-version-number"));
        await dialog.getByRole("button",{name:/关闭|Close/}).first().click();
        // Reopen this cabinet through its workbench link. The generic app root
        // has its own default cabinet and does not identify a saved design.
        await page.goto(url);
        await checkRows(page);
        await page.getByRole("button",{name:"核算版本",exact:true}).click();
        await dialog.locator('[data-version-number="' + version + '"]').waitFor();
        assert.match(await dialog.innerText(), /55\.063/);
        assert.equal(await dialog.locator("[data-version-key]").count(),7);
        const saved = (await read("sheet_cost_versions")).find(v => v.number === version);
        const s = (await read("read_sheet_cost_version", saved.id)).snapshot;
        assert.equal(s.trial,7);
        assert.equal(s.waste_factor,1.2);
        assert.equal(s.sheet_profile.revision, before.sheet_profile.revision);
        assert.deepEqual(s.rows.filter(r=>r.area_source.method === "original").map(r=>r.key),["wrap","top","bottom","mount"]);
        assert.deepEqual(s.rows.filter(r=>r.needs_review).map(r=>r.key),["door","door_right","brace"]);
        for (const row of s.rows) {
            assert.ok(Math.abs(row.weight - row.area * row.thickness * s.density * row.quantity) < 1e-9);
            assert.ok(Math.abs(row.billable_weight - row.weight * 1.2) < 1e-9);
            assert.equal(row.unit,5);
        }
        await page.screenshot({path:path.join(out,"重开板料核算版本.png"), animations:"disabled"});
        for (const [legacyId, old] of legacy) {
            await dialog.getByLabel("查看核算版本").selectOption(String(legacyId));
            await dialog.locator("[data-version-total]").filter({hasText:old.total.toFixed(2)}).waitFor();
            assert.deepEqual((await read("read_sheet_cost_version",legacyId)).snapshot,old);
        }
        const after = await read("workspace");
        assert.deepEqual([after.settings,after.edit_number], [before.settings,before.edit_number]);
        assert.deepEqual(errors,[]);
        return {url,version,legacyTotals:[...legacy.values()].map(s=>s.total),area:s.area,base:s.weight,
            loss:s.loss_weight,billable:s.billable_weight,total:s.total,
            rows:s.rows.map(r=>[r.name,r.quantity,r.weight,r.loss_weight,r.billable_weight,r.amount,r.area_source.method])};
    } finally { await browser.close(); }
}

verify().then(result=>console.log(JSON.stringify(result))).catch(error=>{console.error(error);process.exitCode=1;});
