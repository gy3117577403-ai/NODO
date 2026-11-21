// Exercise the normal browser and worker against the database created by nodo.ps1 test.
const assert = require("node:assert/strict");
const crypto = require("node:crypto");
const fs = require("node:fs");
const path = require("node:path");
const {chromium} = require("playwright");
const {target} = require("./verify_selection.cjs");

const origin = "http://127.0.0.1:8079";
const root = path.resolve(__dirname,"../..");
const exchange = path.join(root,".nodo-draw/exchange");
const output = path.join(root,".nodo-draw/output/playwright/accessory-library");
const downloads = path.join(output,"下载");
const layoutOutput = path.join(output,"side-selection");
const layoutPhase = process.argv[2] || "";
const database = process.env.NODO_DRAW_BROWSER_DB;
const password = process.env.NODO_DRAW_BROWSER_PASSWORD;
const designModel = "nodo.draw.design";
const btn = (area,name) => area.getByRole("button",{name,exact:true});
const value = (area,name) => area.getByLabel(name,{exact:true});
const fileUrl = (id,key) => `/nodo/draw/file/${id}/${key}`;
const digest = data => crypto.createHash("sha256").update(data).digest("hex");
const read = name => JSON.parse(fs.readFileSync(name,"utf8"));
const screenshot = (page,name) => page.screenshot({path:path.join(output,name+".png"),animations:"disabled"});

async function rpc(context, route, params) {
    const response = await context.request.post(origin+route,{data:{jsonrpc:"2.0",method:"call",id:1,params}});
    const body = await response.json();
    if(body.error) throw Error(body.error.data?.message || body.error.message);
    return body.result;
}

function call(context, model, method, args=[]) {
    return rpc(context,`/web/dataset/call_kw/${model}/${method}`,{model,method,args,kwargs:{}});
}

async function signIn(browser, login) {
    const context = await browser.newContext({viewport:{width:1655,height:881},acceptDownloads:true});
    await rpc(context,"/web/session/authenticate",{db:database,login,password});
    assert.equal((await rpc(context,"/web/session/get_session_info",{})).db,database);
    return context;
}

async function openDesign(page, source) {
    const designs=await call(page.context(),designModel,"list_designs");
    const design=designs.find(item=>item.source===source);
    assert(design,source);
    await page.goto(`${origin}/odoo/technical-workbench?design=${design.id}`);
    await value(page,"选择设计").waitFor();
    assert.equal(await value(page,"选择设计").inputValue(),String(design.id));
    return design;
}

async function browseLibrary(page) {
    await page.goto(origin+"/odoo/accessory-library");
    await value(page,"搜索附件库").waitFor();
    assert.equal(await page.locator(".nd-library-item").count(),7);
    await value(page,"搜索附件库").fill("T5-55");
    await page.waitForFunction(()=>document.querySelectorAll(".nd-library-item").length===1);
    assert.equal(await page.locator(".nd-library-item").count(),1);
    await page.locator(".nd-library-view canvas").waitFor();
    await btn(page,"详细规则").click();
    await page.getByText("模型来源",{exact:true}).waitFor();
    await page.locator(".nd-library-view canvas").waitFor();
    await btn(page,"详细规则").click();
    await value(page,"搜索附件库").fill("");
    await page.locator(".nd-library-item").filter({hasText:"T5-55"}).click();
    await page.locator(".nd-library-view canvas").waitFor();
    await screenshot(page,"附件库-五孔连接板");
    await value(page,"附件状态").selectOption("pending");
    await page.waitForFunction(()=>document.querySelectorAll(".nd-library-item").length===2);
    assert.equal(await page.locator(".nd-library-item").count(),2);
    await page.locator(".nd-library-item").filter({hasText:"FC-CORNER-2020"}).click();
    await page.locator(".nd-library-view canvas").waitFor();
    await screenshot(page,"附件库-待工程核对角码");
}

