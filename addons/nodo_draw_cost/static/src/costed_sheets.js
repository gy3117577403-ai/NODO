import {onMounted, signal, useOnChange} from "@odoo/owl";
import {useService} from "@web/core/utils/hooks";
import {patch} from "@web/core/utils/patch";
import {SheetSettings} from "@nodo_draw/sheet_settings";
import {SheetUsage} from "@nodo_draw/sheet_usage";
import {Workbench} from "@nodo_draw/workbench";
import {unitPrice, useLiveSheetPrices} from "./live_sheet_prices";
import {SheetCostHistory} from "./cost_history";

class CostedSheetUsage extends SheetUsage {
    static template = "nodo_draw_cost.SheetUsage";
    saving = signal(false);
    saveError = signal("");
    refreshPrice = signal(0);
    setup() {
        super.setup();
        this.unitPrice = unitPrice;
        this.dialog = useService("dialog");
        this.prices = useLiveSheetPrices(() => {
            this.refreshPrice();
            return this.usage() && this.jobId;
        },
            (orm, jobId) => orm.call("nodo.draw.design", "current_sheet_costs", [[this.props.designId], jobId]));
        const mounted = signal(false);
        onMounted(() => mounted.set(true));
        useOnChange(() => mounted() ? [this.props.designId, this.props.meshId, this.props.edit, this.prices(), this.error()] : [],
            (...args) => { if (args.length) this.props.onPrices?.(...args); });
    }
    async saveVersion() {
        const prices = this.prices().value;
        if (this.saving() || prices?.total == null) return;
        this.saving.set(true);
        this.saveError.set("");
        try {
            const designId = this.props.designId;
            const id = await this.orm.call("nodo.draw.design", "save_sheet_cost_version",
                [[designId], this.props.edit, this.jobId, prices.fingerprint]);
            this.dialog.add(SheetCostHistory, {designId, initialId:id});
        } catch (error) {
            this.saveError.set(error.data?.message || error.message);
            this.refreshPrice.set(this.refreshPrice() + 1);
        } finally {
            this.saving.set(false);
        }
    }
}

class CostedSheetSettings extends SheetSettings {
    static template = "nodo_draw_cost.SheetSettings";
    setup() {
        super.setup();
        this.unitPrice = unitPrice;
        this.rates = useLiveSheetPrices(() => this.props.designId,
            (orm, id) => orm.call("nodo.draw.design", "sheet_price_choices", [[id]]));
    }

    rateFor(row) {
        const normalized = value => (value || "").trim().toLowerCase();
        return this.rates().value?.find(p => p.category === row.material.category && p.thickness_mm === row.thickness &&
            normalized(p.grade) === normalized(row.material.grade) && normalized(p.supply_condition) === normalized(row.material.condition));
    }

    chooseStock(row, select) {
        const price = this.rates().value?.find(p => p.id === Number(select.value));
        select.value = "";
        if (!price) return;
        const material = {...row.material, category:price.category, grade:price.grade || "", condition:price.supply_condition || ""};
        this.props.change({materials:this.materialValues(row.key, material), thickness:this.thicknessValues(row.key, price.thickness_mm)});
    }
}

patch(Workbench, {
    usagePanelWidth: 626,
    components: {...Workbench.components, SheetUsage:CostedSheetUsage, SheetSettings:CostedSheetSettings},
});

patch(Workbench.prototype, {
    openSheetCostHistory() {
        this.env.services.dialog.add(SheetCostHistory, {designId:this.doc().id});
    },
});
