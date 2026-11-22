import { proxy } from "@odoo/owl";

export class DrawingVisionSession {
    constructor(assist) {
        this.assist = assist;
        this.record = assist.record;
        this.orm = assist.orm;
        this.revision = 0;
        this.state = proxy({
            review: null, loading: true, saving: false, selecting: false,
            region: null, focus: null, error: "", viewerReady: false, onlyPending: false,
        });
    }

    get active() {
        return ["queued", "processing"].includes(this.state.review?.state);
    }

    get runs() {
        return [...(this.state.review?.runs || [])].reverse();
    }

    get itemCount() {
        return this.runs.reduce((count, run) => count + run.items.length, 0);
    }

    get pendingCount() {
        return this.runs.reduce((count, run) => count + run.items.filter(item => !item.decision).length, 0);
    }

    itemsFor(run) {
        const pending = run.items.filter(item => !item.decision);
        return this.state.onlyPending ? pending : [...pending, ...run.items.filter(item => item.decision)];
    }

    valueLabel(item, value = item.value) {
        return item.unit ? `${value} ${item.unit}` : value;
    }

    decisionLabel(item) {
        if (item.reviewed_unit === "mm") return "已按毫米确认";
        if (item.decision === "apply") return "已采用";
        if (item.decision === "note") return "已记入技术要求";
        return item.target ? "已保留现值" : "未采用";
    }

    get canSend() {
        return this.assist.editable && this.state.review?.configured && this.state.viewerReady &&
            !this.state.loading && !this.active && !this.state.saving && !this.assist.state.orienting
            && !this.assist.state.busy;
    }

    reset() {
        this.revision++;
        Object.assign(this.state, { review: null, loading: true, saving: false, selecting: false,
            region: null, focus: null, error: "", onlyPending: false });
        this.assist.emit();
    }

    async refresh() {
        const revision = ++this.revision;
        try {
            const review = await this.orm.call("nodo.contract.drawing", "get_drawing_vision", [[this.record.resId]]);
            if (revision === this.revision) {
                this.state.review = review;
                this.state.error = "";
            }
        } catch (error) {
            if (revision === this.revision) {
                this.state.error = error.data?.message || "未能读取智能补读状态。";
            }
        } finally {
            if (revision === this.revision) {
                this.state.loading = false;
            }
        }
    }

    chooseRegion() {
        if (!this.canSend) return;
        this.assist.state.tool = null;
        this.assist.state.error = "";
        Object.assign(this.state, { selecting: true, region: null, focus: null, error: "" });
        this.assist.emit();
        this.assist.revealPreview?.();
    }

    select(page, rect, rotation) {
        if (!this.state.selecting || !this.canSend) return;
        Object.assign(this.state, { region: { page, rect, rotation }, selecting: false });
        this.assist.emit();
    }

    cancel() {
        Object.assign(this.state, { selecting: false, region: null, error: "" });
        this.assist.emit();
    }

    async send() {
        if (!this.state.region || !this.canSend) return;
        const region = this.state.region;
        const revision = this.revision;
        const source = this.state.review.source;
        this.state.saving = true;
        this.state.error = "";
        try {
            const crop = await this.renderCrop(region);
            if (revision !== this.revision) return;
            const review = await this.orm.call("nodo.contract.drawing", "queue_drawing_vision",
                [[this.record.resId], source, region.page, region.rotation, region.rect, crop]);
            if (revision === this.revision) {
                this.state.review = review;
                this.cancel();
            }
        } catch (error) {
            if (revision === this.revision) this.state.error = error.data?.message || error.message || "无法提交选区，请重试。";
        } finally {
            if (revision === this.revision) this.state.saving = false;
        }
    }

    current(item) {
        return item.target ? this.record.data[item.target] || null : null;
    }

    canConfirmMillimetres(item) {
        return item.status === "explicit" && !item.unit?.trim() && item.target?.endsWith("_mm") &&
            /^\d{1,6}(?:\.\d{1,3})?$/.test(item.value);
    }

    conflict(item) {
        const current = this.current(item);
        return !item.decision && item.candidate !== null && current !== null && current !== item.candidate;
    }

    hasAlternative(run, item) {
        return !item.decision && item.candidate !== null && run.items.some(other =>
            other.field === item.field && other.candidate !== null && other.candidate !== item.candidate);
    }

    focus(run, item) {
        this.state.focus = { page: run.page, rotation: run.rotation, rect: item.rect, runId: run.id, itemId: item.id };
        this.assist.state.focusToken = null;
        this.assist.revealPreview?.();
        for (const navigate of this.assist.navigators) {
            navigate(run, item);
        }
        this.assist.emit();
    }

    isFocused(run, item) {
        return this.state.focus?.runId === run.id && this.state.focus?.itemId === item.id;
    }

    async confirm(run, item, choice) {
        if (!this.assist.editable || this.state.saving || item.decision) return;
        this.state.saving = true;
        this.state.error = "";
        try {
            await this.assist.saving;
            if (await this.record.isDirty() && !await this.record.save()) {
                throw new Error("请先补齐当前选型中的必填项。");
            }
            this.state.review = await this.orm.call("nodo.contract.drawing", "review_drawing_vision",
                [[this.record.resId], run.id, item.id, choice, this.current(item)]);
            if (choice !== "keep") await this.record.load();
        } catch (error) {
            this.state.error = error.data?.message || error.message || "未能保存本次复核，请重试。";
        } finally {
            this.state.saving = false;
        }
    }
}

export async function cropDrawingPage(document, pdf, region) {
    const page = await pdf.getPage(region.page);
    const rotation = (page.rotate + region.rotation) % 360;
    const unit = page.getViewport({ scale: 1, rotation });
    const viewport = page.getViewport({ scale: Math.min(4.2, 3500 / Math.max(unit.width, unit.height)), rotation });
    const [x, y, width, height] = region.rect;
    const left = Math.floor(x * viewport.width);
    const top = Math.floor(y * viewport.height);
    const crop = document.createElement("canvas");
    crop.width = Math.min(Math.floor(viewport.width) - left, Math.ceil(width * viewport.width));
    crop.height = Math.min(Math.floor(viewport.height) - top, Math.ceil(height * viewport.height));
    if (crop.width < 20 || crop.height < 20) throw new Error("选区太小，请把完整标注框进来。");
    await page.render({
        canvasContext: crop.getContext("2d"), viewport, transform: [1, 0, 0, 1, -left, -top],
        background: "white",
    }).promise;
    return crop.toDataURL("image/png").split(",")[1];
}
