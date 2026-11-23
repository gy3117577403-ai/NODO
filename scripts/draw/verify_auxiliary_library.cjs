// Read-only local acceptance for the auxiliary library and the AE-202 picker.
const assert = require("node:assert/strict");
const fs = require("node:fs");
const path = require("node:path");
const {chromium} = require("playwright");
const {call, signInRole} = require("./verify_sheet_costs.cjs");

const root = path.resolve(__dirname, "../..");
const out = path.join(root, "docs/验收/辅料库");
const origin = "http://127.0.0.1:8079";
const libraryPath = "/odoo/auxiliary-library";
const sampleCode = "AE-REF-EARTH-200";
const priceModel = "nodo.cost.auxiliary.price";
const number = text => Number(text.trim().replaceAll(",", ""));
const rowFor = page => page.locator(".o_list_view .o_data_row").filter({hasText:sampleCode});
const formFor = page => page.locator(".o_form_view");

async function capture(page, name) {
    await page.bringToFront();
    await page.screenshot({path:path.join(out, name), animations:"disabled"});
}

async function readAdminLibrary(browser, model) {
    const admin = await signInRole(browser, "admin");
    try {
        const page = await admin.newPage();
        await page.goto(origin + libraryPath);
        await rowFor(page).waitFor();
        await page.getByRole("button", {name:"新建", exact:true}).click();
        const lookup = formFor(page).locator('[name="cad_model_id"] input');
        await lookup.fill(model.code);
        const version = "V" + String(model.version).padStart(2, "0");
        await page.getByText(model.code + " · " + model.name + " · " + version, {exact:true}).waitFor();
        await capture(page, "管理员-模型版本选框.png");
    } finally { await admin.close(); }
}

async function verify() {
    fs.mkdirSync(out, {recursive:true});
    const browser = await chromium.launch({channel:"chrome"});
    try {
        const costing = await signInRole(browser, "costing");
        const engineer = await signInRole(browser, "engineering");
        const [rate] = await call(costing, priceModel, "search_read", [[["code", "=", sampleCode]]],
            {fields:["price_per_unit", "cad_model_status"]});
        assert.ok(rate && rate.cad_model_status === "unlinked", "请用未绑定模型的开发样料核对");

        const book = await costing.newPage();
        await book.goto(origin + "/odoo");
        await book.getByRole("button", {name:"成本库", exact:true}).click();
        await book.locator(".o_menu_sections").getByText("辅料库", {exact:true}).click();
        await book.waitForURL("**" + libraryPath);
        await rowFor(book).getByText("待关联模型", {exact:true}).waitFor();
        assert.equal(number(await rowFor(book).locator('[name="price_per_unit"]').innerText()), rate.price_per_unit);
        await capture(book, "核算员-辅料库清单.png");
        await rowFor(book).click();
        await formFor(book).getByText("三维模型与安装规则", {exact:true}).waitFor();
        const price = formFor(book).locator('[name="price_per_unit"] input');
        assert.equal(number(await price.inputValue()), rate.price_per_unit);
        assert.equal(await formFor(book).locator('[name="cad_model_id"]').count(), 0);
        await capture(book, "核算员-辅料档案.png");

        await book.goto(origin + "/odoo/auxiliary-prices");
        assert.equal(number(await rowFor(book).locator('[name="price_per_unit"]').innerText()), rate.price_per_unit);

        const design = (await call(engineer, "nodo.draw.design", "list_designs", [])).find(item => item.source === "AE-202");
        assert.ok(design);
        const quote = await engineer.newPage();
        await quote.goto(origin + "/odoo/technical-workbench?design=" + design.id + "&tab=auxiliary");
        const [reader] = await Promise.all([
            quote.waitForEvent("popup"),
            quote.getByRole("link", {name:"辅料库 ↗", exact:true}).click(),
        ]);
        await reader.waitForURL("**" + libraryPath);
        await rowFor(reader).click();
        const details = formFor(reader);
        await details.getByText("三维模型与安装规则", {exact:true}).waitFor();
        assert.equal(await details.locator('[name="price_per_unit"] input').count(), 0);
        assert.equal(await details.locator('[name="cad_model_id"]').count(), 0);

        await quote.getByRole("button", {name:"添加辅材", exact:true}).click();
        const match = quote.getByRole("region", {name:"选料抽屉"}).locator('[data-picker-code="' + sampleCode + '"]');
        const displayed = await match.locator(".nd-aux-match-price b").innerText();
        assert.equal(number(displayed.split(" 元/件")[0]), rate.price_per_unit);
        await quote.getByRole("button", {name:"取消", exact:true}).click();

        const models = await call(engineer, "nodo.draw.accessory", "list_accessory_models", []);
        await readAdminLibrary(browser, models.find(item => item.state === "available"));
        await quote.getByRole("button", {name:"附件库", exact:true}).click();
        await quote.getByRole("region", {name:"附件型号", exact:true}).getByRole("button").first().waitFor();
        console.log(JSON.stringify({menu:"辅料库", sameRateId:rate.id, price:rate.price_per_unit,
            quoteLink:true, engineeringReadOnly:true, modelPicker:true, screenshots:3}));
    } finally { await browser.close(); }
}

verify().catch(error => {
    console.error(error);
    process.exitCode = 1;
});