async function workspace(page,id) {
    return call(page.context(),designModel,"workspace",[[id]]);
}

async function previewAndConfirm(page, design, expected) {
    const before=await workspace(page,design.id);
    const [previewResponse]=await Promise.all([
        page.waitForResponse(response=>new URL(response.url()).pathname.endsWith("/preview_assembly")),
        btn(page,"装配预览").click(),
    ]);
    const reply=await previewResponse.json();
    assert(reply.result,reply.error?.data?.message);
    const job = reply.result;
    await page.getByText("装配预览校核通过",{exact:true}).waitFor({timeout:180000});
    const phase=await page.context().request.get(origin+fileUrl(job,"mesh"));
    assert(phase.ok());
    const mesh=await phase.json();
    assert.deepEqual(mesh.parameters.accessories.map(part=>[part.definition.code,part.face]),expected);
    const draft=await workspace(page,design.id);
    assert.equal(draft.edit_number,before.edit_number);
    assert.deepEqual(draft.settings,before.settings);
    assert(draft.jobs.every(item=>item.id!==job),"未确认的预览已进入公共批次");
    await screenshot(page,design.source+"-装配预览");
    await btn(page,"确认装配").click();
    await page.locator(".nd-match .nd-tag").filter({hasText:/^已装配$/}).last().waitFor();
    const confirmed=await workspace(page,design.id);
    assert.equal(confirmed.edit_number,before.edit_number+1);
    assert(confirmed.assembly_validated);
    assert.deepEqual(confirmed.settings.instances.map(part=>[part.code,part.face]),expected);
    assert(confirmed.jobs.some(item=>item.id===job),"确认后未采用同一份校核预览");
    return expected;
}

async function selectSheet(page,name) {
    await page.locator(".nd-sheet").getByRole("button",{name:new RegExp(`${name}$`)}).click();
    await page.locator(".nd-drawing").waitFor();
}

function jobFiles(token) {
    assert(/^[a-f0-9]{32}$/.test(token),"错误的成果目录编号");
    const folder=path.join(exchange,token);
    const status=read(path.join(folder,"status.json"));
    assert.equal(status.state,"done");
    assert(/^run-[a-f0-9]{32}$/.test(status.run));
    const run=path.join(folder,status.run);
    const raw=key=>fs.readFileSync(path.join(run,status.files[key]));
    return {run,status,raw};
}

async function downloadBuild(page,id,files) {
    const sheets = files.status.sheets;
    const assembly = sheets.find(sheet=>sheet.category==="assembly");
    const door = sheets.find(sheet=>sheet.name==="门板展开图");
    const expected = [["bundle","工程图包.zip"],["step","整柜.step"],["bom","零件清单.csv"],["holes","孔位表.csv"],
        [assembly.key,"总装图.dwg",assembly.name],[door.key,"门板展开.dwg",door.name],[door.key+"c","门板切割.dxf",door.name]];
    const receipts=[];
    for (const [key,name,sheet] of expected) {
        if(sheet) await selectSheet(page,sheet);
        await btn(page,"下载").click();
        const pending = page.waitForEvent("download");
        await page.locator(`a[href="${fileUrl(id,key)}"]`).click();
        const download=await pending;
        const filename=path.join(downloads,name);
        await download.saveAs(filename);
        const sha=digest(fs.readFileSync(filename));
        assert.equal(sha,digest(files.raw(key)),name);
        receipts.push({name,sha256:sha});
    }
    return receipts;
}

