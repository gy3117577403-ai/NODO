// Local development acceptance. Temporarily edit only the AE-202 seeded trial price and restore it.
const assert = require("node:assert/strict");
const fs = require("node:fs");
const path = require("node:path");
const {chromium} = require("playwright");

const root = path.resolve(__dirname, "../..");
const out = path.join(root, "docs/验收/AE-202板料成本");
const origin = "http://127.0.0.1:8079";
const model = "nodo.cost.sheet.price";
const marker = "AE202-验收临时牌号";
const viewport = {width:1655, height:881};

async function rpc(context, route, params) {
    const response = await context.request.post(origin + route, {data:{jsonrpc:"2.0", method:"call", id:1, params}});
    const data = await response.json();
    if (data.error) throw Error(data.error.data?.message || data.error.message);
    return data.result;
}

function call(ctx, name, method, args, kwargs={}) {
    return rpc(ctx, "/web/dataset/call_kw/" + name + "/" + method, {model:name, method, args, kwargs});
}

async function signInRole(browser, role) {
    const login = role + "@nodo.test";
    const file = fs.readFileSync(path.join(root, "config/dev-accounts.local.md"), "utf8");
    const row = file.split(/\r?\n/).map(line => line.split("|").map(cell=>cell.trim())).find(cells=>cells[3] === login && cells[2] === "nodo_dev");
    if (!row) throw Error("未找到本机开发角色 " + role);
    const ctx = await browser.newContext({viewport});
    await rpc(ctx, "/web/session/authenticate", {db:"nodo_dev", login, password:row[4]});
    const session = await rpc(ctx, "/web/session/get_session_info", {});
    assert.equal(session.db,"nodo_dev");
    assert.ok(session.uid);
    return ctx;
}

async function saveField(page, name, value) {
    const input = page.locator('.o_form_view [name="' + name + '"] input');
    await input.fill(value);
    await input.press("Tab");
    const saved = page.waitForResponse(r => r.url().includes("/" + model + "/web_save") && r.ok());
    await page.locator(".o_form_button_save:visible").first().click();
    const result = await (await saved).json();
    assert.ok(!result.error, result.error?.message);
}

