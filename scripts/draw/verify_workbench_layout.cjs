// Targeted browser acceptance. The engineering run creates a synthetic design on nodo_dev.
const assert = require("node:assert/strict");
const {createHash} = require("node:crypto");
const fs = require("node:fs");
const path = require("node:path");
const {chromium} = require("playwright");

const root = path.resolve(__dirname, "../..");
const origin = "http://127.0.0.1:8079";
const workbench = origin + "/odoo/technical-workbench";
const navigation = {waitUntil:"domcontentloaded", timeout:30000};
const destination = path.resolve(process.argv[2] || path.join(root, ".nodo-draw/output/playwright/workspace-layout"));
const mode = process.argv[3] || "all";
assert(["all", "layout", "materials", "toolbar", "cabinet-preview", "reference-output", "parts", "hole-editing"].includes(mode),
    "选择 layout、materials、toolbar、cabinet-preview、reference-output、parts、hole-editing 或 all");
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

async function measureToolbar(page) {
    const toolbar = page.locator(".o_main_navbar > .nd-workbar-slot > .nd-workbar");
    await toolbar.waitFor();
    assert.equal(await page.locator(".nd-work .nd-workbar").count(), 0);
    assert.equal(await page.locator(".o_main_navbar > .o_menu_brand").isVisible(), false);
    assert.equal(await page.locator(".o_main_navbar > .o_menu_sections").isVisible(), false);
    return toolbar.evaluate(element => {
        const bar = element.getBoundingClientRect();
        const navbar = element.closest(".o_main_navbar").getBoundingClientRect();
        const tray = document.querySelector(".o_main_navbar > .o_menu_systray").getBoundingClientRect();
        const controls = [...element.querySelectorAll("button, select, .nd-tag")].map(node => node.getBoundingClientRect());
        return {
            height:bar.height, navbarHeight:navbar.height,
            oneRow:controls.every(control => Math.abs(control.top + control.height / 2 - (bar.top + bar.height / 2)) < 1),
            fits:controls.every(control => {
                const alignsWithTray = control.top < tray.bottom - 1 && control.bottom > tray.top + 1;
                return control.left >= bar.left - 1 && control.right <= navbar.right + 1 &&
                    (!alignsWithTray || control.right <= tray.left + 1);
            }),
        };
    });
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
        assert.equal(await page.locator(".nd-inspector h2").count(), 0);
        const designBar = await measureToolbar(page);
        assert(designBar.oneRow && designBar.fits, `设计工具栏应为一行且避开系统区 ${width}`);
        const stage = await page.locator(".nd-stage").boundingBox();
        assert(stage.y - designBar.navbarHeight <= 12, `主视口应紧接顶栏 ${width}`);
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
        const archiveBar = await measureToolbar(page);
        assert(archiveBar.oneRow && archiveBar.fits, `阅图工具栏应为一行且避开系统区 ${width}`);
        assert(before.y <= 110 && before.y + before.height <= 871, "图纸应在首屏获得完整视口");
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
        report.push({width, height:871, designBar, stage, drawingSurface:before, archiveBar, directoryClosedWidth:full.width});
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

async function checkToolbarActions(page) {
    const toolbar = page.getByRole("toolbar", {name:"柜体设计工具栏"});
    const button = name => toolbar.getByRole("button", {name, exact:true});
    const sideButton = name => page.locator(".o_nodo_app_sidebar").getByRole("button", {name, exact:true});
    await button("二维").click();
    await activeFace(page).waitFor();
    assert.equal(await page.locator(".nd-face-tile").count(), 7);
    await screenshot(page, "after-1173-二维");
    await page.setViewportSize({width:1651, height:871});
    await tool(page, "材料").click();
    await exact(page, "按零件").click();
    await field(page, "顶板独立厚度").waitFor();
    await screenshot(page, "after-1651-按零件材料");
    await button("三维").click();
    await page.locator(".nd-three-host canvas").waitFor();
    await chooseDesign(page, "AE-202 · 双门配电箱");
    await page.locator(".nd-foot").getByText("AE 双开门", {exact:true}).waitFor();
    await button("二维").click();
    await board(page, "door_right").click();
    assert.equal(await activeFace(page).getAttribute("data-face"), "door_right");
    await screenshot(page, "after-1651-双门右板");
    await chooseDesign(page, "AE-101 · 壁挂控制箱");
    await page.locator(".nd-foot").getByText("AE 单开门", {exact:true}).waitFor();
    await page.setViewportSize({width:1173, height:871});
    const cabinet = field(page, "选择设计");
    const current = await cabinet.inputValue();
    const width = field(page, "柜宽");
    await width.fill("0");
    const response = page.waitForResponse(item => item.request().method() === "POST" &&
        item.url().endsWith("/nodo.draw.design/apply_design"));
    await button("一键出图").click();
    const request = await response;
    assert.equal(request.request().postDataJSON().params.args.at(-1), "generate");
    assert.match((await request.json()).error?.data?.message ?? "", /柜宽须在/);
    await page.getByRole("alert").filter({hasText:"柜宽须在"}).waitFor();

    const switchPrompt = page.waitForEvent("dialog");
    const switching = cabinet.selectOption({label:"AE-202 · 双门配电箱"});
    const switchDialog = await switchPrompt;
    assert.match(switchDialog.message(), /切换柜体/);
    await switchDialog.dismiss();
    await switching;
    assert.equal(await cabinet.inputValue(), current);
    assert.equal(await width.inputValue(), "0");

    const leavePrompt = page.waitForEvent("dialog");
    const leaving = sideButton("讨论").click();
    const leaveDialog = await leavePrompt;
    assert.match(leaveDialog.message(), /放弃未保存/);
    await leaveDialog.dismiss();
    await leaving;
    assert.equal(await width.inputValue(), "0");
    const discardPrompt = page.waitForEvent("dialog");
    const discarding = sideButton("讨论").click();
    await (await discardPrompt).accept();
    await discarding;
    await toolbar.waitFor({state:"detached"});
    await page.locator(".o_main_navbar > .o_menu_brand").filter({hasText:"讨论"}).waitFor();
    await sideButton("技术工作台").click();
    await toolbar.waitFor();
    assert((await measureToolbar(page)).oneRow);
    await button("图纸与版本").click();
    await page.locator(".nd-drawing-surface img").waitFor();
    for (const width of [820, 412]) {
        await page.setViewportSize({width, height:871});
        await settleCanvas(page);
        assert((await measureToolbar(page)).fits, `窄视窗 ${width} 的控件应位于顶栏内`);
        await button("下载").click();
        await page.getByRole("link", {name:"整柜 STEP", exact:true}).waitFor();
        await page.keyboard.press("Escape");
        await page.getByRole("link", {name:"整柜 STEP", exact:true}).waitFor({state:"detached"});
    }
    return {designSwitch:true, viewSwitch:true, generateValidated:true, draftPreserved:true, otherAppRestored:true, narrowWidths:[820,412]};
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

async function verifyOriginalSheet(page, kind) {
    const base = path.join(root, ".nodo-draw/exchange/reference", kind);
    const sheets = JSON.parse(fs.readFileSync(path.join(base, "index.json"), "utf8"));
    assert.equal(sheets.length, kind === "single" ? 14 : 15);
    const drawing = `/nodo/draw/reference/${kind}/${sheets[0].key}`;
    await page.waitForFunction(url => {
        const image = document.querySelector(".nd-drawing-surface img");
        return image?.getAttribute("src") === url && image.naturalWidth > 0;
    }, drawing + "/svg");
    assert.equal(await page.locator(".nd-sheet-list button").count(), sheets.length);
    const dimensions = kind === "single" ? "380 × 300 × 210 mm" : "1000 × 700 × 300 mm";
    assert.equal(await field(page, "原图尺寸（宽 × 高 × 深）").innerText(), dimensions);
    await screenshot(page, kind === "single" ? "单开门基础原图" : "双开门基础原图");
    await exact(page, "下载").click();
    const link = page.getByRole("link", {name:/下载.*DWG/});
    assert.equal(await link.getAttribute("href"), drawing + "/dwg");
    const response = await page.request.get(origin + drawing + "/dwg");
    assert(response.ok());
    assert.equal(createHash("sha256").update(await response.body()).digest("hex"), sheets[0].sha256);
    await page.keyboard.press("Escape");
    return {sheets:sheets.length, dimensions, originalName:sheets[0].filename};
}

async function checkCabinetPreview(page) {
    await page.setViewportSize({width:1173, height:871});
    const singleBase = page.waitForResponse(async response => {
        if (!meshResponse(response)) return false;
        const mesh = await response.json();
        return mesh.parameters.configuration.kind === "single" && !mesh.parameters.accessories.length && !mesh.parameters.holes.length;
    }, {timeout:75000});
    await page.goto(workbench, navigation);
    await expandNav(page);
    const modelCaption = kind => page.locator(".nd-foot").getByText(`AE ${kind}`, {exact:true});
    const host = page.locator(".nd-three-host");
    const indicator = page.getByText("正在生成双开门预览", {exact:true});
    await modelCaption("单开门").waitFor({timeout:75000});
    await host.locator("canvas").waitFor();
    const single = await (await singleBase).json();
    assert.equal(single.faces.length, 7);
    const id = Number(await field(page, "选择设计").inputValue());
    const workspace = () => rpcResult(page.request, "nodo.draw.design", "workspace", [[id]]);
    const before = await workspace();
    assert.equal(before.bom.source, "AE-101");
    assert.equal(before.settings.kind, "single");
    assert.deepEqual([before.settings.width, before.settings.height, before.settings.depth], [420, 340, 235]);
    await screenshot(page, "AE-101-单门");

    const draftRequest = page.waitForResponse(response => response.url().endsWith("/nodo.draw.design/preview_cabinet"));
    const draftMesh = page.waitForResponse(meshResponse, {timeout:75000});
    const start = Date.now();
    await exact(page, "双开门").click();
    await indicator.waitFor();
    assert.equal(await host.isVisible(), false, "计算时只显示状态而非单门模型");
    await screenshot(page, "AE-101-双门计算中");
    const {result:jobId} = await (await draftRequest).json();
    assert(Number.isInteger(jobId));
    const result = await draftMesh;
    assert(result.url().endsWith(`/file/${jobId}/mesh`));
    const mesh = await result.json();
    const rightDoor = mesh.faces.find(board => board.id === "door_right");
    assert.equal(mesh.parameters.configuration.kind, "double");
    assert.deepEqual(mesh.dimensions, {width:420, height:340, depth:235});
    assert.deepEqual(mesh.parameters.accessories, []);
    assert.deepEqual(mesh.parameters.holes, []);
    assert(rightDoor && mesh.parts.some(part => part.id === rightDoor.part && part.valid && part.triangles.length));
    assert.equal(mesh.faces.length, 8);
    await modelCaption("双开门").waitFor();
    await host.locator("canvas").waitFor();
    const elapsedMs = Date.now() - start;
    await screenshot(page, "AE-101-双门预览");
    await exact(page, "打开柜门").click();
    await exact(page, "合上柜门").waitFor();
    await screenshot(page, "AE-101-双门打开");

    const assembled = page.waitForResponse(meshResponse, {timeout:75000});
    await exact(page, "装配").click();
    const assemblyMesh = await (await assembled).json();
    assert.equal(assemblyMesh.parameters.configuration.kind, "double");
    assert.deepEqual(assemblyMesh.parameters.accessories.map(item => item.definition.code).sort(), ["EX-COVER", "T5-55"]);
    assert(assemblyMesh.parameters.holes.some(hole => hole.ownerAccessory));
    await host.locator("canvas").waitFor({timeout:75000});
    await screenshot(page, "AE-101-双门附件");
    await exact(page, "二维").click();
    await board(page, "door_right").click();
    await activeFace(page).and(board(page, "door_right")).waitFor();
    assert.equal(await page.locator(".nd-face-tile").count(), 8);
    await tool(page, "规格").click();
    await modelCaption("双开门").waitFor({timeout:75000});

    await exact(page, "基础原图").click();
    const doubleOriginal = await verifyOriginalSheet(page, "double");
    await field(page, "图纸版本").selectOption("original-single");
    const singleOriginal = await verifyOriginalSheet(page, "single");
    await exact(page, "设计视图").click();
    await modelCaption("双开门").waitFor();

    const historical = before.jobs.find(job => job.operation === "build" && job.state === "done");
    assert(historical);
    await exact(page, "图纸与版本").click();
    await field(page, "图纸版本").selectOption(String(historical.id));
    await page.locator(".nd-drawing-surface img").waitFor();
    const archiveResponse = page.waitForResponse(response =>
        response.url().endsWith(`/file/${historical.id}/mesh`) && response.ok());
    await exact(page, "本版本三维").click();
    assert.equal((await (await archiveResponse).json()).parameters.configuration.kind, "single");
    await exact(page, "设计视图").click();
    await modelCaption("双开门").waitFor();

    await exact(page, "单开门").click();
    await modelCaption("单开门").waitFor();
    await field(page, "柜宽").fill("0");
    await exact(page, "双开门").click();
    await page.getByRole("alert").filter({hasText:"柜宽须在"}).waitFor();
    assert.equal(await host.isVisible(), false);
    await field(page, "柜宽").fill("420");

    const uri = `${origin}/nodo/draw/file/${jobId}/mesh`;
    let resume;
    const hold = new Promise(resolve => { resume = resolve; });
    await page.route(uri, async route => {
        await hold;
        await route.continue().catch(() => {});
    }, {times:1});
    const delayed = page.waitForRequest(uri);
    await exact(page, "双开门").click();
    await delayed;
    await exact(page, "单开门").click();
    await modelCaption("单开门").waitFor();
    resume();
    await exact(page, "二维").click();
    await activeFace(page).waitFor();
    assert.equal(await page.locator(".nd-face-tile").count(), 7);
    assert.equal(await board(page, "door_right").count(), 0);
    const after = await workspace();
    assert.deepEqual(after.settings, before.settings);
    assert.equal(after.edit_number, before.edit_number);
    assert.deepEqual(after.jobs.map(job => job.id), before.jobs.map(job => job.id));
    return {dimensions:mesh.dimensions, singleBoards:single.faces.length, doubleBoards:mesh.faces.length,
        baseAccessories:0, assembledAccessories:assemblyMesh.parameters.accessories.length,
        drawings:{single:singleOriginal, double:doubleOriginal}, elapsedMs, draftJob:jobId,
        historicalRevision:`V${String(historical.version).padStart(2,"0")}`, savedSettingsMatch:true,
        latePreviewIgnored:true, validationErrorShown:true};
}

async function checkParts(page) {
    await page.setViewportSize({width:1655, height:881});
    const waitForBase = kind => page.waitForResponse(async response => {
        if (!meshResponse(response)) return false;
        const {parameters} = await response.json();
        return parameters.configuration.kind === kind && !parameters.accessories.length && !parameters.holes.length;
    }, {timeout:75000});
    const singleBase = waitForBase("single");
    const writes = [];
    page.on("request", request => {
        if (request.url().endsWith("/nodo.draw.design/apply_design")) writes.push(request.url());
    });
    await page.goto(workbench, navigation);
    const collapse = exact(page, "收起应用侧栏");
    if (await collapse.isVisible()) await collapse.click();
    const single = await (await singleBase).json();
    const design = Number(await field(page, "选择设计").inputValue());
    const workspace = () => rpcResult(page.request, "nodo.draw.design", "workspace", [[design]]);
    const before = await workspace();
    assert.equal(before.bom.source, "AE-101");
    assert.equal(single.parts.length, 15);
    await tool(page, "零件").click();
    const region = page.getByRole("region", {name:"零件结构"});
    const count = text => region.getByText(text, {exact:true});
    await count("15 / 15 件").waitFor();
    assert.deepEqual(await region.locator("summary span").allTextContents(), ["钣金件", "结构五金"]);
    assert.deepEqual(await region.locator("summary small").allTextContents(), ["7 件", "8 件"]);
    assert.equal(await region.getByText("附件库匹配").count(), 0);
    const search = field(page, "搜索零件");
    const topCode = single.parts.find(part => part.id === "top").code;
    await search.fill(topCode.toLowerCase());
    await count("1 / 15 件").waitFor();
    assert.equal(await exact(page, "选择顶板").count(), 1);
    await search.fill("门板");
    await exact(page, "选择门板").waitFor();
    await search.fill("没有这个零件");
    await region.getByText("没有匹配的零件", {exact:true}).waitFor();
    await search.fill("m8x32");
    await count("4 / 15 件").waitFor();
    await exact(page, "展开安装板焊接螺柱").click();
    assert.equal(await region.locator(".nd-part-children .nd-part-row").count(), 4);
    await exact(page, "隐藏安装板焊接螺柱").click();
    assert.equal(await region.locator(".nd-part-children .nd-part-hidden").count(), 4);
    await exact(page, "全部显示").click();
    assert.equal(await region.locator(".nd-part-hidden").count(), 0);
    await exact(page, "收起安装板焊接螺柱").click();
    await search.fill("");
    const canvas = page.locator(".nd-three-host canvas");
    await canvas.waitFor();
    const pixels = async () => {
        await settleCanvas(page);
        return canvas.screenshot();
    };
    const allVisible = await pixels();
    await exact(page, "选择门板").click();
    assert.equal(await exact(page, "选择门板").getAttribute("aria-pressed"), "true");
    assert(!allVisible.equals(await pixels()), "选择门板应改变实际三维高亮");
    await screenshot(page, "AE-101-单门零件");
    await exact(page, "隐藏门板").click();
    const hidden = await pixels();
    assert(!hidden.equals(allVisible), "隐藏门板应改变实际三维画面");
    await exact(page, "显示门板").click();
    const shown = await pixels();
    assert(!shown.equals(hidden), "显示门板应恢复实际三维画面");
    await exact(page, "定位门板").click();
    assert(!shown.equals(await pixels()), "定位同一零件应移动三维相机");
    await exact(page, "复位视角").click();
    await settleCanvas(page);
    const box = await canvas.boundingBox();
    await page.mouse.click(box.x + 12, box.y + 12);
    await region.locator(".nd-part-selected").waitFor({state:"detached"});
    await page.mouse.click(box.x + box.width / 2, box.y + box.height / 2);
    await region.locator(".nd-part-selected").waitFor();
    assert.equal(await tool(page, "零件").getAttribute("aria-pressed"), "true");

    const assembly = page.getByRole("complementary", {name:"装配"});
    await exact(page, "装配").click();
    await assembly.waitFor();
    assert.equal(await region.count(), 0);
    assert.deepEqual(await assembly.locator(".nd-match > .nd-between strong").allTextContents(), ["T5-55 × 1", "EX-COVER × 1"]);
    assert.deepEqual([await field(page, "第1行安装面").inputValue(), await field(page, "第2行安装面").inputValue()], ["door", "top"]);
    assert(await exact(page, "一键装配").isEnabled());
    await canvas.waitFor();
    assert((await assembly.boundingBox()).x > (await canvas.boundingBox()).x);
    await screenshot(page, "AE-101-独立装配");
    await exact(page, "关闭装配").click();
    await count("15 / 15 件").waitFor({timeout:75000});

    await tool(page, "规格").click();
    const doubleBase = waitForBase("double");
    await exact(page, "双开门").click();
    await tool(page, "零件").click();
    const double = await (await doubleBase).json();
    assert.equal(double.parts.length, 24);
    await count("24 / 24 件").waitFor();
    assert.deepEqual(await region.locator("summary small").allTextContents(), ["10 件", "14 件"]);
    assert.equal(await exact(page, "选择左门·门板").count(), 1);
    await exact(page, "选择右门·门板").click();
    assert.equal(await exact(page, "选择右门·门板").getAttribute("aria-pressed"), "true");
    await screenshot(page, "AE-101-双门零件");
    await page.setViewportSize({width:1173, height:871});
    assert((await measureToolbar(page)).fits);
    assert((await region.boundingBox()).x < (await canvas.boundingBox()).x);
    const after = await workspace();
    assert.deepEqual(after.settings, before.settings);
    assert.equal(after.edit_number, before.edit_number);
    assert.deepEqual(after.jobs, before.jobs);
    assert.deepEqual(writes, []);
    return {single:{sheet:7, hardware:8}, double:{sheet:10, hardware:14},
        exactDrawingNumber:topCode, groupedStuds:4, selectedFromViewport:true,
        visiblePixelsChanged:true, cameraMoved:true, separatedAssemblyRows:2, workspaceUnchanged:true};
}

async function checkHoleEditing(page) {
    await page.setViewportSize({width:1655, height:881});
    const writes = [];
    page.on("request", request => {
        if (request.url().endsWith("/nodo.draw.design/apply_design")) writes.push(request.url());
    });
    await page.goto(workbench, navigation);
    const selector = field(page, "选择设计");
    await selector.waitFor();
    const workspace = async () => rpcResult(page.request, "nodo.draw.design", "workspace", [[Number(await selector.inputValue())]]);
    const geometry = async (data, face) => {
        const job = data.jobs.find(item => item.state === "done" && item.files?.includes("mesh"));
        assert(job, "缺少样例柜体模型");
        const response = await page.request.get(origin + `/nodo/draw/file/${job.id}/mesh`);
        assert(response.ok());
        return (await response.json()).faces.find(item => item.id === face);
    };
    const read = async () => Promise.all(["横向 U", "纵向 V"].map(async label => Number(await field(page,label).inputValue())));
    const equivalent = async (expected, message) => (await read()).forEach((value, index) =>
        assert(Math.abs(value - expected[index]) < 1e-8, `${message} ${value} 与 ${expected[index]} 不符`));
    const undo = exact(page, "撤销孔位"), redo = exact(page, "重做孔位");
    const uBasis = field(page, "U 坐标基准"), vBasis = field(page, "V 坐标基准");
    const single = await workspace();
    assert.equal(single.bom.source, "AE-101");
    const singleFace = await geometry(single, "door");
    const original = single.settings.holes.find(row => row.id === "H1" && row.face === "door");
    assert(original);
    await exact(page, "二维").click();
    await field(page, "横向 U").waitFor({timeout:75000});
    await page.locator(".nd-bomrow").getByRole("button", {name:/^H1/}).click();
    assert.equal(await undo.isEnabled(), false);
    await uBasis.selectOption("end");
    await vBasis.selectOption("center");
    await equivalent([singleFace.width-original.u, original.v-singleFace.height/2], "切换坐标基准");
    assert.equal(await undo.isEnabled(), false, "显示基准切换不应写入孔位历史");

    await exact(page, "复制 H1").click();
    await page.getByText("复制自 H1，调整位置后确认", {exact:true}).waitFor();
    assert.equal(await field(page, "孔型").inputValue(), original.type);
    assert.equal(Number(await field(page, "直径").inputValue()), original.diameter);
    const confirm = exact(page, "确认复制孔");
    await page.getByRole("alert").filter({hasText:"与 H1 位置、孔型和尺寸相同"}).waitFor();
    assert.equal(await confirm.isEnabled(), false);
    assert.equal(await exact(page,"移除 H2").count(), 0);
    await exact(page, "取消").click();
    assert.equal(await confirm.count(), 0);
    assert.equal(await page.locator(".nd-bomrow").count(), 1);
    await exact(page, "复制 H1").click();

    const target = [135.25, 134.75];
    const display = [singleFace.width-target[0], target[1]-singleFace.height/2];
    await field(page,"横向 U").fill(String(display[0]));
    await field(page,"纵向 V").fill(String(display[1]));
    await equivalent(display, "从终边和中心线输入");
    await exact(page, "U 向居中").click();
    await equivalent([singleFace.width/2, display[1]], "U 向居中");
    await undo.click();
    await equivalent(display, "撤销 U 向居中");
    await redo.click();
    await equivalent([singleFace.width/2, display[1]], "重做 U 向居中");
    await undo.click();
    await exact(page, "V 向居中").click();
    await equivalent([display[0], 0], "V 向居中");
    assert.equal(await redo.isEnabled(), false, "新的编辑应结束旧的重做分支");
    await undo.click();
    await equivalent(display, "撤销 V 向居中");
    assert(await confirm.isEnabled());
    await screenshot(page, "AE-101-二维复制孔");

    await exact(page, "三维").click();
    const handle = page.locator('[data-testid="hole-preview-center"][data-u="135.25"][data-v="134.75"]');
    await handle.waitFor();
    await equivalent(display, "切换三维保留当前草稿");
    await screenshot(page, "AE-101-三维孔位草稿");
    await confirm.click();
    assert.equal(await exact(page, "三维").getAttribute("aria-pressed"), "true");
    await exact(page, "移除 H2").waitFor();
    await undo.click();
    assert.equal(await exact(page,"移除 H2").count(), 0);
    await handle.waitFor();
    await redo.click();
    await exact(page, "移除 H2").waitFor();

    await exact(page, "二维").click();
    await page.locator(".nd-bomrow").getByRole("button", {name:/^H2/}).click();
    await uBasis.selectOption("start");
    await vBasis.selectOption("start");
    await equivalent(target, "复制孔保存到草稿的标准坐标");
    const u = field(page, "横向 U");
    await u.fill("13");
    await u.fill("137");
    await u.fill("137.25");
    await undo.click();
    await equivalent(target, "一次撤销同一输入框中的连续键入");
    await redo.click();
    await equivalent([137.25,target[1]], "重做精确输入");
    await exact(page, "应用孔位修改").click();
    assert.equal(await page.locator(".nd-bomrow").count(), 2);
    const holePosition = text => page.locator(".nd-bomrow").getByText(text,{exact:true});
    await holePosition("137.25，134.75 mm").waitFor();
    await undo.click();
    await holePosition("135.25，134.75 mm").waitFor();
    await redo.click();
    await holePosition("137.25，134.75 mm").waitFor();
    await exact(page,"移除 H2").click();
    assert.equal(await exact(page,"移除 H2").count(), 0);
    await undo.click();
    await exact(page, "移除 H2").waitFor();
    await redo.click();
    assert.equal(await exact(page,"移除 H2").count(), 0);
    await undo.click();
    await exact(page, "移除 H2").waitFor();

    await tool(page, "规格").click();
    await field(page, "柜宽").fill(String(single.settings.width+1));
    await exact(page, "二维").click();
    await page.getByRole("status").filter({hasText:"请先保存并预览当前规格"}).waitFor();
    assert.equal(await u.count(),0);
    const afterSingle = await workspace();
    assert.deepEqual(afterSingle.settings, single.settings);
    assert.equal(afterSingle.edit_number, single.edit_number);
    assert.deepEqual(afterSingle.jobs, single.jobs);

    page.once("dialog", dialog => dialog.accept());
    await chooseDesign(page, "AE-202 · 双门配电箱");
    const double = await workspace();
    const right = await geometry(double,"door_right");
    const rightHole = double.settings.holes.find(row => row.face === "door_right");
    assert(rightHole);
    await exact(page,"二维").click();
    await board(page, "door_right").click();
    await page.locator(".nd-bomrow").getByRole("button",{name:new RegExp(`^${rightHole.id}`)}).click();
    assert.equal(await undo.isEnabled(),false,"切换柜体后孔位历史应独立");
    await uBasis.selectOption("end");
    await equivalent([right.width-rightHole.u,rightHole.v], "右门从终边量");
    await exact(page,"U 向居中").click();
    await equivalent([right.width/2,rightHole.v], "右门单轴居中");
    await undo.click();
    await equivalent([right.width-rightHole.u,rightHole.v], "右门撤销居中");
    await screenshot(page,"AE-202-右门坐标基准");
    assert.deepEqual((await workspace()).settings,double.settings);
    assert.deepEqual(writes,[]);
    return {single:{source:"AE-101",board:[singleFace.width,singleFace.height],original:[original.u,original.v],
        copyCenter:target,duplicateBlocked:true,undoRedo:true,fromOtherBases:display},
        double:{source:"AE-202",board:"door_right",endMeasurement:right.width-rightHole.u},
        sameDraftIn3dAnd2d:true,staleGeometryBlocked:true,workspaceUnchanged:true};
}

async function checkReferenceOutput(page) {
    const model = "nodo.draw.design";
    const fixture = {source:"AE-305", source_version:"1", title:"基础壁挂箱", kind:"single", quantity:1,
        width:380, height:300, depth:210, lines:[]};
    const {design_id:id} = await rpcResult(page.request, model, "handoff_bom", [fixture]);
    const workspace = () => rpcResult(page.request, model, "workspace", [[id]]);
    await page.setViewportSize({width:1173, height:871});
    await page.goto(workbench, navigation);
    await field(page, "选择设计").waitFor();
    await chooseDesign(page, "AE-305 · 基础壁挂箱");
    const submit = async () => {
        const waiting = page.waitForResponse(response => response.url().endsWith("/nodo.draw.design/apply_design") &&
            response.request().method() === "POST");
        await exact(page, "一键出图").click();
        const out = await (await waiting).json();
        assert(!out.error, out.error?.data?.message || "一键出图失败");
        return out.result;
    };
    const initial = (await workspace()).jobs.filter(job => job.operation === "build");
    await field(page, "柜宽").fill("380");
    await field(page, "柜高").fill("300");
    await field(page, "柜深").fill("210");
    assert.equal((await submit()).reference_kind, "single");
    await page.locator('.nd-drawing-surface img[src*="reference/single"]').waitFor();
    assert.deepEqual((await workspace()).jobs.filter(job => job.operation === "build"), initial);
    await exact(page, "设计视图").click();

    await field(page, "柜宽").fill("420");
    await field(page, "柜高").fill("340");
    await field(page, "柜深").fill("235");
    const generated = await submit();
    assert(Number.isInteger(generated.job_id));
    const drawing = page.locator(`.nd-drawing-surface img[src*="/file/${generated.job_id}/"]`);
    await drawing.waitFor({timeout:150000});
    await screenshot(page, "AE-305-调整规格后出图");
    const built = (await workspace()).jobs.find(job => job.id === generated.job_id);
    assert.equal(built.state, "done");
    assert.deepEqual(built.dims.map(Math.round), [420,235,340]);
    await exact(page, "设计视图").click();
    const reused = await submit();
    assert.equal(reused.job_id, generated.job_id);
    const jobs = (await workspace()).jobs.filter(job => job.operation === "build");
    assert.equal(jobs.length, initial.length + Number(!initial.some(job => job.id === built.id)));
    return {source:fixture.source, standardUsesOriginal:true, changedJob:built.id,
        changedRevision:`V${String(built.version).padStart(2,"0")}`, changedWidthDepthHeight:built.dims,
        fileCounts:{dwg:built.sheets.length, dxf:built.cut_count}, sameParametersReused:true};
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
        if (["all", "layout", "toolbar"].includes(mode)) {
            const layout = await page();
            result.layout = await checkLayout(layout);
            if (mode === "toolbar") result.actions = await checkToolbarActions(layout);
        }
        if (mode === "all" || mode === "layout") {
            const single = await page();
            result.single = await checkFaces(single, "AE-101 · 壁挂控制箱", ["door","mount","top","bottom","back","left","right"], true);
            const double = await page();
            await double.goto(workbench, navigation);
            await double.locator(".nd-viewport canvas").waitFor();
            result.double = await checkFaces(double, "AE-202 · 双门配电箱",
                ["door","door_right","mount","top","bottom","back","left","right"], false);
        }
        if (mode === "all" || mode === "materials") result.materials = await checkMaterials(await page());
        if (mode === "cabinet-preview") result.preview = await checkCabinetPreview(await page());
        if (mode === "reference-output") result.output = await checkReferenceOutput(await page());
        if (mode === "all" || mode === "parts") result.parts = await checkParts(await page());
        if (mode === "all" || mode === "hole-editing") result.holes = await checkHoleEditing(await page());
        assert.deepEqual(errors,[]);
        const json = JSON.stringify(result,null,2)+"\n";
        fs.writeFileSync(path.join(destination, `验收-${mode}.json`),json);
        console.log(json);
    } finally { await browser.close(); }
}
main().catch(error=>{console.error(error);process.exitCode=1;});