async function runAE303(page) {
    const design=await openDesign(page,"AE-303");
    assert.equal(design.source_version,"2");
    await btn(page,"装配").click();
    const expected=[["AE-SQ35","door"],["T5-55","mount"],["EX-COVER","top"],["EX-BASE","bottom"]];
    for (const [i,[code,face]] of expected.entries()) {
        const row=page.getByRole("group",{name:`第${i+1}行 ${code}`,exact:true});
        assert((await row.innerText()).includes("× 1"));
        assert.equal(await value(row,`第${i+1}行安装面`).inputValue(),face);
    }
    await btn(page,"一键出图").click();
    await page.getByText(/请先预览并确认装配/).waitFor();
    await previewAndConfirm(page,design,expected);
    const [response]=await Promise.all([
        page.waitForResponse(response=>new URL(response.url()).pathname.endsWith("/apply_design")),
        btn(page,"一键出图").click(),
    ]);
    const reply=await response.json();
    assert(reply.result?.job_id,reply.error?.data?.message);
    const id=reply.result.job_id;
    console.log("AE-303 四行装配已确认，已提交实际 CAD 一键出图。");
    await btn(page,"下载").waitFor({timeout:900000});
    const job=(await workspace(page,design.id)).jobs.find(item=>item.id===id);
    assert.equal(job.state,"done");
    assert.equal(job.version,1);
    const [record]=await call(page.context(),"nodo.draw.job","read",[[id],["token"]]);
    const files=jobFiles(record.token);
    assert.equal(files.status.sheets.length,29);
    assert.equal(files.status.cut_count,12);
    assert.equal(files.status.step_solids,27);
    await screenshot(page,"AE-303-新总装图");
    const receipt={design:design.id,handoff:2,job:id,version:"V01",files:await downloadBuild(page,id,files)};
    fs.writeFileSync(path.join(downloads,"下载记录.json"),JSON.stringify(receipt,null,2));
    fs.writeFileSync(path.join(output,"new-run-path.txt"),files.run);
    return {revision:receipt.version,files:receipt.files.length,installed:expected};
}

async function checkV02(page) {
    const design=await openDesign(page,"AE-303");
    await btn(page,"图纸与版本").click();
    const archive=(await workspace(page,design.id)).jobs.find(item=>item.operation==="build"&&item.version===2);
    assert(archive);
    const [record]=await call(page.context(),"nodo.draw.job","read",[[archive.id],["token"]]);
    const snapshot=jobFiles(record.token);
    const panel=snapshot.status.sheets.find(item=>item.name==="门板展开图");
    await selectSheet(page,panel.name);
    const previewUrl=fileUrl(archive.id,panel.key+"p");
    await page.locator(`.nd-drawing[src="${previewUrl}"]`).waitFor();
    const picture=await page.context().request.get(origin+previewUrl);
    assert(picture.ok());
    assert.equal(digest(await picture.body()),digest(snapshot.raw(panel.key+"p")));
    const dwg=await page.context().request.get(origin+fileUrl(archive.id,panel.key));
    assert(dwg.ok());
    assert.equal(digest(await dwg.body()),digest(snapshot.raw(panel.key)));
    const [model]=await Promise.all([
        page.waitForResponse(response=>response.url()===origin+fileUrl(archive.id,"mesh")&&response.ok()),
        btn(page,"本版本三维").click(),
    ]);
    const mesh=await model.body();
    assert.equal(digest(mesh),digest(snapshot.raw("mesh")));
    assert.equal(JSON.parse(mesh).parameters.revision,"V02");
    await page.locator(".nd-archive-model canvas").waitFor();
    await screenshot(page,"AE-303-V02-原始三维");
    const bundle=await page.context().request.get(origin+fileUrl(archive.id,"bundle"));
    assert(bundle.ok());
    assert.equal(digest(await bundle.body()),digest(snapshot.raw("bundle")));
    return {revision:"V02",mesh:digest(mesh),drawing:digest(snapshot.raw(panel.key)),bundle:digest(snapshot.raw("bundle"))};
}

async function openAE202Picker(page) {
    const design=await openDesign(page,"AE-202");
    await btn(page,"装配").click();
    return {design,picker:await openPicker(page)};
}

