// Browser acceptance with a signed-in engineering test session on nodo_dev.
const assert = require("node:assert/strict");
const crypto = require("node:crypto");
const fs = require("node:fs");
const path = require("node:path");
const {chromium} = require("playwright");

const root = path.resolve(__dirname, "../..");
const exchange = path.join(root, ".nodo-draw", "exchange");
const destination = path.resolve(process.argv[2] || path.join(root, ".nodo-draw", "output", "playwright", "archive"));
const downloads = path.join(destination, "下载");
const viewport = {width: 1173, height: 871};
const origin = "http://127.0.0.1:8079";
const read = filename => JSON.parse(fs.readFileSync(filename, "utf8"));
const digest = bytes => crypto.createHash("sha256").update(bytes).digest("hex");
const fileUrl = (id, key) => `/nodo/draw/file/${id}/${key}`;

function archivedBuild(source, handoff, revision) {
    for (const entry of fs.readdirSync(exchange, {withFileTypes: true})) {
        if (!entry.isDirectory()) continue;
        const folder = path.join(exchange, entry.name);
        const request = path.join(folder, "request.json");
        if (!fs.existsSync(request)) continue;
        const job = read(request);
        if (job.operation !== "build" || job.source !== source ||
            job.source_version !== handoff || job.parameters.revision !== revision) continue;
        const status = read(path.join(folder, "status.json"));
        return {status, run: path.join(folder, status.run)};
    }
    assert.fail(`${source} 交接版 ${handoff} 的 ${revision} 归档缺失`);
}

function archivedHash(build, key) {
    return digest(fs.readFileSync(path.join(build.run, build.status.files[key])));
}

async function chooseVersion(page, revision) {
    const select = page.getByLabel("图纸版本");
    const option = select.locator("option").filter({hasText: new RegExp(`^${revision} `)});
    const id = await option.getAttribute("value");
    await select.selectOption(id);
    return id;
}

async function openSheet(page, id, build, sheetName) {
    const sheet = build.status.sheets.find(item => item.name === sheetName);
    assert(sheet, sheetName);
    await page.locator(".nd-sheet").getByRole("button", {name: new RegExp(`${sheetName}$`)}).click();
    const url = fileUrl(id, sheet.key + "p");
    const image = page.locator(`.nd-drawing[src="${url}"]`);
    await image.waitFor();
    const response = await page.request.get(origin + url);
    assert(response.ok());
    assert.equal(digest(await response.body()), archivedHash(build, sheet.key + "p"), sheetName);
    return {image, sheet};
}

async function drawingPoint(image, x, y) {
    return image.evaluate((element, [u, v]) => {
        const box = element.getBoundingClientRect();
        const aspect = element.naturalWidth / element.naturalHeight;
        const width = Math.min(box.width, box.height * aspect);
        const height = width / aspect;
        return {x: box.x + box.width / 2 + (u - .5) * width, y: box.y + box.height / 2 + (v - .5) * height, width};
    }, [x, y]);
}

async function focusDrawing(page, image, u, v, scale, offsetY = 0) {
    const surface = await page.locator(".nd-drawing-surface").boundingBox();
    const before = await drawingPoint(image, u, v);
    const wheelDelta = Math.round(-Math.log(scale) / .0025);
    const zoom = `${Math.round(Math.exp(-wheelDelta * .0025) * 100)}%`;
    await page.mouse.move(before.x, before.y);
    await page.mouse.wheel(0, wheelDelta);
    await page.locator(".nd-reader-tools output").filter({hasText: zoom}).waitFor();
    const after = await drawingPoint(image, u, v);
    const anchorErrorPx = Math.hypot(after.x - before.x, after.y - before.y);
    assert(anchorErrorPx <= 2, "滚轮放大后鼠标所指图纸点发生偏移");
    const center = {x: surface.x + surface.width / 2, y: surface.y + surface.height / 2 + offsetY};
    await page.mouse.move(after.x, after.y);
    await page.mouse.down();
    await page.mouse.move(center.x, center.y, {steps: 10});
    await page.mouse.up();
    const moved = await drawingPoint(image, u, v);
    const panErrorPx = Math.hypot(moved.x - center.x, moved.y - center.y);
    assert(panErrorPx <= 2, "拖拽后图纸点没有到达目标位置");
    return {zoom, anchorErrorPx, panErrorPx};
}

