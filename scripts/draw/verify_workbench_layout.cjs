// Targeted browser acceptance. The engineering run creates a synthetic design on nodo_dev.
const assert = require("node:assert/strict");
const fs = require("node:fs");
const path = require("node:path");
const {chromium} = require("playwright");

const root = path.resolve(__dirname, "../..");
const origin = "http://127.0.0.1:8079";
const workbench = origin + "/odoo/technical-workbench";
const navigation = {waitUntil:"domcontentloaded", timeout:30000};
const destination = path.resolve(process.argv[2] || path.join(root, ".nodo-draw/output/playwright/workspace-layout"));
const mode = process.argv[3] || "all";
assert(["all", "layout", "materials"].includes(mode), "选择 layout、materials 或 all");
const exact = (page, name) => page.getByRole("button", {name, exact:true});
const tool = (page, name) => page.getByRole("group", {name:"设计工具", exact:true}).getByRole("button", {name, exact:true});
const rpc = params => ({jsonrpc:"2.0", method:"call", id:1, params});
const meshResponse = response => /\/nodo\/draw\/file\/\d+\/mesh$/.test(response.url()) && response.ok();
const activeFace = page => page.locator('.nd-face-tile[aria-pressed="true"]');
const board = (page, face) => page.locator(`.nd-face-tile[data-face="${face}"]`);
const field = (page, label) => page.getByLabel(label, {exact:true});

async function settleCanvas(page) {
    await page.evaluate(() => new Promise(resolve => requestAnimationFrame(() => requestAnimationFrame(resolve))));
}

async function screenshot(page, name) {
    await page.evaluate(() => document.fonts.ready.then(() => true));
    await settleCanvas(page);
    await page.screenshot({path:path.join(destination, name + ".png"), animations:"disabled"});
}

async function expandNav(page) {
    const expand = exact(page, "展开应用侧栏");
    if (await expand.isVisible()) {
        await expand.click();
        await page.waitForFunction(() => document.querySelector(".nd-work")?.getBoundingClientRect().x >= 215);
    }
}

async function chooseDesign(page, label) {
    const selector = field(page, "选择设计");
    await selector.selectOption({label});
    await selector.locator("option:checked").filter({hasText: label}).waitFor({state:"attached"});
}

async function checkLayout(page) {
    await page.goto(workbench, navigation);
    await page.locator(".nd-viewport canvas").waitFor();
    await expandNav(page);
    const report = [];
    for (const width of [1651, 1173]) {
        await page.setViewportSize({width, height:871});
        await settleCanvas(page);
        assert.equal(await page.locator(".nd-work h1").count(), 0);
        const designBar = await page.locator(".nd-workbar").boundingBox();
        assert(designBar.height <= 52, "设计工具栏应为一行");
        const chooser = await field(page, "选择设计").boundingBox();
        const generate = await exact(page, "一键出图").boundingBox();
        const gap = generate.x - (chooser.x + chooser.width);
        assert(gap >= 0 && gap < 30, "出图按钮与柜体选择间距 " + gap);
        await screenshot(page, "after-"+width+"-设计");
        await exact(page, "图纸与版本").click();
        await field(page, "图纸版本").selectOption({label:"V06 · 已生成"});
        const drawing = page.locator(".nd-drawing-surface img");
        await drawing.waitFor();
        assert.equal(await exact(page, "一键出图").count(), 0);
        assert.equal(await page.getByRole("heading", {name:"图纸成果",exact:true}).count(), 0);
        const graphics = page.locator(".nd-drawing-surface");
        const before = await graphics.boundingBox();
        const archiveBar = await page.locator(".nd-workbar").boundingBox();
        assert(archiveBar.height <= 52 && before.y < 170 && before.y + before.height <= 871, "图纸应在首屏获得完整视口");
        await screenshot(page, "after-"+width+"-图纸");
        await exact(page, "收起目录").click();
        await page.locator(".nd-sheet-list").waitFor({state:"detached"});
        const full = await graphics.boundingBox();
        assert(full.width - before.width >= 140, "收起目录后应把横向空间交给图纸");
        await exact(page, "展开目录").click();
        await exact(page, "下载").click();
        await page.getByRole("link", {name:/下载.*总装.* DWG/}).waitFor();
        await exact(page, "版本详情").click();
        await page.locator(".nd-version-details").getByText(/18 张 DWG/).waitFor();
        await page.keyboard.press("Escape");
        await page.locator(".nd-version-details").waitFor({state:"detached"});
        report.push({width, height:871, designBarHeight:designBar.height, drawingSurface:before,
            archiveBarHeight:archiveBar.height, directoryClosedWidth:full.width});
        await exact(page, "设计视图").click();
    }
    const panel = page.locator(".nd-inspector");
    const splitter = page.getByRole("separator", {name:"调整设计栏宽度"});
    const initial = await panel.boundingBox();
    const grip = await splitter.boundingBox();
    const start = {x:grip.x+grip.width/2, y:grip.y+grip.height/2};
    await page.mouse.move(start.x, start.y);
    await page.mouse.down();
    await page.mouse.move(start.x+66, start.y, {steps:10});
    await page.mouse.up();
    const wider = await panel.boundingBox();
    assert(wider.width >= initial.width+60, "拖动分隔线应加宽左栏");
    await exact(page, "收起设计栏").click();
    const folded = await panel.boundingBox();
    assert(folded.width < 80, "左栏应收成窄栏");
    await exact(page, "展开设计栏").click();
    assert.equal((await panel.boundingBox()).width, wider.width, "重新展开应恢复宽度");
    return {viewports:report, inspector:{initial:initial.width, wider:wider.width, folded:folded.width}};
}

