// Run against a logged-in engineering session on the local development database.
const assert = require("node:assert/strict");
const crypto = require("node:crypto");
const fs = require("node:fs");
const path = require("node:path");
const {chromium} = require("playwright");

const phase = process.argv[2];
assert(["before", "after"].includes(phase), "请选择 before 或 after");
const destination = path.resolve(process.argv[3] || ".nodo-draw/viewport-check");
const viewport = {width: 1173, height: 871};
const url = "http://127.0.0.1:8079/odoo/technical-workbench";
const canvas = ".nd-viewport canvas:visible";
const sha = bytes => crypto.createHash("sha256").update(bytes).digest("hex");

function installMeter() {
    const raf = window.requestAnimationFrame.bind(window);
    const meter = window.viewportMeter = {raf, frames: [], count: 0, recording: false};
    function wrapDraw(proto, name) {
        const original = proto[name];
        proto[name] = function (...args) {
            meter.canvas = this.canvas;
            meter.count++;
            return original.apply(this, args);
        };
    }
    wrapDraw(CanvasRenderingContext2D.prototype, "putImageData");
    wrapDraw(WebGL2RenderingContext.prototype, "drawElements");
    window.requestAnimationFrame = callback => raf(time => {
        const count = meter.count;
        const start = performance.now();
        try {
            return callback(time);
        } finally {
            if (meter.count > count && meter.canvas.closest(".nd-viewport")) {
                meter.last = performance.now();
                if (meter.recording) meter.frames.push([start, meter.last - start]);
            }
        }
    });
}

function distribution(values) {
    const sorted = [...values].sort((a, b) => a - b);
    const percentile = p => +sorted[Math.floor((sorted.length - 1) * p)].toFixed(2);
    return {samples: sorted.length, median: percentile(.50), p95: percentile(.95)};
}

async function measure(page, kind) {
    const target = page.locator(canvas);
    const box = await target.boundingBox();
    const cx = Math.round(box.x + box.width * .52);
    const cy = Math.round(box.y + box.height * .55);
    await page.mouse.move(cx, cy);
    if (kind === "rotate") await page.mouse.down();
    const frames = await target.evaluate(async (element, {cx, cy, kind}) => {
        const meter = window.viewportMeter;
        meter.frames = [];
        meter.recording = true;
        for (let i = 0; i < 48; i++) {
            await new Promise(meter.raf);
            const options = {bubbles: true, cancelable: true, clientX: cx, clientY: cy};
            if (kind === "rotate") {
                element.dispatchEvent(new PointerEvent("pointermove", {...options,
                    pointerType: "mouse", pointerId: 1, isPrimary: true, buttons: 1,
                    clientX: cx + 35 * Math.sin(i * .12), clientY: cy + 13 * Math.sin(i * .11)}));
            } else {
                element.dispatchEvent(new WheelEvent("wheel", {...options, deltaY: i < 24 ? -5 : 5}));
            }
        }
        await new Promise(meter.raf);
        meter.recording = false;
        return meter.frames.slice(3);
    }, {cx, cy, kind});
    if (kind === "rotate") {
        await page.mouse.move(cx + Math.round(35 * Math.sin(47 * .12)), cy + Math.round(13 * Math.sin(47 * .11)));
        await page.mouse.up();
    }
    assert(frames.length >= 35, kind + " 实际绘制帧数不足 " + frames.length);
    return {cpuMs: distribution(frames.map(f => f[1])),
        intervalMs: distribution(frames.slice(1).map((f, i) => f[0] - frames[i][0]))};
}

async function main() {
    fs.mkdirSync(destination, {recursive: true});
    const browser = await chromium.launch({channel: "chrome"});
    try {
        const context = await browser.newContext({storageState: ".nodo-draw/dev-session.local.json", viewport, deviceScaleFactor: 1});
        await context.addInitScript(installMeter);
        const session = await browser.newBrowserCDPSession();
        const {gpu} = await session.send("SystemInfo.getInfo");
        const data = {phase, viewport, browser: browser.version(), renderer: gpu.auxAttributes.glRenderer, models: []};
        const page = await context.newPage();
        const errors = [];
        page.on("pageerror", error => errors.push(error.message));
        const meshResponse = response => /\/nodo\/draw\/file\/\d+\/mesh$/.test(response.url()) && response.ok();
        let responsePromise = page.waitForResponse(meshResponse);
        await page.goto(url);
        for (const [code, title] of [["AE-101", "壁挂控制箱"], ["AE-202", "双门配电箱"]]) {
            if (code === "AE-202") {
                responsePromise = page.waitForResponse(meshResponse);
                await page.getByLabel("选择设计").selectOption({label: code + " · " + title});
            }
            const response = await responsePromise;
            await page.getByLabel("选择设计").locator("option:checked").filter({hasText:title}).waitFor({state:"attached"});
            await page.locator(".nd-overlay").waitFor({state: "detached"});
            await page.waitForFunction(() => window.viewportMeter.last > 0 &&
                performance.now() - window.viewportMeter.last > 200 && !document.querySelector(".ae-error"));
            assert.equal(await page.locator(canvas).count(), 1);
            await page.screenshot({path: path.join(destination, code + "-" + phase + ".png")});
            const bytes = await (await context.request.get(response.url())).body();
            const model = JSON.parse(bytes);
            const record = {code, mesh: new URL(response.url()).pathname, sha256: sha(bytes),
                parts: model.parts.length, triangles: model.parts.reduce((n, p) => n + p.triangles.length, 0)};
            record.rotate = await measure(page, "rotate");
            await page.getByRole("button", {name: "复位视角"}).click();
            await page.waitForTimeout(500);
            record.zoom = await measure(page, "zoom");
            console.log(JSON.stringify(record));
            data.models.push(record);
        }
        assert.deepEqual(errors, []);
        if (phase === "after") {
            const earlier = JSON.parse(fs.readFileSync(path.join(destination, "before.json")));
            assert.deepEqual(data.models.map(r => r.sha256), earlier.models.map(r => r.sha256), "前后工程模型不一致");
        }
        fs.writeFileSync(path.join(destination, phase + ".json"), JSON.stringify(data, null, 2) + "\n");
    } finally {
        await browser.close();
    }
}
main().catch(error => {console.error(error); process.exitCode = 1;});
