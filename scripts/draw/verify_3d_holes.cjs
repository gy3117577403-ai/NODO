// UI acceptance on nodo_dev. Delivery creates one isolated, synthetic AE-306.
const assert = require("node:assert/strict");
const fs = require("node:fs");
const path = require("node:path");
const {chromium} = require("playwright");
const {target, faceSurface, near, drawWorkspace, latestMesh} = require("./verify_selection.cjs");

const root = path.resolve(__dirname, "../..");
const origin = "http://127.0.0.1:8079";
const url = origin + "/odoo/technical-workbench";
const out = path.join(root,".nodo-draw/output/playwright/drilling");
const ui = (page, name) => page.getByRole("button", {name,exact:true});
const field = (page, name) => page.getByLabel(name, {exact:true});
const canvas = page => page.locator(".nd-three-host canvas");
const handle = page => page.getByTestId("hole-preview-center");
const notice = page => page.locator(".nd-drill-caption");
const row = (page,id) => page.locator(".nd-bomrow").filter({has:page.getByText(id,{exact:true})});
const holeFields = async page => Promise.all(["横向 U","纵向 V"].map(async name => Number(await field(page,name).inputValue())));

async function frame(page) {
    await page.evaluate(() => new Promise(resolve => requestAnimationFrame(() => requestAnimationFrame(resolve))));
}
async function capture(page, name) {
    await page.evaluate(() => document.fonts.ready.then(() => true));
    await frame(page);
    await page.screenshot({path:path.join(out,name+".png"),animations:"disabled"});
}
async function selectDesign(page, label) {
    await field(page,"选择设计").selectOption({label});
    await field(page,"选择设计").locator("option:checked").filter({hasText:label}).waitFor({state:"attached"});
}
async function drilling(page) {
    await ui(page,"三维开孔").click();
    await notice(page).waitFor({timeout:120000});
    await canvas(page).waitFor();
    await frame(page);
}
async function pick(page, model, face, uv, angle = 0) {
    const point = target(model,face,await canvas(page).boundingBox(),uv,angle);
    await page.mouse.click(point.x,point.y);
    return point;
}
async function checkPoint(page, expected) {
    await handle(page).waitFor();
    const [u,v] = await holeFields(page);
    near(u,expected.u,.15);
    near(v,expected.v,.15);
    assert.equal(await ui(page,"三维开孔").getAttribute("aria-pressed"),"true");
    assert.equal(await page.getByLabel("板面开孔定位").count(),0);
    return [u,v];
}
async function singleDoor(page) {
    await page.goto(url);
    const before = await drawWorkspace(page);
    assert.equal(before.bom.source,"AE-101");
    await canvas(page).waitFor({timeout:120000});
    const base = await canvas(page).boundingBox();
    await page.mouse.click(base.x+base.width*.5,base.y+base.height*.49);
    assert.equal(await ui(page,"三维").getAttribute("aria-pressed"),"true");
    assert.equal(await page.getByLabel("板面开孔定位").count(),0);
    const model = await latestMesh(page,before);
    const face = model.faces.find(item => item.id === "door");
    await drilling(page);
    const firstPoint = await pick(page,model,face,[135.25,134.75]);
    const first = await checkPoint(page,firstPoint);
    const grip = await handle(page).boundingBox();
    const destination = target(model,face,await canvas(page).boundingBox(),[156,147]);
    await page.mouse.move(grip.x+grip.width/2,grip.y+grip.height/2);
    await page.mouse.down();
    await page.mouse.move(destination.x,destination.y,{steps:14});
    await page.mouse.up();
    await frame(page);
    const dragged = await holeFields(page);
    assert.notDeepEqual(dragged,first,"三维拖动未改变坐标");
    near(dragged[0],156,1.6); near(dragged[1],147,1.6);
    assert(dragged.every(Number.isInteger),"1 mm 吸附应写入整数毫米");
    await ui(page,"撤销孔位").click();
    assert.deepEqual(await holeFields(page),first,"一次撤销应恢复拖动前的位置");
    await ui(page,"重做孔位").click();
    assert.deepEqual(await holeFields(page),dragged);

    const stage = await canvas(page).boundingBox();
    const clip = {x:Math.ceil(stage.x)+24, y:Math.ceil(stage.y)+24,
        width:Math.floor(stage.width)-48, height:Math.floor(stage.height)-48};
    const snapshot = () => page.screenshot({clip,animations:"disabled"});
    await page.mouse.move(stage.x+25,stage.y+80);
    const cabinet = await snapshot();
    await ui(page,"正对板面").click();
    await ui(page,"返回整柜").waitFor();
    await capture(page,"AE-101-正对门板");
    assert(!cabinet.equals(await snapshot()),"正对板面未重新构图");
    await ui(page,"返回整柜").click();
    await ui(page,"正对板面").waitFor();
    await page.mouse.move(stage.x+25,stage.y+80);
    await frame(page);
    const restored = await snapshot();
    if (!cabinet.equals(restored)) {
        fs.writeFileSync(path.join(out,"相机-进入正对前.png"),cabinet);
        fs.writeFileSync(path.join(out,"相机-返回整柜后.png"),restored);
        assert.fail("返回整柜未恢复原相机");
    }
    await field(page,"直径").fill("22");
    assert(await field(page,"直径").inputValue() === "22");
    await capture(page,"AE-101-三维直接开孔");
    await ui(page,"保存并预览开孔").click();
    await notice(page).getByText("请先确认或取消当前孔位。").waitFor();
    await page.locator('button.nd-face-tile[data-face="top"]').click();
    assert.equal(await page.locator('.nd-face-tile[aria-pressed=true]').getAttribute("data-face"),"top");
    await ui(page,"一键出图").click();
    await notice(page).getByText("请先确认或取消当前孔位。").waitFor();
    assert.equal(await page.locator('.nd-face-tile[aria-pressed=true]').getAttribute("data-face"),"door");
    assert.deepEqual((await drawWorkspace(page)).jobs,before.jobs);
    await ui(page,"确认孔位").click();
    await row(page,"H2").waitFor();
    assert.equal(await notice(page).getByText("请先确认或取消当前孔位。").count(),0);
    const next = await pick(page,model,face,[140,216]);
    await checkPoint(page,next);
    assert.equal(await row(page,"H3").count(),0);
    await ui(page,"取消").click();
    await frame(page);
    await pick(page,model,face,dragged);
    await ui(page,"应用孔位修改").waitFor();
    await row(page,"H2").locator("button[aria-pressed=true]").waitFor();
    await ui(page,"二维").click();
    await page.getByLabel("板面开孔定位").waitFor();
    assert.deepEqual(await holeFields(page),dragged);
    assert.equal(await ui(page,"应用孔位修改").count(),1);
    const after = await drawWorkspace(page);
    assert.deepEqual(after.settings,before.settings);
    assert.deepEqual(after.jobs,before.jobs);
    assert.equal(after.edit_number,before.edit_number);
    return {first,dragged,diameter:22,originalViewRestored:true,ordinaryPickStayedIn3d:true,
        existingHole:"H2",sameDraftIn2d:true,workspaceUnchanged:true};
}