async function checkFaces(page, label, ids, keepDraft) {
    const expected = page.waitForResponse(meshResponse);
    if (label.startsWith("AE-101")) await page.goto(workbench, navigation);
    else await chooseDesign(page, label);
    const mesh = await (await expected).json();
    await expandNav(page);
    await exact(page, "二维").click();
    await activeFace(page).waitFor();
    const faces = await page.locator(".nd-face-tile").evaluateAll(buttons => buttons.map(button => button.dataset.face));
    assert.deepEqual(faces, ids);
    const canvas = page.getByLabel("板面开孔定位", {exact:true});
    for (const id of ids) {
        await board(page, id).click();
        const geometry = mesh.faces.find(row => row.id === id);
        assert(geometry, id);
        assert.equal(await activeFace(page).getAttribute("data-face"), id);
        const caption = await page.locator(".nd-board-caption").innerText();
        assert(caption.includes(`${geometry.width.toFixed(1)} × ${geometry.height.toFixed(1)} mm`), caption);
        await settleCanvas(page);
        const spot = await canvas.boundingBox();
        await page.mouse.click(Math.round(spot.x+spot.width/2),Math.round(spot.y+spot.height/2));
        await settleCanvas(page);
        const u = Number(await field(page, "横向 U").inputValue());
        const v = Number(await field(page, "纵向 V").inputValue());
        assert(Math.abs(u-geometry.width/2)<1, `${id} U ${u}，预期 ${geometry.width/2}`);
        assert(Math.abs(v-geometry.height/2)<1, `${id} V ${v}，预期 ${geometry.height/2}`);
    }
    await page.locator(".nd-face-overview summary").click();
    await exact(page, "正视选择板面").click();
    await page.locator(".nd-front-faces").getByRole("button",{name:"安装板",exact:true}).click();
    assert.equal(await activeFace(page).getAttribute("data-face"), "mount");
    await page.locator(".nd-face-overview summary").click();
    if (keepDraft) {
        await board(page, "top").click();
        await field(page, "横向 U").fill("71");
        await field(page, "纵向 V").fill("63");
        await exact(page, "添加孔位").click();
        await page.locator(".nd-bomrow .nd-link").filter({hasText:"71"}).click();
        await field(page, "横向 U").fill("73");
        await board(page, "mount").click();
        await field(page, "横向 U").fill("123");
        await field(page, "纵向 V").fill("76");
        await exact(page, "添加孔位").click();
        await page.locator(".nd-bomrow .nd-link").filter({hasText:"123"}).waitFor();
        await tool(page, "材料").click();
        assert.equal(await field(page, "安装板材料").inputValue(), "cold_rolled", "旧稿材料须保留");
        await page.getByText("查看孔位",{exact:true}).waitFor();
        await tool(page, "孔位").click();
        await page.locator(".nd-bomrow .nd-link").filter({hasText:"123"}).waitFor();
        await board(page, "top").click();
        assert.equal(await field(page, "横向 U").inputValue(), "73");
        await exact(page, "应用孔位修改").click();
        assert.equal(await page.locator(".nd-bomrow .nd-link").filter({hasText:"123"}).count(), 0);
        await page.locator(".nd-bomrow .nd-link").filter({hasText:"73"}).waitFor();
        await board(page, "door").click();
        await screenshot(page, "after-1651-二维");
    } else {
        await board(page, "door_right").click();
        await screenshot(page, "after-1651-双门右板");
    }
    return {faces, boardCount:faces.length, draftVerified:keepDraft, dimensions:mesh.faces.map(({id,width,height})=>({id,width,height}))};
}

