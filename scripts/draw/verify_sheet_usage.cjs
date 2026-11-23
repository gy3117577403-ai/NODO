// Read-only acceptance on the AE-202 development sample with the technical session.
const assert = require("node:assert/strict");
const crypto = require("node:crypto");
const fs = require("node:fs");
const path = require("node:path");
const {chromium} = require("playwright");
const {drawWorkspace} = require("./verify_selection.cjs");

const root = path.resolve(__dirname, "../..");
const out = path.join(root, "docs/验收/AE-202板料用量");
const url = "http://127.0.0.1:8079/odoo/technical-workbench";
const expected = [
    ["wrap", "围板", "1.135281", 1, "13.368"], ["top", "顶板", "0.311183", 1, "3.664"],
    ["bottom", "底板", "0.311182", 1, "3.664"], ["door", "左门板", "0.384146", 1, "6.031"],
    ["door_right", "右门板", "0.371068", 1, "5.826"], ["mount", "安装板", "0.627239", 1, "12.310"],
    ["brace", "门内加强件", "0.021724", 4, "1.023"],
];
const button = (page, name) => page.getByRole("button", {name, exact:true});
const table = page => page.getByRole("table", {name:"逐件板料用量"});

async function openUsage(page) {
    await button(page, "零件").click();
    await table(page).waitFor({timeout:90000});
    assert.match(await page.locator(".nd-usage-summary").innerText(), /45\.886\s*kg/);
    assert.match(await page.locator(".nd-usage-summary").innerText(), /7 种 · 10 件/);
    assert.match(await page.locator(".nd-usage-summary").innerText(), /3\.226993 m²/);
}

async function selectSheet(page, key, name) {
    await button(page, "选择" + name + "并查看展开图").click();
    await page.waitForFunction(key => {
        const img = document.querySelector(`[data-flat-key="${key}"] img`);
        return img && img.complete && img.naturalWidth > 0 && !img.hidden && img.src.endsWith("/" + key);
    }, key);
    await page.evaluate(() => new Promise(resolve => requestAnimationFrame(() => requestAnimationFrame(resolve))));
}

async function highlightedPixels(page, png) {
    return page.evaluate(async data => {
        const response = await fetch("data:image/png;base64," + data);
        const image = await createImageBitmap(await response.blob());
        const ctx = new OffscreenCanvas(image.width, image.height).getContext("2d");
        ctx.drawImage(image,0,0);
        image.close();
        const pixels = ctx.getImageData(0,0,ctx.canvas.width,ctx.canvas.height).data;
        let count = 0;
        for (let i = 0; i < pixels.length; i += 4) {
            if (pixels[i+1] > pixels[i]+28 && pixels[i+1] > pixels[i+2]+6) count++;
        }
        return count;
    }, png.toString("base64"));
}

async function main() {
    fs.mkdirSync(out, {recursive:true});
    const browser = await chromium.launch({channel:"chrome"});
    try {
        const page = await browser.newPage({viewport:{width:1655,height:881}, deviceScaleFactor:1,
            storageState:path.join(root, ".nodo-draw/dev-session.local.json")});
        const errors = [];
        page.on("pageerror", error => errors.push(error.message));
        await page.goto(url);
        const select = page.getByLabel("选择设计", {exact:true});
        const designOption = select.locator("option").filter({hasText:"AE-202 · 双开门基础柜"});
        const designId = await designOption.getAttribute("value");
        await page.goto(url + "?design=" + designId);
        await page.waitForFunction(id => document.querySelector(".nd-design-choice")?.value === id, designId);
        const before = await drawWorkspace(page);
        assert.equal(before.bom.source, "AE-202");
        await openUsage(page);
        const rows = table(page).locator("tbody tr");
        assert.equal(await rows.count(), 7);
        assert.deepEqual(await rows.filter({hasText:"待校核"}).evaluateAll(items => items.map(r=>r.dataset.usageKey)),
            ["door", "door_right", "brace"]);
        await selectSheet(page,"door_right","右门板");
        await page.screenshot({path:path.join(out,"用量表与右门展开.png"),animations:"disabled"});

        await button(page,"拆解").click();
        await button(page,"完全展开").click();
        await button(page,"拆解").click();
        const seen = new Set();
        for (const [key, name, area, quantity, kg] of expected) {
            await selectSheet(page,key,name);
            const cells = await table(page).locator(`tr[data-usage-key="${key}"] td`).allTextContents();
            assert.deepEqual(cells.slice(1,4), [String(quantity),area,kg]);
            const rendered = await page.locator(".nd-three-host canvas").screenshot();
            assert.ok(await highlightedPixels(page, rendered) > 40, name + "在三维中应有可见的选中色");
            seen.add(crypto.createHash("sha256").update(rendered).digest("hex"));
        }
        assert.equal(seen.size,7,"七种板件的三维选中画面应各不相同");
        const instances = page.getByRole("group",{name:"加强件安装位置"});
        assert.equal(await instances.locator('button[aria-pressed="true"]').count(),4);
        await page.screenshot({path:path.join(out,"四件加强件与切割孔.png"),animations:"disabled"});
        await button(page,"零件结构").click();
        assert.equal(await page.locator('[data-part-id^="brace_"] .nd-part-name[aria-pressed="true"]').count(),4);
        await button(page,"板料用量").click();
        await selectSheet(page,"brace","门内加强件");
        for (const instance of await instances.getByRole("button").all()) {
            await instance.click();
            assert.equal(await instances.locator('button[aria-pressed="true"]').count(),1);
            assert.equal(await instance.getAttribute("aria-pressed"),"true");
        }
        await button(page,"放大图纸").click();
        assert.equal(await page.getByLabel("图纸缩放比例").innerText(),"125%");
        await button(page,"适应窗口").click();
        const usageUrl = await page.locator("[data-flat-key] img").getAttribute("src");
        await button(page,"规格").click();
        await page.getByLabel("柜宽",{exact:true}).fill("1010");
        await button(page,"零件").click();
        await page.getByText("请保存并预览已修改的柜体，再查看板料用量").waitFor();
        assert.equal(await table(page).count(),0);

        await page.goto(url + "?design=" + before.id + "&tab=parts");
        await table(page).waitFor();
        assert.equal(await button(page,"零件").getAttribute("aria-pressed"),"true");
        assert.match(await page.locator(".nd-usage-summary").innerText(), /45\.886\s*kg/);
        await selectSheet(page,"brace","门内加强件");
        assert.equal(await page.locator("[data-flat-key] img").getAttribute("src"),usageUrl);
        const after = await drawWorkspace(page);
        assert.deepEqual([after.edit_number,after.settings,after.jobs],[before.edit_number,before.settings,before.jobs]);
        assert.deepEqual(errors,[]);
        console.log(JSON.stringify({design:before.id, rows:7, pieces:10, area:3.226993, weight:45.886,
            review:["左门板","右门板","门内加强件"], distinct3dSelections:seen.size, braceInstances:4,
            zoom:true, reopenedSameJob:true, staleDraftHidden:true, screenshots:2}));
    } finally { await browser.close(); }
}
main().catch(error=>{console.error(error);process.exitCode=1;});