async function originalOpening(page) {
    await page.goto(url);
    await selectDesign(page,"AE-303 · 五金装配柜 · 交接版 2");
    const before = await drawWorkspace(page);
    const model = await latestMesh(page,before);
    const v02 = before.jobs.find(item => item.operation === "build" && item.version === 2 && item.state === "done");
    assert(v02?.files.includes("mesh"),"缺少 V02 的归档三维");
    const face = model.faces.find(item => item.id === "door");
    const lock = model.parameters.accessories.find(item => item.definition.code === "AE-SQ35");
    assert.equal(lock.definition.templateOpening.width,21.2);
    assert.equal(lock.definition.templateOpening.height,21.2);
    const uv = [face.width-lock.u,face.height/2+lock.v];
    assert.equal(faceSurface(model,"door")(...uv),false);
    const archiveResponse = await page.request.get(`${origin}/nodo/draw/file/${v02.id}/mesh`);
    assert(archiveResponse.ok(),"无法读取 V02 的归档三维");
    const archived = await archiveResponse.json();
    const archivedDoor = faceSurface(archived,"door");
    for (const [du,dv] of [[1,0],[-1,0],[0,1],[0,-1]]) {
        assert.equal(archivedDoor(uv[0]+du*10.55,uv[1]+dv*10.55),false);
        assert.equal(archivedDoor(uv[0]+du*10.65,uv[1]+dv*10.65),true);
    }
    await drilling(page);
    await pick(page,model,face,uv);
    await notice(page).getByText(/原图 21\.2 × 21\.2 mm 开孔/).waitFor();
    assert.equal(await handle(page).isVisible(),false);
    assert.equal(await page.locator('.nd-face-tile[aria-pressed=true]').getAttribute("data-face"),"door");
    await capture(page,"AE-303-原图方孔保护");

    // Try the same geometry through the numeric editor, independent of picking.
    await field(page,"孔型").selectOption("rectangle");
    await field(page,"横向 U").fill(String(uv[0]));
    await field(page,"纵向 V").fill(String(uv[1]));
    await field(page,"孔宽").fill("21.2");
    await field(page,"孔高").fill("21.2");
    await page.getByRole("alert").filter({hasText:"孔轮廓与原图开孔"}).waitFor();
    assert.equal(await ui(page,"确认孔位").isEnabled(),false);
    const after = await drawWorkspace(page);
    assert.deepEqual(after.jobs,before.jobs);
    assert.deepEqual(after.settings,before.settings);
    assert.equal(after.edit_number,before.edit_number);
    return {size:[21.2,21.2],uv,originalVersion:"V02",protectedPick:true,duplicateFormBlocked:true,wrongBoardPrevented:true,workspaceUnchanged:true};
}