async function openPicker(page) {
    await btn(page,"第1行从附件库选用").click();
    const picker=page.locator(layoutPhase==="before" ? ".modal" : ".nd-library-picker");
    await value(picker,"搜索附件库").waitFor();
    return picker;
}

async function checkAE202(page) {
    const {design,picker}=await openAE202Picker(page);
    await modelRow(picker,"FC-CORNER-2020").click();
    await picker.getByText("待工程核对，暂不可安装",{exact:true}).waitFor();
    assert(await btn(picker,"应用到本行").isDisabled());
    await modelRow(picker,"AE-SQ35").click();
    await picker.locator(".nd-library-note").filter({hasText:"柜型不符"}).waitFor();
    assert(await btn(picker,"应用到本行").isDisabled());
    await screenshot(page,"AE-202-单门方锁柜型不符");
    await modelRow(picker,"T5-55").click();
    await pickerFace(picker,"右门板").click();
    await btn(picker,"应用到本行").click();
    await previewAndConfirm(page,design,[["T5-55","door_right"]]);
    return {rightDoor:"T5-55",incompatible:"AE-SQ35",pending:"FC-CORNER-2020"};
}

async function settle(page) {
    await page.evaluate(()=>new Promise(resolve=>requestAnimationFrame(()=>requestAnimationFrame(resolve))));
}

function modelRow(area, code) {
    return area.locator(".nd-library-item").filter({hasText:code});
}

async function captureLayout(page, name) {
    await settle(page);
    await page.screenshot({path:path.join(layoutOutput,`${layoutPhase}-${page.viewportSize().width}-${name}.png`),animations:"disabled"});
}

const previewCanvas = area => area.locator(".nd-library-view canvas");
const noOverlay = {style:".nd-library-reset { visibility: hidden !important }", animations:"disabled"};

async function modelBounds(page, image) {
    return page.evaluate(async data => {
        const bitmap=await createImageBitmap(await (await fetch(`data:image/png;base64,${data}`)).blob());
        const {width,height}=bitmap;
        const ctx=new OffscreenCanvas(width,height).getContext("2d");
        ctx.drawImage(bitmap,0,0);
        const {data:pixels}=ctx.getImageData(0,0,width,height);
        let left=width, top=height, right=0, bottom=0;
        for (let y=0; y<height; y++) for (let x=0; x<width; x++) {
            const i=(y*width+x)*4;
            if (pixels[i]>208 || pixels[i+1]>220) continue;
            left=Math.min(left,x); right=Math.max(right,x); top=Math.min(top,y); bottom=Math.max(bottom,y);
        }
        return {height:bottom-top+1, fraction:(bottom-top+1)/height,
            margin:Math.min(left,top,width-1-right,height-1-bottom)};
    },image.toString("base64"));
}

async function imageDifference(page, original, current) {
    if (original.equals(current)) return 0;
    return page.evaluate(async images => {
        const pixels=await Promise.all(images.map(async data => {
            const bitmap=await createImageBitmap(await (await fetch(`data:image/png;base64,${data}`)).blob());
            const ctx=new OffscreenCanvas(bitmap.width,bitmap.height).getContext("2d");
            ctx.drawImage(bitmap,0,0);
            return ctx.getImageData(0,0,bitmap.width,bitmap.height).data;
        }));
        const [before,after]=pixels;
        if (before.length!==after.length) return 1;
        let changed=0;
        for (let i=0;i<before.length;i+=4) {
            const red=Math.abs(before[i]-after[i]);
            const green=Math.abs(before[i+1]-after[i+1]);
            const blue=Math.abs(before[i+2]-after[i+2]);
            if (Math.max(red,green,blue)>8) changed++;
        }
        return changed*4/before.length;
    },[original,current].map(image=>image.toString("base64")));
}