async function verify() {
    fs.mkdirSync(out, {recursive:true});
    const browser = await chromium.launch({channel:"chrome"});
    let writer, target;
    try {
        const engineer = await signInRole(browser,"engineering");
        writer = await signInRole(browser,"costing");
        const parts = await engineer.newPage(), materials = await engineer.newPage(), book = await writer.newPage();
        const errors = [];
        for (const p of [parts, materials, book]) p.on("pageerror", e => errors.push(e.message));

        const designs = await call(engineer, "nodo.draw.design", "list_designs", []);
        const design = designs.find(d=>d.source === "AE-202");
        assert.ok(design);
        const workUrl = origin + "/odoo/technical-workbench?design=" + design.id;
        await parts.goto(workUrl + "&tab=parts");
        const total = parts.locator("[data-total-cost]");
        const expectedTotal = async value => parts.waitForFunction(amount =>
            document.querySelector("[data-total-cost]")?.innerText.includes(amount), value, {timeout:45000});
        await expectedTotal("229.43");
        const prices = ["66.840","18.321","18.321","30.155","29.129","61.548","5.116"];
        assert.deepEqual(await parts.locator("[data-row-cost]").allTextContents(),prices);
        assert.match(await parts.locator("[data-usage-weight]").innerText(), /45\.886/);
        await parts.getByRole("button",{name:"选择右门板并查看展开图"}).click();
        const flat = parts.locator('[data-flat-key="door_right"] img');
        await parts.waitForFunction(() => document.querySelector('[data-flat-key="door_right"] img')?.naturalWidth > 0);
        const flatUrl = await flat.getAttribute("src");
        await parts.screenshot({path:path.join(out,"板料用量与逐件成本.png"),animations:"disabled"});

        await materials.goto(workUrl);
        await materials.getByRole("button",{name:"材料",exact:true}).click();
        const stock = materials.locator('[data-stock-key="door"]');
        await materials.waitForFunction(() => document.querySelector('[data-stock-key="door"] b')?.textContent === "5.00");
        await materials.locator('.nd-three-host:not([hidden]) canvas').waitFor({state:"visible"});
        await materials.evaluate(() => new Promise(resolve=>requestAnimationFrame(()=>requestAnimationFrame(resolve))));
        await materials.screenshot({path:path.join(out,"材料选择与库内价格.png"),animations:"disabled"});
        const settingsBefore = await call(engineer, "nodo.draw.design", "workspace", [[design.id]]);

        await book.goto(origin + "/odoo");
        await book.getByRole("button",{name:"成本库",exact:true}).click();
        const list = book.locator(".o_list_view .o_data_row");
        await list.first().waitFor();
        const query = [[["category","=","cold_rolled"],["thickness_mm","=",2],["grade","=",false],
                        ["supply_condition","=",false],["basis","=","trial"],["source_note","=","AE-202 样柜试算"]]];
        const records = await call(writer,model,"search_read",query,{fields:["id","price_per_kg"]});
        assert.equal(records.length,1,"仅允许修改唯一的本地样柜测试价");
        assert.equal(records[0].price_per_kg,5,"既有价格已被维护，请使用隔离样柜验证");
        target = records[0].id;
        await book.screenshot({path:path.join(out,"成本库与三条板料测试价.png"),animations:"disabled"});
        const row = list.filter({has:book.locator('[name="category"]',{hasText:"冷轧板"})})
            .filter({has:book.locator('[name="thickness_mm"]',{hasText:/^2(?:[.,]0+)?$/})});
        await row.click();
        await book.locator('.o_form_view [name="price_per_kg"] input').waitFor();
        let priceChangeCadRequests = 0;
        const onPriceChangeRequest = req => {
            if (/(?:request_sheet_usage|preview_cabinet|\/mesh$)/.test(req.url())) priceChangeCadRequests++;
        };
        parts.on("request",onPriceChangeRequest);
        const started = Date.now();
        await saveField(book, "price_per_kg", "6");
        await expectedTotal("241.29");
        await materials.waitForFunction(() => document.querySelector('[data-stock-key="door"] b')?.textContent === "6.00",
            null, {timeout:45000});
        const syncMs = Date.now() - started;
        assert.equal((await parts.locator('[data-usage-key="door_right"] [data-row-cost]').innerText()).trim(),"34.955");
        assert.equal((await parts.locator('[data-usage-key="wrap"] [data-row-cost]').innerText()).trim(),"66.840");
        assert.match(await stock.innerText(), /6\.00/);

        await saveField(book,"grade",marker);
        await parts.getByText("2 种待补价",{exact:true}).waitFor({timeout:45000});
        assert.equal(await total.count(),0);
        assert.equal(await parts.locator('[data-unit-price]').filter({hasText:"待补价"}).count(),2);
        await stock.getByText("该规格待补价",{exact:true}).waitFor({timeout:45000});
        await saveField(book,"grade","");
        await expectedTotal("241.29");
        await saveField(book,"price_per_kg","5");
        await expectedTotal("229.43");
        await materials.waitForFunction(() => document.querySelector('[data-stock-key="door"] b')?.textContent === "5.00",
            null, {timeout:45000});
        assert.equal(await flat.getAttribute("src"),flatUrl);
        parts.off("request",onPriceChangeRequest);
        assert.equal(priceChangeCadRequests,0);

        const chooser = materials.getByLabel("门板选用库内板料");
        const galv = await chooser.locator("option").filter({hasText:"镀锌板"}).getAttribute("value");
        await chooser.selectOption(galv);
        assert.equal(await materials.getByLabel("门板材料",{exact:true}).inputValue(),"galvanized");
        assert.equal(await materials.getByLabel("门板厚度",{exact:true}).inputValue(),"2.5");
        await materials.getByLabel("门板材料",{exact:true}).selectOption("stainless");
        await stock.getByText("该规格待补价",{exact:true}).waitFor();
        const after = await call(engineer,"nodo.draw.design","workspace",[[design.id]]);
        assert.deepEqual([after.edit_number,after.settings,after.jobs],
                         [settingsBefore.edit_number,settingsBefore.settings,settingsBefore.jobs]);
        await parts.goto(workUrl + "&tab=parts");
        await expectedTotal("229.43");
        assert.deepEqual(errors,[]);
        return {design:design.id,rows:prices.length,total:229.43,changedTotal:241.29,missingRows:2,
                syncMs,priceChangeCadRequests,geometryReused:true,stockChoice:true,restored:true,screenshots:3};
    } finally {
        try {
            if (target && writer) {
                const [rate] = await call(writer,model,"read",[[target],["grade","price_per_kg","basis","source_note"]]);
                if (rate.basis === "trial" && rate.source_note === "AE-202 样柜试算" &&
                    (!rate.grade || rate.grade === marker) && [5,6].includes(rate.price_per_kg) &&
                    (rate.grade === marker || rate.price_per_kg !== 5)) {
                    await call(writer,model,"write",[[target],{price_per_kg:5, grade:false}]);
                }
            }
        } finally { await browser.close(); }
    }
}

verify().then(result=>console.log(JSON.stringify(result))).catch(error=>{console.error(error);process.exitCode=1;});
