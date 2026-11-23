import {patch} from "@web/core/utils/patch";
import {SheetSettings} from "@nodo_draw/sheet_settings";
import {SheetUsage} from "@nodo_draw/sheet_usage";
import {Workbench} from "@nodo_draw/workbench";
import {unitPrice, useLiveSheetPrices} from "./live_sheet_prices";

class CostedSheetUsage extends SheetUsage {
    static template = "nodo_draw_cost.SheetUsage";
    setup() {
        super.setup();
        this.unitPrice = unitPrice;
        this.prices = useLiveSheetPrices(() => this.usage() && this.jobId,
            (orm, jobId) => orm.call("nodo.draw.design", "current_sheet_costs", [[this.props.designId], jobId]));
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