async function checkColumns(area) {
    const controls=await Promise.all(["搜索附件库","附件分类","附件状态"].map(name=>value(area,name).boundingBox()));
    assert(controls.every(control=>Math.abs(control.y-controls[0].y)<4),"筛选控件未在同一行");
    assert(controls.every((control,i)=>!i || control.x>=controls[i-1].x+controls[i-1].width),"筛选控件重叠");
    const grid=await area.locator(".nd-library-grid").boundingBox();
    const list=area.locator(".nd-library-list");
    const preview=await previewCanvas(area).boundingBox();
    const listRect=await list.boundingBox();
    assert(preview.x>=listRect.x+listRect.width && preview.width/grid.width>=.65,"三维未占双栏主区");
    assert(await list.evaluate(node=>node.scrollHeight<=node.clientHeight+1),"末行型号在首屏被截断");
}

async function checkInteraction(page, fit) {
    const canvas=previewCanvas(page), box=await canvas.boundingBox();
    const original=await canvas.screenshot(noOverlay);
    const x=box.x+box.width/2, y=box.y+box.height/2;
    await page.mouse.move(x,y);
    await page.mouse.wheel(0,-150);
    await settle(page);
    const closer=await canvas.screenshot(noOverlay);
    assert((await modelBounds(page,closer)).height>fit.height+10,"滚轮缩放未改变零件取景");
    await page.mouse.down();
    await page.mouse.move(x+100,y+24,{steps:9});
    await page.mouse.up();
    await settle(page);
    assert(await imageDifference(page,closer,await canvas.screenshot(noOverlay))>.005,"拖动未旋转零件");
    await btn(page,"复位视角").click();
    let difference=1;
    for (let frame=0; frame<4 && difference>.0025; frame++) {
        await settle(page);
        difference=await imageDifference(page,original,await canvas.screenshot(noOverlay));
    }
    assert(difference<=.0025,`复位后视角仍有偏移，画面差异 ${difference}`);

    const liveCanvas=await canvas.elementHandle();
    await btn(page,"详细规则").click();
    await page.getByText("板厚范围",{exact:true}).waitFor();
    assert(await liveCanvas.evaluate(node=>node.isConnected),"查看规则时三维被卸载");
    await captureLayout(page,"详细规则");
    await btn(page,"详细规则").click();

    const search=value(page,"搜索附件库");
    await search.fill("五孔连接板");
    await settle(page);
    assert.equal(await page.locator(".nd-library-item").count(),1);
    await search.fill("没有这个型号");
    await page.getByText("没有符合条件的附件",{exact:true}).waitFor();
    await search.fill("");
    await value(page,"附件分类").selectOption("安装与固定");
    await settle(page);
    assert.equal(await modelRow(page,"T5-55").count(),1);
    assert.equal(await modelRow(page,"FC-CORNER-2020").count(),1);
    assert.equal(await page.locator(".nd-library-item").count(),2);
    await value(page,"附件状态").selectOption("available");
    await settle(page);
    assert.equal(await page.locator(".nd-library-item").count(),1);
    await value(page,"附件分类").selectOption("");
    await value(page,"附件状态").selectOption("pending");
    await modelRow(page,"FC-CORNER-2020").click();
    assert.equal(await page.locator(".nd-library-item").count(),2);
    await canvas.waitFor();
    await value(page,"附件状态").selectOption("");
    await modelRow(page,"T5-55").click();
    await canvas.waitFor();

    const viewport=page.viewportSize();
    await page.setViewportSize({width:viewport.width,height:490});
    await settle(page);
    const toolbar=page.locator(".nd-library-bar");
    const before=await Promise.all([toolbar.boundingBox(),canvas.boundingBox()]);
    const list=page.locator(".nd-library-list");
    await list.hover();
    await page.mouse.wheel(0,340);
    await page.waitForFunction(()=>document.querySelector(".nd-library-list").scrollTop>0);
    assert.deepEqual(await Promise.all([toolbar.boundingBox(),canvas.boundingBox()]),before);
    await page.setViewportSize(viewport);
}