async function submit(page, action) {
    const received = page.waitForResponse(response => response.url().endsWith("/apply_design"));
    await ui(page,action).click();
    const rpc = await (await received).json();
    assert(rpc.result?.job_id,rpc.error?.data?.message || "没有创建 CAD 任务");
    return rpc.result.job_id;
}
async function fetchMesh(page, job) {
    const deadline = Date.now()+180000;
    while (Date.now() < deadline) {
        const response = await page.request.get(`${origin}/nodo/draw/file/${job}/mesh`);
        if (response.ok()) return response.json();
        const error = page.locator(".nd-error");
        if (await error.isVisible()) throw Error(await error.textContent());
        await new Promise(resolve=>setTimeout(resolve,500));
    }
    assert.fail("右门开孔预览未完成");
}
async function download(page, name, file, job) {
    await ui(page,"下载").click();
    const received = page.waitForEvent("download");
    await page.getByRole("link",{name,exact:true}).click();
    const download = await received;
    assert(download.url().includes(`/file/${job}/`));
    await download.saveAs(path.join(out,file));
}

async function doubleDelivery(page) {
    const fixture = {source:"AE-306",source_version:"1",title:"双门开孔样件",quantity:1,
        kind:"double",width:1020,height:720,depth:320,lines:[]};
    const method = "handoff_bom";
    const response = await page.request.post(`${origin}/web/dataset/call_kw/nodo.draw.design/${method}`, {
        data:{jsonrpc:"2.0",method:"call",id:1,params:{model:"nodo.draw.design",method,args:[fixture],kwargs:{}}},
    });
    const result = await response.json();
    assert(result.result?.design_id,result.error?.data?.message || "样件交接失败");
    const id = result.result.design_id;
    await page.goto(url+"?design="+id);
    const before = await drawWorkspace(page);
    assert.equal(before.id,id);
    const targetUV = [135.25,155.75], size = [24,14];
    const fitting = row => row.id === "H1" && row.face === "door_right" && row.type === "rectangle" &&
        row.u === targetUV[0] && row.v === targetUV[1] && row.width === size[0] && row.height === size[1];
    let openPick;
    const prior = before.settings.holes;
    if (!prior.length) {
        const response = page.waitForResponse(item => /\/nodo\/draw\/file\/\d+\/mesh$/.test(item.url()) && item.ok(), {timeout:120000});
        await drilling(page);
        const model = await (await response).json();
        const face = model.faces.find(item => item.id === "door_right");
        assert(faceSurface(model,face.id)(...targetUV),"起始右门应是实体板材");
        await ui(page,"打开柜门").click();
        await ui(page,"合上柜门").waitFor();
        await frame(page);
        const aim = await pick(page,model,face,[145,170],70);
        openPick = await checkPoint(page,aim);
        assert.equal(await page.locator('.nd-face-tile[aria-pressed=true]').getAttribute("data-face"),"door_right");
        await field(page,"孔型").selectOption("rectangle");
        await field(page,"横向 U").fill(String(targetUV[0]));
        await field(page,"纵向 V").fill(String(targetUV[1]));
        await field(page,"孔宽").fill(String(size[0]));
        await field(page,"孔高").fill(String(size[1]));
        await capture(page,"AE-306-开门点选右门");
        await ui(page,"合上柜门").click();
        await checkPoint(page,{u:targetUV[0],v:targetUV[1]});
        await ui(page,"确认孔位").click();
        await row(page,"H1").waitFor();
        const preview = await submit(page,"保存并预览开孔");
        const mesh = await fetchMesh(page,preview);
        assert(mesh.parameters.holes.some(fitting));
        const surface = faceSurface(mesh,face.id);
        assert.equal(surface(...targetUV),false);
        assert.equal(surface(targetUV[0]+size[0]/2+.3,targetUV[1]),true);
    } else {
        assert(prior.length === 1 && fitting(prior[0]),"现有样件参数不同，保留该设计");
    }
    const job = await submit(page,"一键出图");
    console.log("双门开孔样件图纸批次",job);
    const version = field(page,"图纸版本").locator("option:checked");
    await version.filter({hasText:/已生成|生成失败/}).waitFor({state:"attached",timeout:600000});
    const label = (await version.textContent()).trim();
    if (!label.includes("已生成")) throw Error(await page.locator(".nd-archive-state").textContent());
    const after = await drawWorkspace(page);
    const built = after.jobs.find(item => item.id === job);
    assert(built && built.state === "done" && after.settings.holes.find(fitting));
    const sheet = built.sheets.find(item => item.category === "flat" && item.name.includes("右门"));
    assert(sheet, "缺少右门板展开图");
    await page.locator(".nd-sheet-list").getByRole("button",{name:new RegExp(sheet.name)}).click();
    await page.locator(".nd-drawing-surface img").waitFor();
    await download(page,"下载"+sheet.name+" DWG","右门展开.dwg",job);
    await download(page,"下载"+sheet.name+" DXF","右门切割.dxf",job);
    await download(page,"整柜 STEP","整柜.step",job);
    await download(page,"孔位表","孔位表.csv",job);
    await capture(page,"AE-306-右门展开图");
    return {id,job,source:fixture.source,revision:label.split(" ")[0],openPick,uv:targetUV,size,
        downloads:["右门展开.dwg","右门切割.dxf","整柜.step","孔位表.csv"]};
}

