import { proxy } from "@odoo/owl";

export class DrawingVisionSession {
    constructor(assist) {
        this.assist = assist;
        this.record = assist.record;
        this.orm = assist.orm;
        this.revision = 0;
        this.state = proxy({
            review: null, loading: true, saving: false, focus: null, error: "", onlyPending: false,
        });
    }

    get active() {
        return ["queued", "processing"].includes(this.state.review?.state);
    }

    get progress() {
        if (this.state.review?.state === "queued") return "识图排队中";
        if (this.state.review?.stage === "reread") return "局部复读中";
        if (this.state.review?.stage === "overview") return "读取其余项";
        return this.active ? "整页识图中" : "";
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
        return this.assist.editable && this.state.review?.configured && this.assist.canView &&
            !this.state.loading && !this.active && !this.state.saving
            && !this.assist.state.busy;
    }

    reset() {
        this.revision++;
        this.refreshing = false;
        Object.assign(this.state, { review: null, loading: true, saving: false,
            focus: null, error: "", onlyPending: false });
        this.assist.emit();
    }

    async refresh() {
        if (this.refreshing) return;
        this.refreshing = true;
        const revision = ++this.revision;
        try {
            const review = await this.orm.call("nodo.contract.drawing", "get_drawing_vision", [[this.record.resId]]);
            if (revision === this.revision) {
                this.state.review = review;
                this.state.error = "";
            }
        } catch (error) {
            if (revision === this.revision) {
                this.state.error = error.data?.message || "未能读取识图状态。";
            }
        } finally {
            if (revision === this.revision) {
                this.refreshing = false;
                this.state.loading = false;
            }
        }
    }

    async send() {
        const preview = this.previewPage?.();
        if (!preview || !this.canSend) return;
        this.assist.cancelTool();
        const revision = this.revision;
        const source = this.state.review.source;
        this.state.saving = true;
        this.state.error = "";
        try {
            const review = await this.orm.call("nodo.contract.drawing", "queue_drawing_vision_page",
                [[this.record.resId], source, preview.page, preview.rotation]);
            if (revision === this.revision) {
                this.state.review = review;
                this.assist.choosePane("results");
            }
        } catch (error) {
            if (revision === this.revision) this.state.error = error.data?.message || error.message || "无法提交识图，请重试。";
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
