// CAD viewport acceptance. Adds one hole to each designated development sample,
// reads the new CAD mesh, then removes only that hole and verifies the restoration.
const assert = require("node:assert/strict");
const fs = require("node:fs");
const path = require("node:path");
const {chromium} = require("playwright");
const dest = path.resolve(".nodo-draw/viewport-check");
const pageUrl = "http://127.0.0.1:8079/odoo/technical-workbench";
const glCanvas = ".nd-three-host canvas";
const dot = (a, b) => a.reduce((sum, n, i) => sum + n * b[i], 0);
const sub = (a, b) => a.map((n, i) => n - b[i]);
const plus = (a, b, k = 1) => a.map((n, i) => n + k * b[i]);
const unit = v => v.map(n => n / Math.hypot(...v));
const cross = (a, b) => [a[1]*b[2]-a[2]*b[1], a[2]*b[0]-a[0]*b[2], a[0]*b[1]-a[1]*b[0]];
const meshResponse = r => /\/nodo\/draw\/file\/\d+\/mesh$/.test(r.url()) && r.ok();
const meshFrom = async (p, r) => (await p.request.get(r.url())).json();
const near = (a, b, tolerance) => assert.ok(Math.abs(a - b) <= tolerance, a + " 与 " + b + " 超差");

// Independent pinhole projection of a CAD face point into the original ISO view.
// Round to an actual browser pixel, then intersect its ray with the known plane.
function target(model, face, box) {
    const all = model.parts.map(p => p.bounds);
    const lo = [0,1,2].map(i => Math.min(...all.map(b => b[0][i])));
    const hi = [0,1,2].map(i => Math.max(...all.map(b => b[1][i])));
    const center = lo.map((n,i) => (n + hi[i])/2);
    const dir = unit([.85,-1.35,.8]), right = unit(cross([0,0,1],dir)), up = cross(dir,right);
    const tanV = Math.tan(34 * Math.PI / 360), tanH = tanV * box.width / box.height;
    let distance = 200;
    for (const x of [lo[0],hi[0]]) for (const y of [lo[1],hi[1]]) for (const z of [lo[2],hi[2]]) {
        const v = sub([x,y,z], center);
        distance = Math.max(distance, Math.abs(dot(v,right))/tanH + dot(v,dir), Math.abs(dot(v,up))/tanV + dot(v,dir));
    }
    const camera = plus(center,dir,distance * 1.2);
    const aim = plus(plus(face.origin,face.uAxis,face.width*.37),face.vAxis,face.height*.65);
    const rel = sub(aim,camera), depth = -dot(rel,dir);
    const x = Math.round(box.x + box.width*(1+dot(rel,right)/(depth*tanH))/2);
    const y = Math.round(box.y + box.height*(1-dot(rel,up)/(depth*tanV))/2);
    const ray = plus(plus(dir.map(n=>-n),right,(2*(x-box.x)/box.width-1)*tanH),up,(1-2*(y-box.y)/box.height)*tanV);
    const hit = plus(camera, ray, dot(sub(face.origin,camera),face.normal)/dot(ray,face.normal));
    return {x,y,u:dot(sub(hit,face.origin),face.uAxis),v:dot(sub(hit,face.origin),face.vAxis)};
}

function faceSurface(model, id) {
    const face = model.faces.find(f => f.id === id);
    const part = model.parts.find(p => p.id === face.part);
    const points = part.vertices.map(point => {
        const d = sub(point,face.origin);
        return [dot(d,face.uAxis),dot(d,face.vAxis),dot(d,face.normal)];
    });
    const triangles = part.triangles.map(t => t.map(i => points[i])).filter(t => t.every(p => Math.abs(p[2]) < .02));
    assert(triangles.length);
    return (u,v) => triangles.some(([a,b,c]) => {
        const side = (p,q) => (q[0]-p[0])*(v-p[1]) - (q[1]-p[1])*(u-p[0]);
        const values = [side(a,b),side(b,c),side(c,a)];
        return Math.max(...values) >= 1e-6 && Math.min(...values) >= -1e-6 ||
            Math.min(...values) <= -1e-6 && Math.max(...values) <= 1e-6;
    });
}

