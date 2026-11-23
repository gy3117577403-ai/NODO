import {Component, onMounted, onWillUnmount, signal, t, untrack, useEffect, useProps} from "@odoo/owl";
import {useService} from "@web/core/utils/hooks";
import {DrawingViewport, fitView} from "./archive_preview";

const MODEL = "nodo.draw.design";

export class SheetUsage extends Component {
    static template = "nodo_draw.SheetUsage";
    static components = {DrawingViewport};
    props = useProps({designId: t.number(), edit: t.number(), meshId: t.number(), selected: t.array(t.string()), select: t.function(),
        onPrices: t.function().optional(), visible: t.boolean().optional(true)});
    usage = signal(null);
    error = signal("");
    originalKey = signal("");

    setup() {
        this.orm = useService("orm");
        this.fitView = fitView;
        onMounted(() => this.load());
        onWillUnmount(() => this.request?.abort());
        useEffect(() => {
            const usage = this.usage();
            if (!this.props.visible || !usage || this.initialSelection) return;
            this.initialSelection = true;
            untrack(() => { if (!this.activeRow()) this.selectRow(usage.rows[0]); });
        });
    }
    activeRow() {
        const ids = this.props.selected;
        return this.usage()?.rows.find(row => row.instances.some(part => ids.includes(part.id)));
    }
    selectRow(row) {
        this.originalKey.set("");
        this.props.select(row.instances.map(part => part.id));
    }
    flatUrl(usage, row) {
        if (this.originalKey() !== row.key || !row.area_source?.reference) return this.drawingUrl(row.key);
        const kind = usage.sheet_profile.template === "AE-DOUBLE-02" ? "double" : "single";
        return "/nodo/draw/reference/" + kind + "/" + row.area_source.reference + "/svg";
    }
    drawingUrl(key) {
        return "/nodo/draw/file/" + this.jobId + "/" + key;
    }
    async load() {
        this.request?.abort();
        const request = this.request = new AbortController();
        const args = [[this.props.designId], this.props.edit, this.props.meshId];
        this.error.set("");
        try {
            const id = await this.orm.call(MODEL, "request_sheet_usage", args);
            while (!request.signal.aborted) {
                const job = await this.orm.call(MODEL, "cabinet_preview_status", [args[0], id]);
                if (request.signal.aborted) return;
                if (job.state === "failed") throw Error(job.error || "板料展开计算失败");
                if (job.state === "done") {
                    this.jobId = id;
                    const response = await fetch(this.drawingUrl("usage"), {signal:request.signal});
                    if (!response.ok) throw Error("板料清单读取失败");
                    const usage = await response.json();
                    if (request.signal.aborted) return;
                    this.usage.set(usage);
                    return;
                }
                await new Promise(resolve => setTimeout(resolve, 750));
            }
        } catch (error) {
            if (!request.signal.aborted) this.error.set(error.data?.message || error.message);
        }
    }
}
