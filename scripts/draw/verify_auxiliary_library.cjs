// Read-only local acceptance for the auxiliary library and the AE-202 picker.
const assert = require("node:assert/strict");
const fs = require("node:fs");
const path = require("node:path");
const {chromium} = require("playwright");
const {call, signInRole} = require("./verify_sheet_costs.cjs");
const {imageDifference, modelBounds} = require("./verify_accessory_library.cjs");

const root = path.resolve(__dirname, "../..");
const out = path.join(root, "docs/验收/辅料三维预览");
const origin = "http://127.0.0.1:8079";
const libraryPath = "/odoo/auxiliary-library";
const sampleCode = "AE-REF-EARTH-200";
const priceModel = "nodo.cost.auxiliary.price";
const number = text => Number(text.trim().replaceAll(",", ""));
const rowFor = page => page.locator('.nd-al-item[data-material-code="' + sampleCode + '"]');
const legacyRow = page => page.locator(".o_list_view .o_data_row").filter({hasText:sampleCode});
const formFor = page => page.locator(".o_form_view");
const previewFor = page => page.getByRole("region", {name:"三维预览", exact:true});

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

async function verifyExample(page) {
    const preview = previewFor(page);
    await preview.getByRole("heading", {name:"待关联模型", exact:true}).waitFor();
    assert.equal(await preview.locator("canvas").count(), 0);
    await capture(page, "技术员-待关联模型.png");
    await preview.getByRole("button", {name:"预览示例模型", exact:true}).click();
    const reset = preview.getByRole("button", {name:"复位视角", exact:true});
    await reset.waitFor();
    await preview.getByText("示例模型", {exact:true}).waitFor();
    const canvas = preview.locator(".nd-library-mesh canvas");
    const area = await canvas.boundingBox();
    assert.ok(area.width > 400 && area.height > 350, "桌面三维视口应留足空间");
    const pauseForPaint = () => page.evaluate(() => new Promise(resolve => requestAnimationFrame(() => requestAnimationFrame(resolve))));
    const pixels = async () => {
        await pauseForPaint();
        return canvas.screenshot({style:".nd-library-reset { visibility: hidden !important }", animations:"disabled"});
    };
    const initial = await pixels();
    const originalBounds = await modelBounds(page, initial);
    const x = area.x + area.width / 2, y = area.y + area.height / 2;
    await page.mouse.move(x, y);
    await page.mouse.wheel(0, -150);
    const closer = await pixels();
    assert.ok((await modelBounds(page, closer)).height > originalBounds.height + 8, "滚轮应缩放实际模型");
    await page.mouse.down();
    await page.mouse.move(x + 92, y + 36, {steps:10});
    await page.mouse.up();
    assert.ok(await imageDifference(page, closer, await pixels()) > .005, "拖动应旋转实际模型");
    await reset.click();
    let difference = 1;
    for (let frame = 0; frame < 4 && difference > .0025; frame++) {
        difference = await imageDifference(page, initial, await pixels());
    }
    assert.ok(difference <= .0025, "复位后视角仍有偏移，画面差异 " + difference);
    await capture(page, "技术员-示例三维.png");
    await preview.getByRole("button", {name:"退出示例", exact:true}).click();
    await preview.getByRole("heading", {name:"待关联模型", exact:true}).waitFor();
    assert.equal(await preview.locator("canvas").count(), 0);

    await preview.getByRole("button", {name:"预览示例模型", exact:true}).click();
    await reset.waitFor();
    await page.locator(".nd-al-item").filter({hasNotText:sampleCode}).first().click();
    await preview.getByRole("heading", {name:"待关联模型", exact:true}).waitFor();
    assert.equal(await preview.getByText("示例模型", {exact:true}).count(), 0);
    await rowFor(page).click();
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
        await rowFor(book).click();
        const priceCard = book.getByRole("region", {name:"当前单价", exact:true});
        assert.equal(number(await priceCard.locator("strong").innerText()), rate.price_per_unit);
        assert.equal(await previewFor(book).getByRole("button", {name:"预览示例模型", exact:true}).count(), 0);
        await capture(book, "核算员-辅料库.png");
        await book.getByRole("button", {name:"编辑档案", exact:true}).click();
        await formFor(book).getByText("三维模型与安装规则", {exact:true}).waitFor();
        const price = formFor(book).locator('[name="price_per_unit"] input');
        assert.equal(number(await price.inputValue()), rate.price_per_unit);
        assert.equal(await formFor(book).locator('[name="cad_model_id"]').count(), 0);
        await capture(book, "核算员-辅料档案.png");

        await book.goto(origin + "/odoo/auxiliary-prices");
        assert.equal(number(await legacyRow(book).locator('[name="price_per_unit"]').innerText()), rate.price_per_unit);

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
        await verifyExample(reader);
        await reader.getByRole("button", {name:"查看档案", exact:true}).click();
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
        const [after] = await call(costing, priceModel, "read", [[rate.id], ["price_per_unit", "cad_model_status"]]);
        assert.deepEqual(after, {id:rate.id, price_per_unit:rate.price_per_unit, cad_model_status:"unlinked"});
        console.log(JSON.stringify({menu:"辅料库", sameRateId:rate.id, price:rate.price_per_unit,
            quoteLink:true, engineeringReadOnly:true, modelPicker:true, rotate:true, zoom:true, reset:true, screenshots:5}));
    } finally { await browser.close(); }
}

verify().catch(error => {
    console.error(error);
    process.exitCode = 1;
});
