import {Component, onMounted, signal, t, useProps} from "@odoo/owl";
import {Dialog} from "@web/core/dialog/dialog";
import {unitPrice} from "./live_sheet_prices";

export class AuxiliaryPicker extends Component {
    static template = "nodo_draw_cost.AuxiliaryPicker";
    static components = {Dialog};
    props = useProps({catalog: t.function(), add: t.function(), close: t.function()});
    query = signal("");
    selectedId = signal(null);
    quantity = signal(1);
    validQuantity = signal(true);
    issue = signal("");
    search = signal.ref();
    unitPrice = unitPrice;

    setup() {
        onMounted(() => this.search()?.focus());
    }

    matches() {
        const terms = this.query().trim().toLowerCase().split(/\s+/).filter(Boolean);
        return this.props.catalog().filter(item => {
            const label = (item.name + " " + item.code).toLowerCase();
            return terms.every(term => label.includes(term));
        });
    }

    selected() {
        return this.props.catalog().find(item => item.id === this.selectedId());
    }

    select(id) {
        if (id === this.selectedId()) return;
        this.selectedId.set(id);
        this.quantity.set(1);
        this.validQuantity.set(true);
        this.issue.set("");
    }

    changeQuantity(input) {
        this.quantity.set(input.value);
        this.validQuantity.set(input.checkValidity());
    }

    amount(item) {
        const value = item.price * Number(this.quantity());
        return (Math.round((value + Number.EPSILON * value) * 100) / 100).toFixed(2);
    }

    add() {
        const item = this.selected();
        if (!item || !this.validQuantity()) return;
        if (this.props.add(item.id, Number(this.quantity()))) {
            this.props.close();
        } else {
            this.issue.set("当前辅材已加入或不再适用，请重新选料。");
        }
    }
}
