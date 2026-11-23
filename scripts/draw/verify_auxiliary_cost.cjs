const assert = require("node:assert/strict");
const fs = require("node:fs");
const path = require("node:path");
const {chromium} = require("playwright");
const {call, signInRole} = require("./verify_sheet_costs.cjs");

const origin = "http://127.0.0.1:8079";
const designModel = "nodo.draw.design";
const priceModel = "nodo.cost.auxiliary.price";
const sampleCode = "AE-REF-EARTH-200";
const lockEvidence = "本机规则复验，整组换配";
const directory = path.resolve(__dirname, "../../docs/验收/报价工作区");
const quoteOnly = process.argv.includes("--quote-workspace");
const quoteUrl = origin + "/odoo/technical-workbench";
const button = (page, name) => page.getByRole("button", {name, exact:true});
const standard = page => page.getByRole("table", {name:"标配辅材"});

async function waitAmount(page, selector, amount) {
    await page.waitForFunction(([sel, value]) => document.querySelector(sel)?.textContent.trim() === value, [selector, amount]);
}

const waitTotal = (page, amount) => waitAmount(page, "[data-auxiliary-total]", amount);

async function openQuote(page, url) {
    await page.goto(url);
    const entry = button(page, "报价");
    await entry.waitFor();
    const design = page.getByRole("group", {name:"设计工具"});
    assert.deepEqual(await design.getByRole("button").allTextContents(), ["规格", "材料", "孔位"]);
    assert.equal(await entry.evaluate(element => element.previousElementSibling.textContent.trim()), "附件库");
    await entry.click();
    await page.getByRole("group", {name:"报价页签"}).waitFor();
}

async function openAuxiliary(page, url) {
    await page.goto(url + "&tab=auxiliary");
    await page.getByRole("region", {name:"辅材核算"}).waitFor();
}

async function chooseHeight(page, height) {
    await button(page, "设计视图").click();
    await button(page, "规格").click();
    await page.getByRole("spinbutton", {name:"柜高", exact:true}).fill(String(height));
    await button(page, "报价").click();
    await button(page, "辅材").click();
}

async function saveChoices(page) {
    await button(page, "保存辅材选配").click();
    await page.getByText("辅材选配已保存", {exact:true}).waitFor();
}

async function changeRate(page, price) {
    const input = page.locator('.o_form_view [name="price_per_unit"] input');
    await input.fill(price);
    await input.press("Tab");
    const saved = page.waitForResponse(r => r.url().includes(`/${priceModel}/web_save`) && r.ok());
    await page.locator(".o_form_button_save:visible").first().click();
    const response = await (await saved).json();
    assert.ok(!response.error, response.error?.message);
}

async function capture(page, file) {
    await page.bringToFront();
    await page.evaluate(() => new Promise(resolve => requestAnimationFrame(() => requestAnimationFrame(resolve))));
    await page.screenshot({path:path.join(directory, file), animations:"disabled"});
}

async function verifyParts(page) {
    const rows = page.getByRole("table", {name:"逐件板料用量"}).locator("tbody tr");
    await waitAmount(page, "[data-quote-sheet]", "275.32");
    await waitAmount(page, "[data-quote-total]", "299.52");
    assert.equal(await rows.count(), 7);
    assert.match(await page.locator("[data-usage-weight]").innerText(), /45\.886\s*kg/);
    assert.deepEqual(await rows.filter({hasText:"待校核"}).evaluateAll(items => items.map(row => row.dataset.usageKey)),
        ["door", "door_right", "brace"]);
    const door = button(page, "选择右门板并查看展开图");
    await door.click();
    await page.waitForFunction(() => document.querySelector('[data-flat-key="door_right"] img')?.naturalWidth > 0);
    assert.equal(await door.getAttribute("aria-pressed"), "true");
    await page.locator(".nd-three-host canvas").waitFor({state:"visible"});
    await capture(page, "AE-202-报价零件.png");
    await button(page, "零件结构").click();
    await page.getByRole("region", {name:"零件结构"}).waitFor();
    await waitAmount(page, "[data-quote-sheet]", "275.32");
    await button(page, "板料用量").click();
    assert.equal(await door.getAttribute("aria-pressed"), "true");
}