async function showModel(page, id, build, revision, action) {
    const url = origin + fileUrl(id, "mesh");
    const responsePromise = page.waitForResponse(response => response.url() === url && response.ok());
    await action();
    const response = await responsePromise;
    const sha256 = digest(await response.body());
    assert.equal(sha256, archivedHash(build, "mesh"), `${revision} 读取了另一批次的网格`);
    await page.locator(".nd-archive-model").getByText(`${revision} · 本版本三维`, {exact: true}).waitFor();
    await page.locator(".nd-archive-model .ae-viewport[data-conflict-parts] canvas").waitFor();
    return {revision, job: Number(id), sha256};
}

async function saveDownload(page, id, build, key, name) {
    const download = page.waitForEvent("download");
    await page.locator(`a[href="${fileUrl(id, key)}"]`).click();
    const filename = path.join(downloads, name);
    const received = await download;
    await received.saveAs(filename);
    const sha256 = digest(fs.readFileSync(filename));
    assert.equal(sha256, archivedHash(build, key), name);
    return {name, url: received.url(), sha256};
}

async function checkAE303(page) {
    const build = archivedBuild("AE-303", "2", "V02");
    await page.getByLabel("选择设计").selectOption({label: "AE-303 · 五金装配柜 · 交接版 2"});
    await page.getByRole("heading", {name: "五金装配柜"}).waitFor();
    const design = Number(await page.getByLabel("选择设计").inputValue());
    await page.getByRole("button", {name: /图纸与版本/}).click();
    const id = await chooseVersion(page, "V02");
    const door = await openSheet(page, id, build, "门板展开图");
    const zoom = await focusDrawing(page, door.image, .737, .497, 4, -24);
    const pose = await door.image.getAttribute("style");
    await page.screenshot({path: path.join(destination, "V02-门板方孔.png")});
    await showModel(page, id, build, "V02", () => page.getByRole("button", {name: "本版本三维"}).click());
    await page.getByRole("button", {name: "打开柜门", exact: true}).click();
    await page.getByRole("button", {name: "合上柜门", exact: true}).waitFor();
    await page.evaluate(() => new Promise(resolve => requestAnimationFrame(() => requestAnimationFrame(resolve))));
    await page.screenshot({path: path.join(destination, "V02-同版三维.png")});
    await page.getByRole("button", {name: "图纸", exact: true}).click();
    await door.image.waitFor();
    assert.equal(await door.image.getAttribute("style"), pose, "返回门板图时丢失放大和平移位置");
    await page.getByRole("button", {name: "适应窗口"}).click();
    await page.locator(".nd-reader-tools output").filter({hasText: /^100%$/}).waitFor();
    const fitPose = await door.image.getAttribute("style");
    await page.getByRole("button", {name: "放大图纸"}).click();
    await page.locator(".nd-reader-tools output").filter({hasText: /^125%$/}).waitFor();
    await page.getByRole("button", {name: "缩小图纸"}).click();
    await page.locator(".nd-reader-tools output").filter({hasText: /^100%$/}).waitFor();
    assert.equal(await door.image.getAttribute("style"), fitPose);

    const bills = [];
    for (const [index, centerY] of [[1, .40], [2, .20]]) {
        const bill = await openSheet(page, id, build, `零件明细表 ${index}/2`);
        const fit = await drawingPoint(bill.image, .46, centerY);
        const surface = await page.locator(".nd-drawing-surface").boundingBox();
        await focusDrawing(page, bill.image, .46, centerY, surface.width / (fit.width * .84));
        await page.screenshot({path: path.join(destination, `V02-零件明细${index}.png`)});
        bills.push(bill.sheet.key);
    }
    const modelKey = build.status.sheets.find(sheet => sheet.category === "assembly").key;
    const receipts = [];
    for (const [key, name] of [["bundle", "工程图包.zip"], ["step", "整柜.step"], ["bom", "零件清单.csv"],
        ["holes", "孔位表.csv"], [modelKey, "总装图.dwg"], [door.sheet.key, "门板展开.dwg"], [door.sheet.key + "c", "门板切割.dxf"],
        [bills[0], "零件明细表1.dwg"], [bills[1], "零件明细表2.dwg"]]) {
        receipts.push(await saveDownload(page, id, build, key, name));
    }
    const receipt = {design, handoff: 2, job: Number(id), version: "V02", files: receipts};
    fs.writeFileSync(path.join(downloads, "下载记录.json"), JSON.stringify(receipt, null, 2) + "\n");
    await chooseVersion(page, "V01");
    await page.locator(".nd-archive-state").getByText("生成失败", {exact: true}).waitFor();
    assert.equal(await page.locator(".nd-drawing, .nd-archive-model canvas, .nd-downloads").count(), 0);
    await chooseVersion(page, "V02");
    await showModel(page, id, build, "V02", () => page.getByRole("button", {name: "本版本三维"}).click());
    await chooseVersion(page, "V01");
    await page.locator(".nd-archive-state").getByText("生成失败", {exact: true}).waitFor();
    assert.equal(await page.locator(".nd-archive-model canvas").count(), 0);
    await chooseVersion(page, "V02");
    await page.getByRole("button", {name: "图纸", exact: true}).click();
    await openSheet(page, id, build, "门板展开图");
    return {job: Number(id), run: build.run, zoom, verifiedDownloads: receipts.length, failedBatchCleared: true};
}