async function saveMesh(page) {
    const next = page.waitForResponse(meshResponse, {timeout: 180000});
    const save = page.waitForResponse(r => r.url().includes("apply_design"));
    await page.getByRole("button",{name:"保存并预览开孔"}).click();
    const out = await (await save).json();
    assert(out.result?.job_id, "设计未保存");
    const result = await next;
    assert(new URL(result.url()).pathname.endsWith("/" + out.result.job_id + "/mesh"));
    return meshFrom(page,result);
}

async function examine(context, code, id) {
    const page = await context.newPage();
    const errors = [];
    page.on("pageerror", e => errors.push(e.message));
    try {
        let current = page.waitForResponse(meshResponse);
        await page.goto(pageUrl);
        if (code === "AE-202") {
            await current;
            current = page.waitForResponse(meshResponse);
            await page.getByLabel("选择设计").selectOption({label:"AE-202 · 双门配电箱"});
        }
        const initial = await meshFrom(page, await current);
        const face = initial.faces.find(f => f.id === id);
        const canvas = page.locator(glCanvas);
        await canvas.waitFor();
        await page.locator(".nd-overlay").waitFor({state:"detached"});
        await page.evaluate(() => new Promise(resolve => requestAnimationFrame(() => requestAnimationFrame(resolve))));
        const point = target(initial,face,await canvas.boundingBox());
        await page.mouse.click(point.x,point.y);
        await page.getByLabel("加工板面").waitFor({timeout:4000});
        assert.equal(await page.getByLabel("加工板面").inputValue(),id);
        const u = Number(await page.getByLabel("横向 U").inputValue());
        const v = Number(await page.getByLabel("纵向 V").inputValue());
        near(u,point.u,.15); near(v,point.v,.15);
        const isDouble = id === "door_right";
        await page.getByLabel("孔型").selectOption(isDouble?"rectangle":"circle");
        if (isDouble) {
            await page.getByLabel("孔宽").fill("24"); await page.getByLabel("孔高").fill("14");
        } else {
            await page.getByLabel("直径").fill("12");
        }
        const prior = await page.locator("button[aria-label^='移除 H']").evaluateAll(buttons=>buttons.map(b=>b.getAttribute("aria-label")));
        assert.deepEqual(prior, ["移除 H1"],"只接受原始开发样例");
        assert(faceSurface(initial,id)(u,v), "新增孔位原先应有板材");
        await page.getByRole("button",{name:"添加孔位"}).click();
        await page.screenshot({path:path.join(dest,code+"-选面开孔.png")});
        try {
            const changed = await saveMesh(page);
            const hole = changed.parameters.holes.find(h=>h.id==="H2");
            assert(hole && hole.face===id && hole.u===u && hole.v===v);
            const solid = faceSurface(changed,id);
            const a = isDouble?12:6, b = isDouble?7:6;
            for (const [du,dv] of [[0,0],[a-.4,0],[-a+.4,0],[0,b-.4],[0,-b+.4]]) assert(!solid(u+du,v+dv),"孔内残留面");
            for (const [du,dv] of [[a+.4,0],[-a-.4,0],[0,b+.4],[0,-b-.4]]) assert(solid(u+du,v+dv),"孔边材料缺失");
        } finally {
            if (await page.getByLabel("移除 H2").count()) {
                await page.getByLabel("移除 H2").click();
                const restored = await saveMesh(page);
                assert(!restored.parameters.holes.some(h=>h.id==="H2"));
                assert(faceSurface(restored,id)(u,v),"原板面未恢复");
            }
        }
        assert.deepEqual(errors, []);
        return {code,face:id,pointMm:[u,v],independentMm:[+point.u.toFixed(3),+point.v.toFixed(3)],
            shape:isDouble?"24 × 14 mm":"Ø12 mm",insidePoints:5,outsidePoints:4,restored:true};
    } finally { await page.close(); }
}

