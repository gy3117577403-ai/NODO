import {Component, onMounted, signal, t, useProps} from "@odoo/owl";
import {Dialog} from "@web/core/dialog/dialog";
import {unitPrice} from "./live_sheet_prices";
import {AuxiliaryModelPreview, modelStatusLabel} from "./auxiliary_review";

// Four price decimals and three quantity decimals produce amounts in 10^-7 yuan.
function scaledInteger(value, decimalPlaces) {
    const [whole, fraction = ""] = value.split(".");
    return BigInt(whole + fraction.padEnd(decimalPlaces, "0").slice(0, decimalPlaces));
}

function moneyText(raw) {
    const cents = (raw + 50000n) / 100000n;
    return (cents / 100n).toString() + "." + (cents % 100n).toString().padStart(2, "0");
}

export class AuxiliaryPicker extends Component {
    static template = "nodo_draw_cost.AuxiliaryPicker";
    static components = {Dialog, AuxiliaryModelPreview};
    props = useProps({catalog: t.function(), pricing:t.function(), add: t.function(), close: t.function()});
    query = signal("");
    selectedId = signal(null);
    quantity = signal(1);
    modelOpen = signal(false);
    validQuantity = signal(true);
    issue = signal("");
    search = signal.ref();
    unitPrice = unitPrice;
    modelStatusLabel = modelStatusLabel;

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
        this.modelOpen.set(false);
        this.issue.set("");
    }

    changeQuantity(input) {
        this.quantity.set(input.value);
        this.validQuantity.set(input.checkValidity());
    }

    addition(item) {
        const pricing = this.props.pricing();
        if (!pricing || !this.validQuantity()) return null;
        const quantity = scaledInteger(Number(this.quantity()).toFixed(3), 3);
        const price = item.price === null ? 0n : scaledInteger(item.price.toFixed(4), 4);
        const amount = price * quantity;
        const subtotal = scaledInteger(pricing.exact_subtotal, 7);
        return {
            amount:item.price === null ? null : moneyText(amount),
            after:moneyText(subtotal + amount),
            incomplete:pricing.total === null || item.price === null,
        };
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
