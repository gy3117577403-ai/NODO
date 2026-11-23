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
const directory = path.resolve(__dirname, "../../docs/验收/辅材核算");

async function waitTotal(page, amount) {
    await page.waitForFunction(value => document.querySelector("[data-auxiliary-total]")?.textContent === `${value} 元`, amount);
}

async function openAuxiliary(page, url) {
    await page.goto(url);
    await page.getByRole("button", {name:"辅材", exact:true}).click();
    await page.getByRole("region", {name:"辅材核算"}).waitFor();
}

async function chooseHeight(page, height) {
    await page.getByRole("button", {name:"规格", exact:true}).click();
    await page.getByRole("spinbutton", {name:"柜高", exact:true}).fill(String(height));
    await page.getByRole("button", {name:"辅材", exact:true}).click();
}

async function saveChoices(page) {
    await page.getByRole("button", {name:"保存辅材选配"}).click();
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

async function captureCabinet(page, file) {
    await page.bringToFront();
    await page.locator(".nd-three-host:not([hidden]) canvas").waitFor({state:"visible", timeout:90000});
    await page.evaluate(() => new Promise(resolve => requestAnimationFrame(() => requestAnimationFrame(resolve))));
    await page.screenshot({path:path.join(directory, file), animations:"disabled"});
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
        costing = await signInRole(browser, "costing");
        design = (await call(engineer, designModel, "list_designs", [])).find(item => item.source === "AE-202");
        assert.ok(design);
        const base = await preview();
        assert.equal(base.height, 700);
        assert.equal(base.total, 24.2);
        assert.deepEqual(base.saved, {items:[], lock:null}, "仅在未额外配置的 AE-202 基础样柜验收");
        rate = base.catalog.find(item => item.code === sampleCode);
        assert.ok(rate);
        assert.equal((await currentRate()).price_per_unit, 2.5);

        const work = await engineer.newPage();
        const errors = [];
        work.on("pageerror", error => errors.push(error.message));
        const url = `${origin}/odoo/technical-workbench?design=${design.id}`;
        await openAuxiliary(work, url);
        await waitTotal(work, "24.20");
        assert.deepEqual(await work.getByRole("table", {name:"标配辅材"}).locator("[data-aux-code]").evaluateAll(
            rows => rows.map(row => row.dataset.auxCode)), ["30209000001", "30215000004", "30102000002"]);
        await captureCabinet(work, "AE202-标配与参考价.png");

        await work.getByRole("combobox", {name:"自选辅材目录"}).selectOption(String(rate.id));
        await work.getByRole("button", {name:"添加辅材", exact:true}).click();
        await waitTotal(work, "26.70");
        const quantity = work.getByRole("spinbutton", {name:"接地编织带 200 mm每台用量"});
        await quantity.fill("2");
        await quantity.press("Tab");
        await waitTotal(work, "29.20");
        restoreSelection = true;
        await saveChoices(work);
        await openAuxiliary(work, url);
        await waitTotal(work, "29.20");
        assert.equal(await quantity.inputValue(), "2");

        await chooseHeight(work, 800);
        await waitTotal(work, "29.20");
        await chooseHeight(work, 801);
        await waitTotal(work, "44.60");
        assert.equal(await work.locator("[data-aux-lock-difference]").textContent(), "+15.40 元");
        const standard = work.getByRole("table", {name:"标配辅材"});
        assert.equal(await standard.locator('[data-aux-code="30102000002"]').count(), 0);
        for (const code of ["30104000002", "30199000155", "30199000156"]) {
            await standard.locator(`[data-aux-code="${code}"]`).waitFor();
        }
        assert.equal(await quantity.inputValue(), "2");
        assert.ok(await work.getByRole("button", {name:"保存辅材选配"}).isDisabled());
        await captureCabinet(work, "801毫米-整组换锁与自选.png");
        await openAuxiliary(work, url);
        await waitTotal(work, "29.20");

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
        assert.equal(await work.locator("[data-auxiliary-total]").count(), 0);
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