async function checkGallery(page, exerciseReturn) {
    await btn(page,"图集").click();
    const gallery=page.locator(".nd-library-gallery");
    await page.waitForFunction(()=>[...document.querySelectorAll(".nd-library-gallery img")]
        .filter(image=>image.complete && image.naturalWidth===320 && image.naturalHeight===216).length===7);
    assert(await gallery.evaluate(node=>[...node.querySelectorAll("img")].every(image=>{
        const frame=image.parentElement.getBoundingClientRect(), box=image.getBoundingClientRect();
        return getComputedStyle(image).objectFit==="contain" && Math.abs(frame.height-box.height)<1;
    })),"图集卡片应完整显示缩略图");
    assert.equal(await previewCanvas(page).count(),0,"图集应仅读取静态缩略图");
    await captureLayout(page,"附件图集");
    if (!exerciseReturn) return;

    const viewport=page.viewportSize();
    await page.setViewportSize({width:viewport.width,height:430});
    const tile=gallery.locator(".nd-library-tile").filter({hasText:"T5-55"});
    await tile.scrollIntoViewIfNeeded();
    const scroll=await gallery.evaluate(node=>node.scrollTop);
    assert(scroll>0,"图集测试窗口应触发滚动");
    await tile.click();
    await previewCanvas(page).waitFor();
    assert.equal(await previewCanvas(page).count(),1);
    await btn(page,"返回图集").click();
    await page.waitForFunction(expected=>Math.abs(document.querySelector(".nd-library-gallery")?.scrollTop-expected)<2,scroll);
    assert.equal(await previewCanvas(page).count(),0);
    await page.setViewportSize(viewport);

    await value(page,"搜索附件库").fill("角码");
    await value(page,"附件分类").selectOption("安装与固定");
    await value(page,"附件状态").selectOption("pending");
    await gallery.locator(".nd-library-tile").filter({hasText:"FC-CORNER-2020"}).click();
    await previewCanvas(page).waitFor();
    await btn(page,"返回图集").click();
    assert.equal(await value(page,"搜索附件库").inputValue(),"角码");
    assert.equal(await value(page,"附件分类").inputValue(),"安装与固定");
    assert.equal(await value(page,"附件状态").inputValue(),"pending");
    assert.equal(await gallery.locator(".nd-library-tile").count(),1);
}

const cabinetCanvas = page => page.locator(".nd-three-host canvas");
const applyChoice = area => btn(area,"应用到本行");
const firstFace = page => value(page,"第1行安装面");
const pickerFace = (area,name) => btn(area.getByRole("group",{name:"选型安装面",exact:true}),name);

async function clickCabinetFace(page, mesh, id, relative = [.37,.65]) {
    await btn(page,"复位视角").click();
    await settle(page);
    const face=mesh.faces.find(board=>board.id===id);
    assert(face,id);
    const point=target(mesh,face,await cabinetCanvas(page).boundingBox(),[face.width*relative[0],face.height*relative[1]]);
    await page.mouse.click(point.x,point.y);
}