async function hardware(context) {
    const page = await context.newPage();
    try {
        await page.goto(pageUrl);
        const selector = page.getByLabel("选择设计");
        const option = selector.locator("option").filter({hasText:"AE-303"}).first();
        const design = await option.getAttribute("value");
        const response = page.waitForResponse(meshResponse);
        await page.goto(pageUrl + "?design=" + design);
        await page.getByRole("heading", {name:"五金装配柜"}).waitFor();
        const model = await meshFrom(page, await response);
        const occurrences = model.parameters.accessories;
        assert.deepEqual(occurrences.map(a=>[a.definition.code,a.face]),
            [["AE-SQ35","door"],["T5-55","mount"],["EX-COVER","top"],["EX-BASE","bottom"]]);
        const groups = occurrences.map(a=>model.parts.filter(p=>p.accessoryId===a.id));
        assert.deepEqual(groups.map(parts=>parts.length),[1,1,5,5]);
        assert(groups[0][0].group === "door" && groups[1][0].group === "body");
        assert.deepEqual(groups[0][0].bounds,[[347.5,-5,152.5],[395,21,187.5]]);
        assert.equal(model.parts.filter(p=>p.id.startsWith("hinge_")).length,2);
        assert.equal(model.parts.filter(p=>p.id.startsWith("stud_")).length,4);
        const door = model.faces.find(f=>f.id==="door");
        const material = faceSurface(model,"door");
        const u = door.width-52.5, v = door.height/2;
        for (const [du,dv] of [[1,0],[-1,0],[0,1],[0,-1],[1,1]]) {
            assert(!material(u+du*10.55,v+dv*10.55));
            assert(material(u+du*10.65,v+dv*10.65));
        }
        assert.equal(model.parameters.holes.filter(h=>h.ownerAccessory===occurrences[0].id).length,0);
        const check = model.accessoryValidation;
        assert.equal(check.status,"checked-samples");
        assert.deepEqual(check.issues,[]);
        assert.deepEqual(check.sampledAngles,Array.from({length:12},(_,i)=>i*10));
        await page.getByRole("button",{name:"附件装配",exact:true}).click();
        assert.equal(await page.getByText("已装配",{exact:true}).count(),4);
        const view = page.locator(glCanvas);
        await view.waitFor();
        await page.waitForTimeout(250);
        await page.screenshot({path:path.join(dest,"AE-303-合门.png")});
        const closed = await view.screenshot();
        const box = await view.boundingBox(), x = box.x+box.width*.5, y = box.y+box.height*.5;
        await page.mouse.move(x,y); await page.mouse.down();
        await page.mouse.move(x+70,y+25,{steps:8}); await page.mouse.up();
        await page.waitForTimeout(250);
        const rotated = await view.screenshot();
        assert(!closed.equals(rotated),"旋转未更新画面");
        await page.mouse.wheel(0,-170); await page.waitForTimeout(300);
        assert(!rotated.equals(await view.screenshot()),"缩放未更新画面");
        await page.getByRole("button",{name:"打开柜门"}).click();
        await page.getByRole("button",{name:"复位视角"}).click();
        await page.waitForTimeout(400);
        await page.screenshot({path:path.join(dest,"AE-303-开门.png")});
        const report = {design, parts:model.parts.length, hinges:2, studs:4, nativeOpeningMm:21.2, neckMm:21,
            occurrences:occurrences.map((a,i)=>({code:a.definition.code,face:a.face,solids:groups[i].length})),
            closedPairs:check.staticPairs, sampledDegrees:check.sampledAngles, collisions:check.issues.length};
        fs.writeFileSync(path.join(dest,"hardware.json"), JSON.stringify(report,null,2) + "\n");
        console.log(JSON.stringify(report));
    } finally { await page.close(); }
}

async function main() {
    fs.mkdirSync(dest, {recursive:true});
    const browser = await chromium.launch({channel:"chrome"});
    try {
        const context = await browser.newContext({storageState:".nodo-draw/dev-session.local.json",
            viewport:{width:1173,height:871},deviceScaleFactor:1});
        const session = await context.request.post(new URL("/web/session/get_session_info",pageUrl).href,
            {data:{jsonrpc:"2.0",method:"call",params:{},id:1}});
        assert.equal((await session.json()).result?.db,"nodo_dev","选面加工验收只能在开发库运行");
        if (process.argv.includes("--hardware")) return await hardware(context);
        const results = [];
        for (const [code,face] of [["AE-101","door"],["AE-202","door_right"]]) {
            const row = await examine(context,code,face);
            results.push(row);
            console.log(JSON.stringify(row));
            fs.writeFileSync(path.join(dest,"selection.json"), JSON.stringify(results,null,2) + "\n");
        }
    } finally { await browser.close(); }
}
main().catch(e=>{console.error(e);process.exitCode=1;});
