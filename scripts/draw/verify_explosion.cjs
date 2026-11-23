// Browser acceptance on nodo_dev. The archive scenario supplies existing CAD
// files to isolated browser routes and leaves the development records alone.
const assert = require("node:assert/strict");
const crypto = require("node:crypto");
const fs = require("node:fs");
const path = require("node:path");
const {chromium} = require("playwright");
const {target, drawWorkspace} = require("./verify_selection.cjs");

const root = path.resolve(__dirname,"../..");
const exchange = path.join(root,".nodo-draw/exchange");
const out = path.join(root,".nodo-draw/output/playwright/explosion-clearance");
const origin = "http://127.0.0.1:8079";
const url = origin + "/odoo/technical-workbench";
const state = path.join(root,".nodo-draw/dev-session.local.json");
const viewport = {width:1655,height:881};
const btn = (page,name) => page.getByRole("button",{name,exact:true});
const field = (page,name) => page.getByLabel(name,{exact:true});
const canvas = page => page.locator(".nd-three-host canvas");
const during = page => page.locator('.nd-face-tile[aria-pressed="true"]');
const picker = page => field(page,"拆解比例");
const read = file => JSON.parse(fs.readFileSync(file,"utf8"));
const digest = data => crypto.createHash("sha256").update(data).digest("hex");

async function frame(page) {
    await page.evaluate(() => new Promise(resolve => requestAnimationFrame(() => requestAnimationFrame(() => requestAnimationFrame(resolve)))));
}
async function screenshot(page,name) {
    await frame(page);
    await page.screenshot({path:path.join(out,name+".png"),animations:"disabled"});
}
async function modelImage(page) {
    await frame(page);
    const box = await canvas(page).boundingBox();
    const clip = {x:Math.ceil(box.x)+20,y:Math.ceil(box.y)+15,
        width:Math.floor(box.width)-40,height:Math.floor(box.height)-160};
    return page.screenshot({clip,animations:"disabled"});
}
async function visibleAssemblyGroups(page, expected) {
    const image = await canvas(page).screenshot({style:".nd-viewport-head,.nd-vtools { visibility: hidden !important }"});
    const groups = await page.evaluate(async data => {
        const bitmap = await createImageBitmap(await (await fetch(`data:image/png;base64,${data}`)).blob());
        const {width,height} = bitmap;
        const context = new OffscreenCanvas(width,height).getContext("2d");
        context.drawImage(bitmap,0,0);
        const {data:pixels} = context.getImageData(0,0,width,height);
        const mask = new Uint8Array(width*height), stack = new Int32Array(mask.length);
        const sample = (width+1)*8;
        for (let y=2;y<height-2;y++) for (let x=2;x<width-2;x++) {
            const i = y*width+x, p = 4*i;
            mask[i] = Math.max(Math.abs(pixels[p]-pixels[sample]),Math.abs(pixels[p+1]-pixels[sample+1]),
                Math.abs(pixels[p+2]-pixels[sample+2]))>10;
        }
        const boxes = [];
        for (let i=0;i<mask.length;i++) {
            if (!mask[i]) continue;
            let count=0, size=0, left=width, right=0, top=height, bottom=0;
            const visit = next => { if (mask[next]) { mask[next]=0; stack[size++]=next; } };
            visit(i);
            while (size) {
                const at = stack[--size], x = at % width, y = Math.floor(at/width);
                left=Math.min(left,x); right=Math.max(right,x); top=Math.min(top,y); bottom=Math.max(bottom,y);
                count++;
                if (x>0) visit(at-1);
                if (x<width-1) visit(at+1);
                if (y>0) visit(at-width);
                if (y<height-1) visit(at+width);
            }
            if (count>500) boxes.push({count,margin:Math.min(left,top,width-1-right,height-1-bottom)});
        }
        return boxes;
    },image.toString("base64"));
    assert.equal(groups.length,expected,JSON.stringify(groups));
    const minMargin = Math.min(...groups.map(group=>group.margin));
    assert(minMargin>=12,`完全展开后距视口最窄仅 ${minMargin}px`);
    return {visibleGroups:groups.length,minMargin};
}
async function openControls(page) {
    await frame(page);
    const trigger = btn(page,"拆解");
    if (await trigger.getAttribute("aria-expanded") !== "true") await trigger.click();
    await picker(page).waitFor();
    assert.equal(await page.locator(".nd-explosion-slider").evaluate(panel=>getComputedStyle(panel).position),"absolute");
}
async function setEndpoint(page, value) {
    await btn(page,value===100 ? "完全展开" : "收拢").click();
    await frame(page);
    assert.equal(await picker(page).inputValue(),String(value));
}
async function dragHalfway(page) {
    const box = await picker(page).boundingBox();
    const y = box.y+box.height/2;
    await page.mouse.move(box.x+7,y);
    await page.mouse.down();
    await page.mouse.move(box.x+box.width/2,y,{steps:10});
    await page.mouse.up();
    const dragged = Number(await picker(page).inputValue());
    assert(Math.abs(dragged-50) <= 5,"拖动滑杆未达到一半附近");
    for (let i=0;i<Math.abs(dragged-50);i++) {
        await picker(page).press(dragged>50 ? "ArrowLeft" : "ArrowRight");
    }
    assert.equal(Number(await picker(page).inputValue()),50);
}
async function place(page, model, id, spread = false, ratios = [.37,.65]) {
    const face = model.faces.find(board=>board.id===id);
    assert(face,id);
    const part = model.parts.find(item=>item.id===face.part);
    const shifted = spread ? {...face,origin:face.origin.map((value,i)=>value+part.explode[i])} : face;
    const click = target(model,shifted,await canvas(page).boundingBox(),[face.width*ratios[0],face.height*ratios[1]],0,spread);
    await page.mouse.click(click.x,click.y);
    await frame(page);
}
async function coords(page) {
    return Promise.all(["横向 U","纵向 V","直径"].map(name=>field(page,name).inputValue()));
}
function trackCadRequests(page) {
    const requests = [];
    page.on("request", request => {
        const action = request.url().split("/").at(-1);
        if (["preview_cabinet","apply_design"].includes(action)) requests.push(action);
    });
    return requests;
}
async function rpc(request, route, params) {
    const response = await request.post(origin+route,{data:{jsonrpc:"2.0",method:"call",id:1,params}});
    const message = await response.json();
    if (message.error) throw Error(message.error.data?.message || message.error.message);
    return message.result;
}
async function currentBase(page, id) {
    const ready = page.waitForResponse(response=>response.ok()&&/\/nodo\/draw\/file\/\d+\/mesh$/.test(response.url()),{timeout:150000});
    await page.goto(url+"?design="+id);
    const mesh = await (await ready).json();
    await canvas(page).waitFor();
    await frame(page);
    assert.deepEqual(mesh.parameters.accessories,[]);
    return mesh;
}