async function checkPicker(page, picker, design, mesh) {
    const before=await workspace(page,design.id);
    const requests=[];
    const track=request=>{
        const method=new URL(request.url()).pathname.split("/").at(-1);
        if (["apply_design","preview_assembly","preview_cabinet"].includes(method)) requests.push(method);
    };
    page.on("request",track);
    await modelRow(picker,"FC-CORNER-2020").click();
    await picker.getByText("待工程核对，暂不可安装",{exact:true}).waitFor();
    assert(await applyChoice(picker).isDisabled());
    await btn(picker,"取消").click();

    const offsets=page.locator(".nd-assembly-locations");
    await offsets.locator("summary").click();
    await value(offsets,"横向").fill("37.5");
    await value(offsets,"纵向").fill("-16");
    await value(offsets,"转角").selectOption("90");
    picker=await openPicker(page);
    await pickerFace(picker,"左门板").click();
    await page.getByText("安装面 · 左门板",{exact:true}).waitFor();
    await clickCabinetFace(page,mesh,"door_right");
    await page.getByText("安装面 · 右门板",{exact:true}).waitFor();
    assert.equal(await pickerFace(picker,"右门板").getAttribute("aria-pressed"),"true");
    await captureLayout(page,"右门点选");
    await applyChoice(picker).click();

    const assertOriginal=async()=>{
        assert.equal(await firstFace(page).inputValue(),"door_right");
        if (await offsets.getAttribute("open")===null) await offsets.locator("summary").click();
        assert.equal(await value(offsets,"横向").inputValue(),"37.5");
        assert.equal(await value(offsets,"纵向").inputValue(),"-16");
        assert.equal(await value(offsets,"转角").inputValue(),"90");
    };
    await assertOriginal();
    picker=await openPicker(page);
    await modelRow(picker,"EX-COVER").click();
    await picker.getByText("请选择安装面",{exact:true}).waitFor();
    assert(await applyChoice(picker).isDisabled());
    await clickCabinetFace(page,mesh,"top",[.5,.55]);
    await page.getByText("安装面 · 顶板",{exact:true}).waitFor();
    await modelRow(picker,"EX-COVER").getByText("板面已选",{exact:true}).waitFor();
    await captureLayout(page,"顶板点选");
    await btn(picker,"取消").click();
    await assertOriginal();

    picker=await openPicker(page);
    await pickerFace(picker,"安装板").click();
    await page.getByText("安装面 · 安装板",{exact:true}).waitFor();
    await captureLayout(page,"柜门闭合时选择安装板");
    await applyChoice(picker).click();
    assert.equal(await firstFace(page).inputValue(),"mount");
    await page.getByText("安装基准已变更，请重新核对位置。",{exact:true}).waitFor();
    assert.notEqual(await value(offsets,"横向").inputValue(),"37.5");

    picker=await openPicker(page);
    await modelRow(picker,"EX-COVER").click();
    await pickerFace(picker,"顶板").click();
    await applyChoice(picker).click();
    await btn(page,"第1行从附件库选用").getByText("平板防尘罩",{exact:true}).waitFor();
    assert.equal(await firstFace(page).inputValue(),"top");
    const after=await workspace(page,design.id);
    assert.equal(after.edit_number,before.edit_number);
    assert.deepEqual(after.settings,before.settings);
    assert.deepEqual(requests,[],"选型操作不应提交 CAD 或写入服务器");
    page.off("request",track);
}

