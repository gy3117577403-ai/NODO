// Run on nodo_dev with the existing technical account's Playwright session.
const assert = require("node:assert/strict");
const fs = require("node:fs");
const path = require("node:path");
const {chromium} = require("playwright");
const {target, near, faceSurface, drawWorkspace} = require("./verify_selection.cjs");

const root = path.resolve(__dirname,"../..");
const out = path.join(root,".nodo-draw/output/playwright/base-cabinets");
const origin = "http://127.0.0.1:8079";
const url = origin + "/odoo/technical-workbench";
const viewport = {width:1655,height:881};
const button = (page,name) => page.getByRole("button",{name,exact:true});
const canvas = page => page.locator(".nd-three-host canvas");
const caseList = [
    {source:"AE-101", name:"单开门基础柜", kind:"single", size:[380,300,210], face:"door", boardCount:7, sheets:14},
    {source:"AE-202", name:"双开门基础柜", kind:"double", size:[1000,700,300], face:"door_right", boardCount:8, sheets:15},
];

async function rpc(request, route, params) {
    const response = await request.post(origin+route,{data:{jsonrpc:"2.0",method:"call",id:1,params}});
    const body = await response.json();
    if (body.error) throw Error(body.error.data?.message || body.error.message);
    return body.result;
}
async function frame(page) {
    await page.evaluate(() => new Promise(resolve => requestAnimationFrame(() => requestAnimationFrame(resolve))));
}
async function saveShot(page,name) {
    await frame(page);
    await page.screenshot({path:path.join(out,name+".png"),animations:"disabled"});
}
async function initialMesh(page, designId) {
    const received = page.waitForResponse(async response => {
        if (!response.ok() || !/\/nodo\/draw\/file\/\d+\/mesh$/.test(response.url())) return false;
        return !(await response.json()).parameters.accessories.length;
    },{timeout:180000});
    await page.goto(url + "?design=" + designId);
    const model = await (await received).json();
    await canvas(page).waitFor({timeout:15000});
    await frame(page);
    return model;
}
async function startHoleEditing(page) {
    const original = await canvas(page).elementHandle();
    await button(page,"三维开孔").click();
    await page.getByText("点击板面定位",{exact:true}).waitFor();
    await frame(page);
    assert.equal(await original.evaluate(element => element.isConnected),true,"进入三维开孔时更换了当前模型");
    await original.dispose();
}

async function regressionBeforeCleanup(page, design) {
    assert.equal(design.name,"壁挂控制箱","旧版回归需要带附件的 AE-101 快照");
    const model = await initialMesh(page,design.id);
    const before = await drawWorkspace(page);
    assert.deepEqual(before.settings.instances.map(row=>row.code),["T5-55","EX-COVER"]);
    assert.deepEqual(model.parameters.holes.map(row=>row.id),["H1"],"柜体预览须保留已保存的自定义孔");
    assert.equal(faceSurface(model,"door")(95,110),false);
    await startHoleEditing(page);
    await saveShot(page,"旧AE-101-基础柜开孔");
    const bareCanvas = await canvas(page).elementHandle();
    await button(page,"装配").click();
    await page.getByRole("complementary",{name:"装配",exact:true}).getByText("T5-55 × 1",{exact:true}).waitFor();
    await page.waitForFunction(element => !element.isConnected,bareCanvas);
    await bareCanvas.dispose();
    await canvas(page).waitFor();
    await startHoleEditing(page);
    await page.getByRole("button",{name:"取消",exact:true}).waitFor({state:"hidden"});
    await saveShot(page,"旧AE-101-明确切入装配后开孔");
    const after = await drawWorkspace(page);
    assert.deepEqual(after.settings,before.settings);
    assert.deepEqual(after.jobs,before.jobs);
    return {savedAttachments:2, unassembledAccessories:model.parameters.accessories.length,
        savedHolesPreserved:true, assemblyOnlyOnRequest:true, bothEditingTransitionsPreserveModel:true};
}