async function singleDoor(page, mesh) {
    const oldCanvas = await canvas(page).elementHandle();
    const closed = await modelImage(page);
    await openControls(page);
    assert.equal(await picker(page).inputValue(),"0");
    await dragHalfway(page);
    const half = await modelImage(page);
    await picker(page).press("End");
    const sliderFull = await modelImage(page);
    await setEndpoint(page,100);
    const full = await modelImage(page);
    assert(!closed.equals(half) && !half.equals(full),"滑杆没有改变模型");
    assert(full.equals(sliderFull),"滑杆到达 100% 时未按完全展开取景");
    await screenshot(page,"AE-101-单门拆解");
    const fullyExpanded = await visibleAssemblyGroups(page,5);
    await setEndpoint(page,0);
    assert(closed.equals(await modelImage(page)),"收拢后的视口与初始位置不一致");
    assert(await oldCanvas.evaluate(element=>element.isConnected),"拆解重建了三维画布");
    await oldCanvas.dispose();

    await btn(page,"打开柜门").click();
    await btn(page,"复位视角").click();
    const open = await modelImage(page);
    await openControls(page);
    await setEndpoint(page,100);
    assert(!open.equals(await modelImage(page)));
    await visibleAssemblyGroups(page,5);
    await setEndpoint(page,0);
    assert(await btn(page,"合上柜门").isVisible());
    assert(open.equals(await modelImage(page)),"开门收拢没有恢复原姿态");
    await btn(page,"合上柜门").click();

    await openControls(page);
    await setEndpoint(page,100);
    const initialView = await modelImage(page);
    const area = await canvas(page).boundingBox();
    const x = area.x+area.width*.56, y = area.y+area.height*.42;
    await page.mouse.move(x,y);
    await page.mouse.down();
    await page.mouse.move(x-100,y+34,{steps:10});
    await page.mouse.up();
    const rotated = await modelImage(page);
    assert(!initialView.equals(rotated),"拆解时拖动没有旋转模型");
    await page.mouse.wheel(0,-230);
    assert(!rotated.equals(await modelImage(page)),"拆解时滚轮没有缩放模型");
    await openControls(page);
    await setEndpoint(page,0);
    await btn(page,"复位视角").click();
    await frame(page);

    await btn(page,"三维开孔").click();
    await page.getByText("点击板面定位",{exact:true}).waitFor();
    await place(page,mesh,"right");
    assert.equal(await during(page).getAttribute("data-face"),"right");
    await field(page,"直径").fill("22");
    const draft = await coords(page);
    await openControls(page);
    assert.equal(await btn(page,"三维").getAttribute("aria-pressed"),"true");
    await dragHalfway(page);
    await btn(page,"三维开孔").click();
    assert.equal(await during(page).getAttribute("data-face"),"right");
    assert.deepEqual(await coords(page),draft);
    assert(!((await btn(page,"拆解").innerText()).includes("50%")),"开孔视口仍显示拆解比例");
    await page.getByTestId("hole-preview-center").waitFor();
    await screenshot(page,"AE-101-收拢恢复右侧板孔位");
    await btn(page,"三维").click();
    await openControls(page);
    assert.equal(await picker(page).inputValue(),"50");
    return {ratios:[0,50,100,0],fullyExpanded,canvasReused:true,doorPosePreserved:true,rotatedAndZoomed:true,
        restoredFace:"right",restoredDraft:draft,restoredRatio:50};
}

