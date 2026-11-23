import {Component, signal, useProps} from "@odoo/owl";
import {useService} from "@web/core/utils/hooks";
import {patch} from "@web/core/utils/patch";
import {Workbench} from "@nodo_draw/workbench";
import {unitPrice, useLiveSheetPrices} from "./live_sheet_prices";

const MODEL = "nodo.draw.design";

class AuxiliaryCost extends Component {
    static template = "nodo_draw_cost.AuxiliaryCost";
    props = useProps({designId: Number, spec: Object, edit: Number, dirty: Boolean, visible: Boolean});
    draft = signal(null);
    choice = signal("");
    lockEditor = signal(false);
    saving = signal(false);
    refresh = signal(0);
    message = signal("");
    saveError = signal("");
    unitPrice = unitPrice;

    setup() {
        this.orm = useService("orm");
        this.costs = useLiveSheetPrices(() => {
            if (!this.props.visible) return null;
            this.refresh();
            return {designId: this.props.designId, spec: this.props.spec, edit: this.props.edit,
                draft: this.draft()?.values ?? null};
        }, (orm, key) => orm.call(MODEL, "preview_auxiliary_costs", [[key.designId], key.spec, key.draft]),
        "nodo.cost/auxiliary_prices_changed");
    }

    choices() {
        return this.draft()?.values ?? this.costs().value?.saved;
    }

    remaining() {
        const selected = new Set(this.choices()?.items.map(row => row.id));
        return (this.costs().value?.catalog ?? []).filter(row => !selected.has(row.id));
    }

    change(mutator) {
        const current = this.draft();
        const latest = this.costs().value;
        if (this.saving() || !latest) return;
        this.message.set("");
        this.saveError.set("");
        this.draft.set({revision: current?.revision ?? latest.revision, values: mutator(this.choices())});
    }

    add() {
        const id = Number(this.choice());
        if (!this.remaining().some(row => row.id === id)) return;
        this.choice.set("");
        this.change(values => ({...values, items: [...values.items, {id, quantity: 1}]}));
    }

    setQuantity(row, input) {
        const quantity = input.valueAsNumber;
        if (!input.checkValidity() || !Number.isFinite(quantity)) {
            this.saveError.set(row.unit === "metre" ? "长度须大于零，最多三位小数。" : "每台数量须为正整数。");
            input.value = row.quantity;
            return;
        }
        this.change(values => ({...values, items: values.items.map(item => item.id === row.id ? {...item, quantity} : item)}));
    }

    remove(id) {
        this.change(values => ({...values, items: values.items.filter(item => item.id !== id)}));
    }

    setLock(scheme) {
        this.change(values => ({...values, lock: scheme ? {scheme, reason: "", confirm: true} : null}));
    }

    confirmLock(reason) {
        this.change(values => ({...values, lock: {...values.lock, reason, confirm: true}}));
    }

    discard() {
        this.draft.set(null);
        this.choice.set("");
        this.lockEditor.set(false);
        this.message.set("");
        this.saveError.set("");
        this.refresh.set(this.refresh() + 1);
    }

    async save() {
        const draft = this.draft();
        if (!draft || this.props.dirty || this.saving() || !this.costs().value) return;
        this.saving.set(true);
        this.saveError.set("");
        try {
            await this.orm.call(MODEL, "save_auxiliary_choices", [
                [this.props.designId], this.props.edit, draft.revision, draft.values,
            ]);
            this.draft.set(null);
            this.lockEditor.set(false);
            this.message.set("辅材选配已保存");
        } catch (error) {
            this.saveError.set(error.data?.message || error.message);
        } finally {
            this.saving.set(false);
        }
    }
}

patch(Workbench, {components: {...Workbench.components, AuxiliaryCost}});
patch(Workbench.prototype, {
    setup() {
        super.setup(...arguments);
        this.tabs = [...this.tabs, ["auxiliary", "辅材"]];
    },
    currentPanelWidth() {
        return this.tab() === "auxiliary" ? this.usageWidth() : super.currentPanelWidth();
    },
    setPanelWidth(value) {
        if (this.tab() === "auxiliary") {
            this.usageWidth.set(Math.max(390, Math.min(660, value)));
        } else {
            super.setPanelWidth(value);
        }
    },
    auxiliarySpec(doc, form) {
        const selected = form.materials.parts?.wrap ?? form.materials.body;
        return {kind: form.kind, width: form.width, height: form.height, depth: form.depth,
            material: selected?.category ?? doc.sheet_catalog.materials.groups.body};
    },
});