async function verifyCabinet(page, design, expected) {
    const {source, name, kind, size, face, boardCount, sheets} = expected;
    const model = await initialMesh(page,design.id);
    const before = await drawWorkspace(page);
    assert.equal(before.bom.kind,kind);
    assert.deepEqual([model.dimensions.width,model.dimensions.height,model.dimensions.depth],size);
    assert.deepEqual([before.bom.lines,before.settings.instances,before.settings.holes,before.jobs],[[],[],[],[]]);
    assert.deepEqual([model.parameters.accessories,model.parameters.holes],[[],[]]);
    assert.equal(model.parts.some(part=>part.accessoryId),false);
    await startHoleEditing(page);
    assert.equal(await page.getByRole("group",{name:"加工板面",exact:true}).locator("button").count(),boardCount);
    const board = model.faces.find(row=>row.id===face);
    const screen = target(model,board,await canvas(page).boundingBox());
    await page.mouse.click(screen.x,screen.y);
    await page.getByTestId("hole-preview-center").waitFor();
    const coordinate = async label => Number(await page.getByLabel(label,{exact:true}).inputValue());
    const uv = [await coordinate("横向 U"),await coordinate("纵向 V")];
    near(uv[0],screen.u,.15);
    near(uv[1],screen.v,.15);
    assert.equal(await page.locator('.nd-face-tile[aria-pressed="true"]').getAttribute("data-face"),face);
    await saveShot(page,`${source}-${name}-三维开孔`);
    await button(page,"确认孔位").click();
    await page.locator(".nd-bomrow").getByText("H1",{exact:true}).waitFor();
    await button(page,"撤销孔位").click();
    await button(page,"取消").click();
    const reference = page.waitForResponse(response=>response.url().endsWith("/apply_design"));
    await button(page,"一键出图").click();
    assert.equal((await (await reference).json()).result?.reference_kind,kind);
    await page.locator(".nd-drawing-surface img").waitFor();
    assert.equal(await page.getByLabel("图纸版本",{exact:true}).inputValue(),"original-"+kind);
    assert.equal(await page.locator(".nd-sheet-list button").count(),sheets);
    const after = await drawWorkspace(page);
    assert.deepEqual(after.settings,before.settings);
    assert.deepEqual(after.jobs,[]);
    return {source,kind,size,faces:boardCount,selectedFace:face,clickedUV:uv,originalSheets:sheets};
}

async function main() {
    fs.mkdirSync(out,{recursive:true});
    const browser = await chromium.launch({channel:"chrome"});
    try {
        const context = await browser.newContext({storageState:path.join(root,".nodo-draw/dev-session.local.json"),viewport,deviceScaleFactor:1});
        const session = await rpc(context.request,"/web/session/get_session_info",{});
        assert.equal(session.db,"nodo_dev");
        const model = "nodo.draw.design", method = "list_designs";
        const designs = await rpc(context.request,`/web/dataset/call_kw/${model}/${method}`,{model,method,args:[],kwargs:{}});
        const legacy = process.argv.includes("--legacy");
        if (!legacy) assert.deepEqual(designs.map(({source,name})=>({source,name})),caseList.map(({source,name})=>({source,name})));
        const errors = [];
        async function verify(design, run) {
            const page = await context.newPage();
            page.setDefaultTimeout(15000);
            page.on("pageerror",error=>errors.push(error.message));
            try { return await run(page,design); }
            finally { await page.close(); }
        }
        const results = [];
        if (legacy) results.push(await verify(designs.find(row=>row.source==="AE-101"),regressionBeforeCleanup));
        else for (const [index, design] of designs.entries()) {
            results.push(await verify(design,(page,entry)=>verifyCabinet(page,entry,caseList[index])));
        }
        assert.deepEqual(errors,[]);
        const note = JSON.stringify(results,null,2)+"\n";
        fs.writeFileSync(path.join(out,legacy?"旧样例回归.json":"基础柜验收.json"),note);
        console.log(note);
    } finally { await browser.close(); }
}
main().catch(error=>{console.error(error);process.exitCode=1;});