async function verifyPicker(page) {
    const drawer = page.getByRole("region", {name:"选料抽屉"});
    const open = button(page, "添加辅材");
    await open.click();
    const search = drawer.getByRole("searchbox", {name:"搜索物料名称或编码"});
    await search.fill("接地编织带");
    await page.waitForFunction(() => document.querySelectorAll("[data-picker-code]").length === 1);
    await button(page, "取消").click();
    await drawer.waitFor({state:"hidden"});
    assert.equal(await page.getByRole("table", {name:"自选辅材"}).count(), 0);
    await waitTotal(page, "24.20");

    await open.click();
    await drawer.waitFor();
    const box = await page.locator(".nd-aux-drawer").boundingBox();
    const viewport = page.viewportSize();
    assert.ok(box.x > viewport.width / 2 && Math.abs(box.x + box.width - viewport.width) < 5
        && box.y < 5 && Math.abs(box.height - viewport.height) < 5, "选料抽屉应贴右边并贯穿窗口");
    await search.fill(sampleCode);
    const matching = drawer.locator("[data-picker-code]");
    await page.waitForFunction(code => {
        const items = document.querySelectorAll("[data-picker-code]");
        return items.length === 1 && items[0].dataset.pickerCode === code;
    }, sampleCode);
    assert.match(await matching.innerText(), /2\.50 元\/件/);
    await matching.click();
    const quantity = drawer.getByRole("spinbutton", {name:"添加的每台用量"});
    await quantity.fill("1.5");
    await drawer.getByText("请输入 1 至 10000 的整数。", {exact:true}).waitFor();
    assert.ok(await button(page, "加入清单").isDisabled());
    await quantity.fill("2");
    await waitAmount(page, "[data-picker-amount]", "5.00 元/台");
    await capture(page, "AE-202-选料抽屉.png");
    await button(page, "加入清单").click();
    await drawer.waitFor({state:"hidden"});
}