async function rpcResult(request, model, method, args) {
    const response = await request.post(`${origin}/web/dataset/call_kw/${model}/${method}`,
        {data:rpc({model,method,args,kwargs:{}})});
    const payload = await response.json();
    assert(!payload.error, payload.error?.data?.message || payload.error?.message);
    return payload.result;
}

async function apply(page, buttonName) {
    const rpcCall = page.waitForResponse(response => response.url().endsWith("/apply_design"));
    await exact(page, buttonName).click();
    const payload = await (await rpcCall).json();
    assert(payload.result?.job_id, payload.error?.data?.message || "没有生成 CAD 任务");
    return payload.result.job_id;
}

async function waitForPreview(page, job) {
    const url = `${origin}/nodo/draw/file/${job}/mesh`;
    for (let attempt=0; attempt<150; attempt++) {
        const response = await page.request.get(url);
        if (response.ok()) return response.json();
        const error = await page.locator(".nd-error").textContent({timeout:1300}).catch(()=>null);
        if (error?.trim()) throw Error(error.trim());
        await new Promise(resolve => setTimeout(resolve, 450));
    }
    assert.fail("材料预览计算未完成");
}

async function editByPart(page) {
    await exact(page, "按零件").click();
}

async function setTopOverride(page) {
    await field(page, "顶板独立材料").selectOption("stainless");
    await field(page, "顶板独立厚度").fill("1.8");
    await exact(page, "顶板材料详情").click();
    await field(page, "顶板牌号").fill("304");
    await field(page, "顶板来料状态或镀层").fill("2B");
    await exact(page, "顶板材料详情").click();
}