async function doubleDoor(page, mesh, positionModel) {
    await btn(page,"零件").click();
    await btn(page,"零件结构").click();
    const fitted = positionModel(mesh), part = id => fitted.parts.find(part=>part.id===id);
    assert.deepEqual(part("stud_0").explode,part("wrap").explode);
    assert.deepEqual(part("hinge_top_right").explode,part("door_right").explode);
    await openControls(page);
    await setEndpoint(page,100);
    const fullyExpanded = await visibleAssemblyGroups(page,6);
    const picked = ["door","door_right","right","top","bottom","mount"];
    for (const face of picked) {
        await place(page,fitted,face,true);
        const name = part(fitted.faces.find(item=>item.id===face).part).name;
        assert.equal(await btn(page,"选择"+name).getAttribute("aria-pressed"),"true",name);
    }
    await openControls(page);
    await screenshot(page,"AE-202-双门拆解与安装板选中");
    const expanded = await modelImage(page);
    await btn(page,"定位安装板").click();
    assert(!expanded.equals(await modelImage(page)),"安装板定位没有更新视角");
    await btn(page,"隐藏安装板").click();
    await btn(page,"显示安装板").waitFor();
    await btn(page,"全部显示").click();
    assert(await btn(page,"隐藏安装板").isVisible());
    await btn(page,"三维开孔").click();
    assert.equal(await during(page).getAttribute("data-face"),"mount","拆解选中的安装板未带入开孔");
    await btn(page,"二维").click();
    assert.equal(await btn(page,"拆解").count(),0);
    return {fullyExpanded,independentDoorOffsets:[part("door").explode,part("door_right").explode],picked,
        locatedAndToggled:true,drillFace:"mount"};
}