async function verify() {
    fs.mkdirSync(directory, {recursive:true});
    const browser = await chromium.launch({channel:"chrome"});
    let engineer, costing, design, rate;
    const preview = () => call(engineer, designModel, "preview_auxiliary_costs", [[design.id]]);
    const currentRate = async () => (await call(costing, priceModel, "read", [[rate.id], ["price_per_unit", "source_note"]]))[0];
    let restoreSelection = false;
    let restorePrice = false;
    let restoreLock = false;
    try {
        engineer = await signInRole(browser, "engineering");
        if (!quoteOnly) costing = await signInRole(browser, "costing");
        design = (await call(engineer, designModel, "list_designs", [])).find(item => item.source === "AE-202");
        assert.ok(design);
        const base = await preview();
        assert.equal(base.height, 700);
        assert.equal(base.total, 24.2);
        assert.deepEqual(base.saved, {items:[], lock:null}, "仅在未额外配置的 AE-202 基础样柜验收");
        rate = base.catalog.find(item => item.code === sampleCode);
        assert.ok(rate);
        assert.equal(rate.price, 2.5);
        if (!quoteOnly) assert.equal((await currentRate()).price_per_unit, 2.5);

        const work = await engineer.newPage();
        const errors = [];
        work.on("pageerror", error => errors.push(error.message));
        work.on("console", entry => {
            if (entry.type() === "error" && /OwlError|TypeError/.test(entry.text())) errors.push(entry.text());
        });
        const url = `${quoteUrl}?design=${design.id}`;
        await openQuote(work, url);
        await verifyParts(work);
        await button(work, "辅材").click();
        await waitTotal(work, "24.20");
        assert.deepEqual(await standard(work).locator("[data-aux-code]").evaluateAll(
            rows => rows.map(row => row.dataset.auxCode)), ["30209000001", "30215000004", "30102000002"]);
        assert.equal(await work.locator(".nd-layout").isVisible(), false);

        await verifyPicker(work);
        const quantity = work.getByRole("spinbutton", {name:"接地编织带 200 mm每台用量"});
        await waitTotal(work, "29.20");
        await button(work, "零件").click();
        await button(work, "辅材").click();
        assert.equal(await quantity.inputValue(), "2");
        restoreSelection = true;
        await saveChoices(work);
        await openAuxiliary(work, url);
        await waitTotal(work, "29.20");
        assert.equal(await quantity.inputValue(), "2");
        await waitAmount(work, "[data-quote-total]", "304.52");
        await capture(work, "AE-202-自选保存重开.png");

        await chooseHeight(work, 800);
        await waitTotal(work, "29.20");
        await work.locator(".nd-aux-basis").getByText(/柜体高 800 mm/).waitFor();
        assert.deepEqual(await standard(work).locator("[data-aux-code]").evaluateAll(
            rows => rows.map(row => row.dataset.auxCode)), ["30209000001", "30215000004", "30102000002"]);
        await capture(work, "AE-202-800mm.png");
        await chooseHeight(work, 801);
        await waitTotal(work, "44.60");
        assert.equal(await work.locator("[data-aux-lock-difference]").textContent(), "+15.40 元/台");
        assert.deepEqual(await standard(work).locator("[data-aux-code]").evaluateAll(
            rows => rows.map(row => row.dataset.auxCode)), ["30209000001", "30215000004", "30104000002", "30199000155", "30199000156"]);
        assert.deepEqual(await standard(work).locator(".nd-aux-quantity b").allTextContents(), ["6", "2", "1", "1", "1"]);
        assert.equal(await quantity.inputValue(), "2");
        assert.ok(await button(work, "保存辅材选配").isDisabled());
        await work.getByText("待重算", {exact:true}).waitFor();
        assert.equal(await work.locator("[data-quote-total]").count(), 0);
        await capture(work, "AE-202-801mm.png");
        await openAuxiliary(work, url);
        await waitTotal(work, "29.20");

        if (quoteOnly) {
            await button(work, "移除接地编织带 200 mm").click();
            await waitTotal(work, "24.20");
            await saveChoices(work);
            const restored = await preview();
            assert.deepEqual({edit:restored.spec_edit, height:restored.height, saved:restored.saved},
                {edit:base.spec_edit, height:base.height, saved:base.saved});
            restoreSelection = false;
            assert.deepEqual(errors, []);
            console.log(JSON.stringify({design:design.id, board:275.32, base700:24.2, withExtras700:29.2,
                withExtras800:29.2, withExtras801:44.6, lockDifference:15.4, reopened:true, restored:true, screenshots:5}));
            return;
        }

        const book = await costing.newPage();
        book.on("pageerror", error => errors.push(error.message));
        await book.goto(`${origin}/odoo/auxiliary-prices`);
        await book.locator(".o_list_view .o_data_row").filter({hasText:sampleCode}).first().waitFor();
        await book.screenshot({path:path.join(directory, "核算员-辅材单价库.png"), animations:"disabled"});
        await book.locator(".o_list_view .o_data_row").filter({hasText:sampleCode}).first().click();
        restorePrice = true;
        await changeRate(book, "3");
        await waitTotal(work, "30.20");
        await changeRate(book, "0");
        await work.getByText("待补价", {exact:true}).waitFor();
        await waitTotal(work, "");
        await changeRate(book, "2.5");
        await waitTotal(work, "29.20");
        restorePrice = false;

        await work.getByRole("button", {name:"移除接地编织带 200 mm"}).click();
        await waitTotal(work, "24.20");
        await saveChoices(work);
        const restored = await preview();
        assert.equal(restored.spec_edit, base.spec_edit);
        assert.deepEqual(restored.saved, base.saved);
        restoreSelection = false;

        await work.getByRole("button", {name:"锁具换配", exact:true}).click();
        await work.getByRole("combobox", {name:"锁具组合"}).selectOption("MS821");
        const basis = work.getByRole("textbox", {name:"换配依据"});
        await basis.fill(lockEvidence);
        await basis.press("Tab");
        await waitTotal(work, "39.60");
        restoreLock = true;
        await saveChoices(work);
        await openAuxiliary(work, url);
        await waitTotal(work, "39.60");
        assert.equal((await preview()).saved.lock.reason, lockEvidence);
        await work.getByRole("button", {name:"锁具换配", exact:true}).click();
        await work.getByRole("combobox", {name:"锁具组合"}).selectOption("");
        await waitTotal(work, "24.20");
        await saveChoices(work);
        assert.deepEqual((await preview()).saved, base.saved);
        restoreLock = false;
        assert.deepEqual(errors, []);
        console.log(JSON.stringify({design:design.id, standard700:24.2, standard800:24.2, standard801:39.6,
            withExtras801:44.6, livePrice:30.2, missingPrice:true, overridePersistence:true,
            restored:restored.total, screenshots:3}));
    } finally {
        try {
            if (restorePrice) {
                const actual = await currentRate();
                if (actual.source_note === "自选流程参考值" && [0, 3].includes(actual.price_per_unit)) {
                    await call(costing, priceModel, "write", [[rate.id], {price_per_unit:2.5}]);
                }
            }
            if (restoreSelection) {
                const actual = await preview();
                if (!actual.saved.lock && actual.saved.items.length === 1 && actual.saved.items[0].id === rate.id
                    && actual.saved.items[0].quantity === 2) {
                    await call(engineer, designModel, "save_auxiliary_choices", [[design.id], actual.spec_edit,
                        actual.revision, {items:[], lock:null}]);
                }
            }
            if (restoreLock) {
                const actual = await preview();
                if (actual.saved.lock?.reason === lockEvidence && !actual.saved.items.length) {
                    await call(engineer, designModel, "save_auxiliary_choices", [[design.id], actual.spec_edit,
                        actual.revision, {items:[], lock:null}]);
                }
            }
        } finally {
            await browser.close();
        }
    }
}

verify().catch(error => {
    console.error(error);
    process.exitCode = 1;
});
