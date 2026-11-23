import {Component, onWillStart, signal, types as t, useProps} from "@odoo/owl";
import {Dialog} from "@web/core/dialog/dialog";
import {deserializeDateTime, formatDateTime} from "@web/core/l10n/dates";
import {useService} from "@web/core/utils/hooks";
import {unitPrice} from "./live_sheet_prices";

export class SheetCostHistory extends Component {
    static template = "nodo_draw_cost.SheetCostHistory";
    static components = {Dialog};
    props = useProps({designId: t.number(), initialId: t.number().optional(0), close: t.function()});
    versions = signal([]);
    selected = signal(0);
    detail = signal(null);
    error = signal("");
    unitPrice = unitPrice;

    setup() {
        this.orm = useService("orm");
        onWillStart(() => this.load());
    }
    async load() {
        this.error.set("");
        try {
            const versions = await this.orm.call("nodo.draw.design", "sheet_cost_versions", [[this.props.designId]]);
            this.versions.set(versions);
            if (versions.length) await this.select(this.selected() || this.props.initialId || versions[0].id);
        } catch (error) {
            this.error.set(error.data?.message || error.message);
        }
    }
    async select(value) {
        const id = Number(value);
        this.selected.set(id);
        this.error.set("");
        this.detail.set(null);
        try {
            const detail = await this.orm.call("nodo.draw.design", "read_sheet_cost_version", [[this.props.designId], id]);
            if (this.selected() === id) this.detail.set(detail);
        } catch (error) {
            if (this.selected() === id) this.error.set(error.data?.message || error.message);
        }
    }
    date(value) {
        return formatDateTime(deserializeDateTime(value));
    }
    signed(value, places) {
        return (value > 0 ? "+" : "") + value.toFixed(places);
    }
    version(number) {
        return "V" + String(number).padStart(2, "0");
    }
}