async function checkLayout(page) {
    fs.mkdirSync(layoutOutput,{recursive:true});
    const fits=[];
    for (const [width,height] of [[1173,871],[1655,881]]) {
        await page.setViewportSize({width,height});
        await page.goto(origin+"/odoo/accessory-library");
        await modelRow(page,"T5-55").click();
        assert.equal(await page.locator(".nd-library-item").count(),7);
        await page.locator(".nd-library-view canvas").waitFor();
        await captureLayout(page,"附件库");
        if (layoutPhase==="after") {
            await checkColumns(page);
            const fit=await modelBounds(page,await previewCanvas(page).screenshot(noOverlay));
            assert(fit.fraction>=.60 && fit.fraction<.90 && fit.margin>=20,JSON.stringify(fit));
            fits.push({viewport:[width,height],modelHeight:fit.height,fraction:fit.fraction,minMargin:fit.margin});
            if (width===1173) await checkInteraction(page,fit);
            await checkGallery(page,width===1173);
        }

        if (layoutPhase==="before") {
            const {picker}=await openAE202Picker(page);
            await modelRow(picker,"AE-SQ35").click();
            assert(await btn(picker,"使用此型号").isDisabled());
            await previewCanvas(picker).waitFor();
            await captureLayout(page,"AE-202选型");
            continue;
        }

        const nextMesh=page.waitForResponse(response=>/\/nodo\/draw\/file\/\d+\/mesh$/.test(response.url()) && response.ok(),{timeout:180000});
        const design=await openDesign(page,"AE-202");
        await btn(page,"装配").click();
        const mesh=await (await nextMesh).json();
        const canvas=cabinetCanvas(page);
        await canvas.waitFor({timeout:30000});
        const rect=await canvas.boundingBox();
        const picker=await openPicker(page);
        await page.getByText("安装面 · 右门板",{exact:true}).waitFor();
        assert.equal(await page.locator(".modal").count(),0);
        assert.equal(await page.locator("canvas").count(),1);
        assert.deepEqual(await canvas.boundingBox(),rect,"打开选型栏后柜体画布位置变化");
        assert.match(await picker.locator(".nd-picker-head").innerText(),/AE-202.*双开门.*第 1 行.*× 1/);
        assert.match(await picker.locator(".nd-library-item").first().innerText(),/T5-55/);
        await modelRow(picker,"AE-SQ35").click();
        await picker.locator(".nd-library-note").filter({hasText:"柜型不符"}).waitFor();
        assert(await applyChoice(picker).isDisabled());
        await captureLayout(page,"AE-202选型");
        await modelRow(picker,"T5-55").click();
        await page.getByText("安装面 · 右门板",{exact:true}).waitFor();
        await captureLayout(page,"柜体右侧选型");
        if (width===1173) await checkPicker(page,picker,design,mesh);
    }
    if (fits.length) fs.writeFileSync(path.join(layoutOutput,"取景测量.json"),JSON.stringify(fits,null,2));
}

async function main() {
    assert(/^nodo_test_\d{14}$/.test(database) && password,"请用 nodo.ps1 test nodo_draw 启动附件库验收");
    assert(["","before","after"].includes(layoutPhase),"附件库界面验收阶段无效");
    const browser=await chromium.launch({channel:"chrome"});
    const errors=[];
    let currentPage;
    async function open(login) {
        const context=await signIn(browser,login);
        const page=await context.newPage();
        currentPage=page;
        page.setDefaultTimeout(18000);
        page.on("pageerror",error=>errors.push(error.message));
        return page;
    }
    try {
        const engineer=await open("draw.engineer@nodo.test");
        if (layoutPhase) {
            await checkLayout(engineer);
            if (layoutPhase === "after") {
                const catalog=await call(engineer.context(),"nodo.draw.accessory","list_accessory_models");
                const ref=catalog.find(item=>item.code==="T5-55").thumbnail;
                const otherCompany=await signIn(browser,"draw.archive@nodo.test");
                assert.equal((await otherCompany.request.get(origin+ref)).status(),404);
                await otherCompany.close();
            }
            assert.deepEqual(errors,[]);
            console.log(`附件库 ${layoutPhase} 界面验收 1173×871、1655×881 已完成。`);
            return;
        }
        fs.mkdirSync(downloads,{recursive:true});
        await browseLibrary(engineer);
        const archive=await open("draw.archive@nodo.test");
        const original=await checkV02(archive);
        currentPage=engineer;
        const double=await checkAE202(engineer);
        const fresh=await runAE303(engineer);
        assert.deepEqual(errors,[]);
        const results={catalogRecords:7,pendingRecords:2,AE303:fresh,V02:original,AE202:double};
        fs.writeFileSync(path.join(output,"浏览器验收.json"),JSON.stringify(results,null,2));
        console.log(JSON.stringify(results,null,2));
    } catch (error) {
        if(currentPage) {
            console.error((await currentPage.locator("body").innerText()).slice(-1000));
            await screenshot(currentPage,"验收诊断").catch(()=>{});
        }
        throw error;
    } finally {
        await browser.close();
    }
}

main().catch(error=>{console.error(error);process.exitCode=1;});
