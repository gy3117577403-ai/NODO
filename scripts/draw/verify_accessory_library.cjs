// Exercise the normal browser and worker against the database created by nodo.ps1 test.
const assert = require("node:assert/strict");
const crypto = require("node:crypto");
const fs = require("node:fs");
const path = require("node:path");
const {chromium} = require("playwright");

const origin = "http://127.0.0.1:8079";
const root = path.resolve(__dirname,"../..");
const exchange = path.join(root,".nodo-draw/exchange");
const output = path.join(root,".nodo-draw/output/playwright/accessory-library");
const downloads = path.join(output,"下载");
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
    await page.getByRole("heading",{name:"附件库",exact:true}).waitFor();
    assert.equal(await page.locator(".nd-library-item").count(),7);
    await value(page,"搜索附件库").fill("T5-55");
    await page.waitForFunction(()=>document.querySelectorAll(".nd-library-item").length===1);
    assert.equal(await page.locator(".nd-library-item").count(),1);
    await page.locator(".nd-library-view canvas").waitFor();
    await btn(page,"安装规则").click();
    await page.getByText("门板 / 左门、右门板、安装板",{exact:true}).first().waitFor();
    await btn(page,"三维模型").click();
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

async function checkAE202(page) {
    const design=await openDesign(page,"AE-202");
    await btn(page,"装配").click();
    await btn(page,"第1行从附件库选用").click();
    const dialog=page.locator(".modal").filter({hasText:"从附件库选用"});
    await value(dialog,"搜索附件库").fill("FC-CORNER-2020");
    await dialog.getByText("待工程核对，暂不可安装",{exact:true}).waitFor();
    assert(await btn(dialog,"使用此型号").isDisabled());
    await value(dialog,"搜索附件库").fill("AE-SQ35");
    await dialog.getByText("柜型不符",{exact:true}).waitFor();
    assert(await btn(dialog,"使用此型号").isDisabled());
    await dialog.locator(".nd-library-view canvas").waitFor();
    await screenshot(page,"AE-202-单门方锁柜型不符");
    await value(dialog,"搜索附件库").fill("T5-55");
    await btn(dialog,"使用此型号").click();
    await value(page,"第1行安装面").selectOption("door_right");
    await previewAndConfirm(page,design,[["T5-55","door_right"]]);
    return {rightDoor:"T5-55",incompatible:"AE-SQ35",pending:"FC-CORNER-2020"};
}

async function main() {
    assert(/^nodo_test_\d{14}$/.test(database) && password,"请用 nodo.ps1 test nodo_draw -DrawBrowser 运行");
    fs.mkdirSync(downloads,{recursive:true});
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
