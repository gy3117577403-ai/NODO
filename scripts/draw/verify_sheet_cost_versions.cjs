// Local AE-202 only. Preserve both requested versions and restore the original trial price.
const assert = require("node:assert/strict");
const fs = require("node:fs");
const path = require("node:path");
const {chromium} = require("playwright");
const {call, signInRole, saveField} = require("./verify_sheet_costs.cjs");

const origin = "http://127.0.0.1:8079";
const out = path.resolve(__dirname, "../../docs/验收/AE-202板料核算版本");
const model = "nodo.draw.design";
const bookModel = "nodo.cost.sheet.price";
const seed = "AE-202 样柜试算";
const rateFields = ["category","grade","supply_condition","thickness_mm","price_per_kg","basis","source_note","active"];
const baseAmounts = ["66.840","18.321","18.321","30.155","29.129","61.548","5.116"];
const newAmounts = [...baseAmounts];
newAmounts.splice(3, 2, "36.187", "34.955");
const trialDoor = rate => rate.category === "cold_rolled" && rate.thickness_mm === 2 && !rate.grade &&
    !rate.supply_condition && rate.active && rate.source_note === seed && rate.basis === "trial";

async function liveTotal(page, total) {
    await page.waitForFunction(value => document.querySelector("[data-total-cost]")?.textContent.includes(value),
        total, {timeout:60000});
}

async function checkDetail(page, number) {
    const dialog = page.getByRole("dialog").filter({has:page.getByRole("heading",{name:"板料核算版本"})});
    await dialog.locator('[data-version-number="' + number + '"]').waitFor({timeout:20000});
    const total = number === 1 ? "229.43" : "241.29";
    assert.match(await dialog.locator("[data-version-total]").innerText(), new RegExp(total.replace(".","\\.")));
    const summary = await dialog.locator(".nd-history-summary").innerText();
    assert.match(summary, /测试价/);
    assert.match(summary, /45\.886/);
    assert.match(summary, /7\s*种\s*10\s*件/);
    const rows = dialog.locator("[data-version-key]");
    assert.deepEqual(await rows.locator("td:last-child").allTextContents(), number === 1 ? baseAmounts : newAmounts);
    assert.deepEqual(await rows.filter({has:page.getByText("待校核",{exact:true})})
        .evaluateAll(elements => elements.map(row => row.dataset.versionKey)), ["door","door_right","brace"]);
    if (number === 2) {
        assert.match(await dialog.locator("[data-version-delta]").innerText(), /\+11\.86/);
        const changes = dialog.locator("[data-change-key]");
        assert.deepEqual(await changes.evaluateAll(elements=>elements.map(row=>row.dataset.changeKey)), ["door","door_right"]);
        assert.match(await changes.nth(0).innerText(), /5\.00\s*→\s*6\.00 元\/kg[\s\S]*\+6\.031 元/);
        assert.match(await changes.nth(1).innerText(), /5\.00\s*→\s*6\.00 元\/kg[\s\S]*\+5\.826 元/);
    } else {
        assert.equal(await dialog.locator("[data-change-key]").count(), 0);
    }
    return dialog;
}

async function saveVersion(page, number) {
    await page.getByRole("button",{name:"保存核算版本",exact:true}).click();
    await page.waitForFunction(() => Boolean(document.querySelector("[data-version-number], .nd-sheet-usage [role=alert]")),
        null, {timeout:25000});
    const errors = page.locator('.nd-sheet-usage [role="alert"]');
    if (await errors.count()) throw Error(await errors.innerText());
    const dialog = await checkDetail(page, number);
    await dialog.getByRole("button",{name:/关闭|Close/}).first().click();
    await dialog.waitFor({state:"hidden"});
}