async function checkMaterials(page) {
    const model = "nodo.draw.design";
    const payload = {source:"AE-304",source_version:"1",title:"混合板材壁挂柜",quantity:1,
        kind:"single",width:420,height:340,depth:235,lines:[]};
    const intake = await rpcResult(page.request, model, "handoff_bom", [payload]);
    const design = intake.design_id;
    await page.goto(workbench + "?design=" + design, navigation);
    await tool(page, "材料").click();
    assert.equal(await field(page, "安装板材料").inputValue(), "galvanized");
    await editByPart(page);
    assert.equal(await field(page, "加强件（左右）独立厚度").inputValue(), "1.5");
    await setTopOverride(page);
    await exact(page, "返回分组").click();
    await field(page, "箱体材料").selectOption("galvanized");
    await field(page, "箱体厚度").fill("1.6");
    await editByPart(page);
    assert.equal(await field(page, "顶板独立材料").inputValue(), "stainless");
    assert.equal(await field(page, "顶板独立厚度").inputValue(), "1.8");
    assert.equal(await field(page, "围板独立厚度").inputValue(), "1.6");
    assert.equal(await field(page, "加强件（左右）独立厚度").inputValue(), "1.5");
    await exact(page, "顶板恢复跟随").click();
    assert.equal(await field(page, "顶板独立材料").inputValue(), "galvanized");
    assert.equal(await field(page, "顶板独立厚度").inputValue(), "1.6");
    await exact(page, "返回分组").click();
    await field(page, "箱体材料").selectOption("cold_rolled");
    await editByPart(page);
    await setTopOverride(page);
    const preview = await apply(page, "应用材料并预览");
    const mesh = await waitForPreview(page, preview);
    for (const [id, gauge] of [["top",1.8],["bottom",1.6],["back",1.6],["door",2],["mount",2.5]]) {
        assert.equal(mesh.faces.find(face => face.id === id)?.thickness, gauge, id+" 预览板厚");
    }
    await page.reload(navigation);
    await chooseDesign(page, payload.source + " · " + payload.title);
    await tool(page, "材料").click();
    assert.equal(await field(page, "箱体厚度").inputValue(), "1.6");
    await editByPart(page);
    assert.equal(await field(page, "顶板独立材料").inputValue(), "stainless");
    assert.equal(await field(page, "顶板独立厚度").inputValue(), "1.8");
    await exact(page, "顶板材料详情").click();
    assert.equal(await field(page, "顶板牌号").inputValue(), "304");
    await exact(page, "顶板材料详情").click();
    await expandNav(page);
    await page.locator(".nd-viewport canvas").waitFor();
    await screenshot(page, "after-1651-按零件材料");

    const job = await apply(page, "一键出图");
    console.log("生成混合板材样例，任务",job);
    const versions = field(page, "图纸版本");
    const selected = versions.locator("option:checked");
    await selected.filter({hasText:/已生成|生成失败/}).waitFor({state:"attached",timeout:600000});
    const label = (await selected.textContent()).trim();
    if (!label.includes("已生成")) throw Error(await page.locator(".nd-archive-state").textContent());
    const revision = label.split(" ")[0];
    const fileDir = path.join(destination, "材料出图");
    fs.mkdirSync(fileDir,{recursive:true});
    const files = [];
    for (const [name, filename] of [["整套图包","工程图包.zip"],["整柜 STEP","整柜.step"],["零件清单","零件清单.csv"]]) {
        await exact(page, "下载").click();
        const waiting = page.waitForEvent("download");
        await page.getByRole("link",{name,exact:true}).click();
        const file = await waiting;
        assert(file.url().includes(`/file/${job}/`));
        await file.saveAs(path.join(fileDir,filename));
        files.push(filename);
    }
    return {design, preview, job, revision, source:payload.source, files};
}

async function main() {
    fs.mkdirSync(destination,{recursive:true});
    const browser = await chromium.launch({channel:"chrome"});
    const errors = [];
    try {
        const context = await browser.newContext({storageState:path.join(root,".nodo-draw/dev-session.local.json"),
            viewport:{width:1651,height:871},deviceScaleFactor:1});
        const response = await context.request.post(origin+"/web/session/get_session_info",{data:rpc({})});
        assert.equal((await response.json().catch(()=>({}))).result?.db,"nodo_dev","请先建立已登录的本地技术会话");
        async function page(){
            const tab = await context.newPage();
            tab.setDefaultTimeout(12000);
            tab.on("pageerror",error=>errors.push(error.message));
            tab.on("console",message=>{
                if (message.type()==="error" && /OwlError|Failed to compile/.test(message.text())) errors.push(message.text());
            });
            return tab;
        }
        const result = {};
        if (mode !== "materials") {
            const layout = await page();
            result.layout = await checkLayout(layout);
            const single = await page();
            result.single = await checkFaces(single, "AE-101 · 壁挂控制箱", ["door","mount","top","bottom","back","left","right"], true);
            const double = await page();
            await double.goto(workbench, navigation);
            await double.locator(".nd-viewport canvas").waitFor();
            result.double = await checkFaces(double, "AE-202 · 双门配电箱",
                ["door","door_right","mount","top","bottom","back","left","right"], false);
        }
        if (mode !== "layout") result.materials = await checkMaterials(await page());
        assert.deepEqual(errors,[]);
        const json = JSON.stringify(result,null,2)+"\n";
        fs.writeFileSync(path.join(destination, `验收-${mode}.json`),json);
        console.log(json);
    } finally { await browser.close(); }
}
main().catch(error=>{console.error(error);process.exitCode=1;});