function archiveFixtures() {
    const filenames = fs.readdirSync(exchange).filter(name=>/^dev-cabinets-backup-\d{8}T\d{6}Z\.json$/.test(name));
    assert(filenames.length,"缺少本机旧柜体归档记录");
    const backup = read(path.join(exchange,filenames.sort().at(-1)));
    const single = backup.nodo_draw_design.find(row=>row.source==="AE-101");
    const assembled = backup.nodo_draw_design.find(row=>row.source==="AE-303" && row.source_version==="2");
    assert(single && assembled,"缺少旧版单双用途验收数据");
    function materialize(row) {
        assert(/^[a-f0-9]{32}$/.test(row.token));
        const folder = path.join(exchange,row.token);
        const status = read(path.join(folder,"status.json"));
        assert.equal(status.state,"done");
        assert(/^run-[a-f0-9]{32}$/.test(status.run));
        const run = path.join(folder,status.run);
        const files = new Map(Object.entries(status.files));
        const info = {id:row.id,operation:row.operation,version:row.version,edit_number:row.edit_number,
            state:status.state,files:[...files.keys()],sheets:status.sheets ?? [],cut_count:status.cut_count,limits:status.limits};
        return {run,files,info};
    }
    const archive = new Map();
    for (const [design, version] of [[single,5],[single,6],[assembled,2]]) {
        const row=backup.nodo_draw_job.find(row=>row.design_id===design.id&&row.operation==="build"&&
            row.final_state==="done"&&row.version===version);
        assert(row,`缺少 ${design.source} V${version}`);
        archive.set(row.id,materialize(row));
    }
    const base = backup.nodo_draw_job.filter(row=>row.design_id===single.id && row.preview_user_id && row.final_state==="done")
        .filter(row=>row.payload.parameters.width===420 && row.payload.parameters.height===340 && row.payload.parameters.depth===235 &&
            row.payload.parameters.accessories.length===0).at(-1);
    assert(base,"缺少用于隔离会话的基础模型文件");
    archive.set(base.id,materialize(base));
    const designs = [assembled,single];
    const jobs = design => [...archive.values()].map(file=>file.info).filter(info=>info.operation==="build" &&
        backup.nodo_draw_job.find(row=>row.id===info.id).design_id===design.id).sort((a,b)=>b.version-a.version);
    return {designs,jobs,archive,base:base.id,assembled};
}

async function useArchivedFiles(page, fixture) {
    const {designs,jobs,archive,base} = fixture;
    await page.route("**/web/dataset/call_kw/nodo.draw.design/**",async route=>{
        const {id,params} = route.request().postDataJSON();
        const {method,args} = params;
        let result;
        if (method === "list_designs") result = designs.map(({id,name,source,source_version})=>({id,name,source,source_version}));
        else if (method === "workspace") {
            const design = designs.find(row=>row.id===args[0][0]);
            assert(design,"隔离会话请求了未配置的设计");
            result = {...design,jobs:jobs(design),online:true};
        } else if (method === "preview_cabinet") result = base;
        else if (method === "cabinet_preview_status") result = archive.get(base).info;
        else if (method === "list_reference_drawings") return route.fallback();
        else assert.fail(`隔离会话发起了未允许的 ${method}`);
        await route.fulfill({json:{jsonrpc:"2.0",id,result}});
    });
    await page.route("**/nodo/draw/file/**",async route=>{
        const [,id,key] = /\/file\/(\d+)\/([a-z0-9_]+)$/.exec(new URL(route.request().url()).pathname) ?? [];
        const job = archive.get(Number(id));
        assert(job?.files.has(key),"隔离会话读取了未配置的归档文件");
        const file = path.resolve(job.run,job.files.get(key));
        assert(!path.relative(job.run,file).startsWith(".."));
        const contentType = key === "mesh" ? "application/json" : key.endsWith("p") ? "image/svg+xml" : undefined;
        await route.fulfill({path:file,contentType});
    });
}