async function verify() {
    fs.mkdirSync(out,{recursive:true});
    const browser = await chromium.launch({channel:"chrome"});
    let writer, target, touched = false;
    try {
        const engineer = await signInRole(browser,"engineering");
        writer = await signInRole(browser,"costing");
        const work = await engineer.newPage(), book = await writer.newPage(), errors = [];
        for (const page of [work, book]) page.on("pageerror", error=>errors.push(error.message));
        const designs = await call(engineer,model,"list_designs",[]);
        const candidates = designs.filter(d=>d.source === "AE-202");
        assert.equal(candidates.length, 1, "需要唯一 AE-202 本机样柜");
        const id = candidates[0].id, url = origin + "/odoo/technical-workbench?design=" + id + "&tab=parts";
        const workCall = (method, ...args) => call(engineer, model, method, [[id], ...args]);
        const state = await workCall("workspace");
        const rates = () => call(writer,bookModel,"search_read",[[["source_note","=",seed]]],{fields:rateFields, order:"id"});
        const baseline = await rates();
        assert.equal(baseline.length,3);
        assert.ok(baseline.every(r=>r.price_per_kg === 5 && r.basis === "trial"));
        const targets = baseline.filter(trialDoor);
        assert.equal(targets.length,1);
        target = targets[0].id;
        const versions = await workCall("sheet_cost_versions");
        assert.ok(versions.length <= 2, "已有其他核算记录，停止样柜复验");
        for (const v of versions) {
            const {snapshot} = await workCall("read_sheet_cost_version", v.id);
            assert.equal(snapshot.edit, state.edit_number);
            assert.equal(snapshot.total, v.number === 1 ? 229.43 : 241.29);
        }
        await work.goto(url);
        await liveTotal(work,"229.43");
        assert.deepEqual(await work.locator("[data-row-cost]").allTextContents(), baseAmounts);
        if (!versions.length) await saveVersion(work, 1);
        if (versions.length < 2) {
            await book.goto(origin + "/odoo/sheet-costs/" + target);
            await book.locator('.o_form_view [name="price_per_kg"] input').waitFor();
            assert.equal(Number(await book.locator('.o_form_view [name="price_per_kg"] input').inputValue()),5);
            touched = true;
            await saveField(book,"price_per_kg","6");
            await liveTotal(work,"241.29");
            assert.deepEqual(await work.locator("[data-row-cost]").allTextContents(), newAmounts);
            await saveVersion(work, 2);
            await saveField(book,"price_per_kg","5");
            await liveTotal(work,"229.43");
        }
        assert.deepEqual(await rates(), baseline);
        touched = false;
        // Open the cabinet in a new tab after restoration, with no previously mounted workbench.
        await work.close();
        const reopened = await engineer.newPage();
        reopened.on("pageerror", error=>errors.push(error.message));
        await reopened.goto(url);
        await liveTotal(reopened,"229.43");
        await reopened.getByRole("button",{name:"选择左门板并查看展开图"}).click();
        await reopened.waitForFunction(() => document.querySelector('[data-flat-key="door"] img')?.naturalWidth > 0);
        await reopened.screenshot({path:path.join(out,"实时用量与已恢复价格.png"),animations:"disabled"});
        await reopened.getByRole("button",{name:"核算版本",exact:true}).click();
        const saved = await workCall("sheet_cost_versions");
        assert.deepEqual(saved.map(v=>v.number),[2,1]);
        const choose = reopened.getByLabel("查看核算版本");
        for (const [number,file] of [[1,"第一版恢复后.png"],[2,"第二版与左右门板差额.png"]]) {
            await choose.selectOption(String(saved.find(v=>v.number === number).id));
            const dialog = await checkDetail(reopened, number);
            assert.equal(await choose.inputValue(), String(saved.find(v=>v.number === number).id));
            const labels = await dialog.locator(".nd-history-audit").innerText();
            assert.match(labels,/设计编辑号/);
            await reopened.screenshot({path:path.join(out,file),animations:"disabled"});
        }
        const after = await workCall("workspace");
        assert.deepEqual([after.settings,after.edit_number,after.jobs], [state.settings,state.edit_number,state.jobs]);
        assert.deepEqual(errors,[]);
        return {id,edit:after.edit_number,versions:saved.map(v=>({id:v.id,number:v.number})),totals:[229.43,241.29],
            delta:11.86,changed:["左门板 +6.031","右门板 +5.826"],pending:["左门板","右门板","门内加强件"],
            weight:45.886,restored:5,screenshots:3};
    } finally {
        try {
            if (touched) {
                const [rate] = await call(writer,bookModel,"read",[[target],rateFields]);
                if (trialDoor(rate) && rate.price_per_kg === 6) {
                    await call(writer,bookModel,"write",[[target],{price_per_kg:5}]);
                    const [restored] = await call(writer,bookModel,"read",[[target],["price_per_kg"]]);
                    assert.equal(restored.price_per_kg,5);
                }
            }
        } finally {await browser.close();}
    }
}

verify().then(result=>console.log(JSON.stringify(result))).catch(error=>{console.error(error);process.exitCode=1;});
