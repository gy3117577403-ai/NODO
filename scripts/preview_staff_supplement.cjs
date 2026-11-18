"use strict";

const assert = require("node:assert/strict");
const fs = require("node:fs");
const path = require("node:path");
const { chromium } = require("playwright");

const preview = path.resolve(__dirname, "../docs/设计预览/员工模块");
const read = (name) => fs.readFileSync(path.resolve(preview, name), "utf8");
const component = "../../../addons/nodo_staff_import/static/src/";

// Render the actual preview with its own local assets in an offline, empty browser context.
function inlineAsset(relativePath, mime) {
  const bytes = fs.readFileSync(path.resolve(preview, relativePath));
  return "data:" + mime + ";base64," + bytes.toString("base64");
}

function offlineMarkup() {
  const css = read("styles.css").replace(/url\("([^"]+\.woff2)"\)/g, (_, font) =>
    'url("' + inlineAsset(font, "font/woff2") + '")'
  );
  return read("index.html")
    .replace('<link rel="stylesheet" href="styles.css">', () => "<style>" + css + "</style>")
    .replace('<link rel="stylesheet" href="' + component + 'supplement.css">', () => "<style>" + read(component + "supplement.css") + "</style>")
    .replace('<script defer src="' + component + 'supplement_form.js"></script>', "")
    .replace('<script defer src="directory.js"></script>', "")
    .replace(/src="([^"]+nodo-wordmark-white\.svg)"/, (_, logo) =>
      'src="' + inlineAsset(logo, "image/svg+xml") + '"'
    );
}

async function checkPreview() {
  const browser = await chromium.launch({ channel: "chrome", headless: true });
  try {
    const context = await browser.newContext({
      viewport: { width: 1280, height: 800 }, locale: "zh-CN", offline: true, deviceScaleFactor: 1.5,
    });
    const page = await context.newPage();
    const errors = [];
    page.on("pageerror", (error) => errors.push(error.message));
    page.on("console", (message) => { if (message.type() === "error") errors.push(message.text()); });
    await page.goto("about:blank#supplement");
    await page.setContent(offlineMarkup());
    await page.addScriptTag({ content: read(component + "supplement_form.js") });
    await page.addScriptTag({ content: read("directory.js") });
    await page.evaluate(() => document.fonts.ready);

    const dialog = page.getByRole("dialog", { name: "补充员工信息" });
    const field = (label) => dialog.getByLabel(label, { exact: true });
    const save = dialog.getByRole("button", { name: "保存", exact: true });
    const progress = dialog.getByRole("status");
    const record = page.locator("#employee-rows tr").filter({ hasText: "柏星禾" });
    const source = dialog.locator(".staff-code");
    const expectFocus = (control) => control.and(page.locator(":focus")).waitFor({ state: "attached", timeout: 3000 });

    assert(await dialog.isVisible());
    await expectFocus(field("人员编号"));
    assert.equal(await field("姓名").inputValue(), "柏星禾");
    assert.equal(await source.textContent(), "ORG-0008");
    assert.deepEqual(await dialog.locator("label").allTextContents(), ["姓名", "人员编号", "部门", "岗位"]);
    assert.equal(await progress.textContent(), "待补 2 项");
    const desktop = await dialog.screenshot({ animations: "disabled", caret: "hide" });
    console.log("PASS 直达预览、缺项聚焦和桌面初始状态");

    await dialog.getByRole("button", { name: "取消" }).click();
    const jobLink = record.getByRole("button", { name: "补充柏星禾的岗位" });
    await jobLink.click();
    await expectFocus(field("岗位"));
    await field("姓名").fill("临时更名");
    await page.keyboard.press("Escape");
    await expectFocus(jobLink);
    assert.equal(await record.locator(".person-open").textContent(), "柏星禾");
    console.log("PASS 岗位直达、取消修改和键盘焦点归还");

    await record.locator(".person-open").click();
    const openEdit = page.getByRole("button", { name: "补充信息", exact: true });
    await openEdit.click();
    await field("姓名").fill("  ");
    await save.click();
    await expectFocus(field("姓名"));
    assert(await dialog.getByText("请填写姓名", { exact: true }).isVisible());
    await field("姓名").fill("柏星禾");
    // The native department picker normally always has a selection.
    await field("部门").evaluate((select) => {
      select.selectedIndex = -1;
      select.dispatchEvent(new Event("input", { bubbles: true }));
    });
    await save.click();
    await expectFocus(field("部门"));
    assert(await dialog.getByText("请选择部门", { exact: true }).isVisible());
    await field("部门").selectOption("quality");
    console.log("PASS 员工详情入口、空姓名和空部门校验");

    await field("岗位").fill("来料质检");
    await field("人员编号").fill("e0001");
    await save.click();
    await expectFocus(field("人员编号"));
    assert.equal(await field("人员编号").getAttribute("aria-invalid"), "true");
    assert(await dialog.getByText("此编号已被使用", { exact: true }).isVisible());
    assert.equal(await field("岗位").inputValue(), "来料质检");
    assert.equal(await progress.textContent(), "资料待核对");
    console.log("PASS 编号查重忽略大小写、字段旁报错和保留已填内容");

    await page.setViewportSize({ width: 390, height: 740 });
    const mobile = await dialog.screenshot({ animations: "disabled", caret: "hide" });
    await page.setViewportSize({ width: 320, height: 380 });
    const fits = await dialog.evaluate((node) => {
      const body = node.querySelector(".staff-body");
      body.scrollTop = body.scrollHeight;
      const footer = node.querySelector("footer").getBoundingClientRect();
      return body.scrollTop > 0 && body.scrollWidth === body.clientWidth &&
        node.scrollWidth === node.clientWidth && footer.bottom <= innerHeight && footer.top >= 0;
    });
    assert(fits);
    console.log("PASS 窄屏表单无横向溢出、短屏可滚动且保存区可见");

    await field("人员编号").fill("E8808");
    await field("岗位").fill("");
    assert.equal(await progress.textContent(), "待补 1 项");
    await save.click();
    const confirmReview = page.getByRole("button", { name: "确认复核" });
    assert(await confirmReview.isDisabled());
    await expectFocus(openEdit);
    await openEdit.click();
    assert.equal(await field("人员编号").inputValue(), "E8808");
    await expectFocus(field("岗位"));
    await field("岗位").fill("来料质检");
    await save.click();
    assert(await confirmReview.isEnabled());
    await confirmReview.click();
    assert.equal(await record.getByText("已复核", { exact: true }).count(), 1);
    console.log("PASS 分次保存、重开回显与独立确认复核");

    assert.deepEqual(errors, []);
    fs.writeFileSync(path.join(preview, "31-员工档案-01-桌面补充信息.png"), desktop);
    fs.writeFileSync(path.join(preview, "31-员工档案-02-窄屏补充信息.png"), mobile);
    console.log("PASS 浏览器错误 0，已生成两张预览图");
  } finally {
    await browser.close();
  }
}

checkPreview().catch((error) => { console.error(error); process.exitCode = 1; });