async function checkAE101(page) {
    const builds = new Map(["V05", "V06"].map(revision => [revision, archivedBuild("AE-101", "1", revision)]));
    await page.getByLabel("选择设计").selectOption({label: "AE-101 · 壁挂控制箱"});
    await page.getByRole("heading", {name: "壁挂控制箱"}).waitFor();
    const width = page.getByLabel("柜宽", {exact: true});
    const draft = String(Number(await width.inputValue()) + 1);
    await width.fill(draft);
    await page.getByRole("button", {name: /图纸与版本/}).click();
    const switches = [];
    const ids = new Map();
    for (const revision of ["V05", "V06", "V05"]) {
        const id = await chooseVersion(page, revision);
        ids.set(revision, id);
        const build = builds.get(revision);
        const sheet = build.status.sheets.find(sheet => sheet.category === "assembly");
        await openSheet(page, id, build, sheet.name);
        switches.push(await showModel(page, id, build, revision, () => page.getByRole("button", {name: "本版本三维"}).click()));
        await page.getByRole("button", {name: "图纸", exact: true}).click();
    }
    assert.notEqual(switches[0].sha256, switches[1].sha256);
    assert.deepEqual(switches[0], switches[2]);

    await showModel(page, ids.get("V05"), builds.get("V05"), "V05",
        () => page.getByRole("button", {name: "本版本三维"}).click());
    const delayedUrl = origin + fileUrl(ids.get("V06"), "mesh");
    const release = Promise.withResolvers();
    await page.route(delayedUrl, async route => {
        await release.promise;
        await route.continue().catch(() => {});
    }, {times: 1});
    try {
        const loading = page.waitForRequest(delayedUrl);
        await chooseVersion(page, "V06");
        await loading;
        await page.getByRole("status").filter({hasText: "正在加载本版本三维"}).waitFor();
        assert.equal(await page.locator(".nd-archive-model canvas").count(), 0);
        await showModel(page, ids.get("V05"), builds.get("V05"), "V05", () => chooseVersion(page, "V05"));
    } finally {
        release.resolve();
    }
    await page.getByRole("button", {name: "设计视图", exact: true}).click();
    assert.equal(await width.inputValue(), draft, "切换归档后丢失未保存的设计草稿");
    return {switches, slowResponseCleared: true, draftPreserved: true};
}

async function main() {
    fs.mkdirSync(downloads, {recursive: true});
    const browser = await chromium.launch({channel: "chrome"});
    try {
        const context = await browser.newContext({
            storageState: path.join(root, ".nodo-draw", "dev-session.local.json"), viewport, deviceScaleFactor: 1,
        });
        const session = await context.request.post(origin + "/web/session/get_session_info",
            {data: {jsonrpc: "2.0", method: "call", params: {}, id: 1}});
        assert.equal((await session.json()).result?.db, "nodo_dev", "阅图验收只能在已登录的开发库中执行");
        const page = await context.newPage();
        page.setDefaultTimeout(15000);
        const errors = [];
        page.on("pageerror", error => errors.push(error.message));
        await page.goto(origin + "/odoo/technical-workbench");
        const data = {viewport, ae303: await checkAE303(page), ae101: await checkAE101(page)};
        assert.deepEqual(errors, []);
        const report = JSON.stringify(data, null, 2) + "\n";
        fs.writeFileSync(path.join(destination, "浏览器实测.json"), report);
        console.log(report);
    } finally {
        await browser.close();
    }
}

main().catch(error => { console.error(error); process.exitCode = 1; });