async function historicalExplosion(page, positionModel) {
    const fixture = archiveFixtures();
    await useArchivedFiles(page,fixture);
    const latest = fixture.jobs(fixture.assembled)[0];
    const current = page.waitForResponse(response=>response.url()===`${origin}/nodo/draw/file/${latest.id}/mesh`&&response.ok());
    await page.goto(url+"?design="+fixture.assembled.id);
    const raw = await (await current).body();
    const mesh = JSON.parse(raw.toString("utf8"));
    const positioned = positionModel(mesh);
    const byPart = new Map(positioned.parts.map(part=>[part.id,part]));
    const codes = mesh.parameters.accessories.map(item=>item.definition.code);
    assert.deepEqual(codes,["AE-SQ35","T5-55","EX-COVER","EX-BASE"]);
    for (const item of mesh.parameters.accessories) {
        const host = byPart.get(mesh.faces.find(face=>face.id===item.face).part);
        const assembly = positioned.parts.filter(part=>part.accessoryId===item.id);
        assert(assembly.length);
        for (const part of assembly) assert.deepEqual([part.group,part.explode],[host.group,host.explode]);
    }
    assert(mesh.parts.filter(part=>part.accessoryId).every(part=>part.explode.every(value=>value===0)));
    await btn(page,"装配").click();
    await page.getByRole("complementary",{name:"装配",exact:true}).waitFor();
    await canvas(page).waitFor();
    const cadRequests = trackCadRequests(page);
    const assembled = await modelImage(page);
    await openControls(page);
    await setEndpoint(page,100);
    assert(!assembled.equals(await modelImage(page)));
    await screenshot(page,"AE-303-装配附件拆解");

    await btn(page,"图纸与版本").click();
    const archives = [];
    async function verifyVersion(info) {
        const record = fixture.archive.get(info.id);
        const disk = fs.readFileSync(path.join(record.run,record.files.get("mesh")));
        const load = page.waitForResponse(response=>response.url()===`${origin}/nodo/draw/file/${info.id}/mesh`&&response.ok());
        await btn(page,"本版本三维").click();
        assert.equal(digest(await (await load).body()),digest(disk));
        await canvas(page).waitFor();
        await openControls(page);
        assert.equal(await picker(page).inputValue(),"0");
        const closed = await modelImage(page);
        await setEndpoint(page,100);
        const expanded = await modelImage(page);
        assert(!closed.equals(expanded),`V${info.version} 的归档视口未拆解`);
        const revision = "V"+String(info.version).padStart(2,"0");
        await page.getByText(revision+" · 本版本三维",{exact:true}).waitFor();
        if (info.id===latest.id) {
            await screenshot(page,"AE-303-V02-本版本三维拆解");
        }
        archives.push({revision,job:info.id,sha256:digest(disk)});
        await btn(page,"图纸").click();
    }
    await verifyVersion(latest);
    assert.deepEqual(cadRequests,[]);
    const single = fixture.designs.find(row=>row.source==="AE-101");
    await field(page,"选择设计").selectOption(String(single.id));
    await field(page,"图纸版本").locator('option').filter({hasText:/^V06 /}).waitFor({state:"attached"});
    cadRequests.length = 0;
    for (const info of fixture.jobs(single)) {
        await field(page,"图纸版本").selectOption(String(info.id));
        await verifyVersion(info);
    }
    assert.deepEqual(cadRequests,[]);
    return {accessories:codes,archives,archiveScope:"isolated browser with original archived CAD files"};
}

async function main() {
    fs.mkdirSync(out,{recursive:true});
    const {withExplosionVectors} = await import("./viewer/explosion_model.mjs");
    const browser = await chromium.launch({channel:"chrome"});
    try {
        const context = await browser.newContext({storageState:state,viewport,deviceScaleFactor:1});
        assert.equal((await rpc(context.request,"/web/session/get_session_info",{})).db,"nodo_dev");
        const method="list_designs", model="nodo.draw.design";
        const designs = () => rpc(context.request,`/web/dataset/call_kw/${model}/${method}`,{method,model,args:[],kwargs:{}});
        const original = await designs();
        assert.deepEqual(original.map(row=>row.source),["AE-101","AE-202"]);
        const errors = [];
        const page = async ctx => {
            const tab=await ctx.newPage();
            tab.setDefaultTimeout(15000);
            tab.on("pageerror",error=>{ errors.push(error.message); console.error(error); });
            return tab;
        };
        const result = {};
        for (const row of original) {
            const tab = await page(context);
            const mesh = await currentBase(tab,row.id);
            const before = await drawWorkspace(tab);
            const cadRequests = trackCadRequests(tab);
            result[row.source] = await (row.source==="AE-101" ? singleDoor : doubleDoor)(tab,mesh,withExplosionVectors);
            const after = await drawWorkspace(tab);
            assert.deepEqual([after.settings,after.bom,after.jobs,after.edit_number],[before.settings,before.bom,before.jobs,before.edit_number]);
            assert.deepEqual(cadRequests,[]);
            await tab.close();
        }
        const isolated = await browser.newContext({storageState:state,viewport,deviceScaleFactor:1});
        result.history = await historicalExplosion(await page(isolated),withExplosionVectors);
        assert.deepEqual(await designs(),original);
        assert.deepEqual(errors,[]);
        const note = JSON.stringify(result,null,2)+"\n";
        fs.writeFileSync(path.join(out,"拆解验收.json"),note);
        console.log(note);
    } finally { await browser.close(); }
}
main().catch(error=>{console.error(error);process.exitCode=1;});