async function main() {
    fs.mkdirSync(out,{recursive:true});
    const browser = await chromium.launch({channel:"chrome"});
    const errors = [];
    try {
        const context = await browser.newContext({storageState:path.join(root,".nodo-draw/dev-session.local.json"),
            viewport:{width:1655,height:881},deviceScaleFactor:1});
        const result = await context.request.post(`${origin}/web/session/get_session_info`,{
            data:{jsonrpc:"2.0",method:"call",id:1,params:{}},
        });
        assert.equal((await result.json()).result?.db,"nodo_dev");
        async function check(run) {
            const page = await context.newPage();
            page.setDefaultTimeout(12000);
            page.on("pageerror",error=>errors.push(error.message));
            try { return await run(page); }
            catch (error) {
                if (errors.length) console.error(errors.join("\n"));
                const dialog = page.getByRole("dialog").last();
                const details = dialog.getByText(/查看技术细节/);
                if (await details.isVisible()) {
                    await details.click();
                    console.error((await dialog.innerText()).slice(0,1800));
                }
                throw error;
            }
            finally { await page.close(); }
        }
        const deliver = process.argv.includes("--deliver");
        const evidence = deliver ? await check(doubleDelivery) :
            {single:await check(singleDoor),square:await check(originalOpening)};
        assert.deepEqual(errors,[]);
        const json = JSON.stringify(evidence,null,2)+"\n";
        fs.writeFileSync(path.join(out,deliver?"出图浏览器.json":"交互实测.json"),json);
        console.log(json);
    } finally { await browser.close(); }
}
main().catch(error=>{console.error(error);process.exitCode=1;});
