import {Component, onMounted, signal, t, useOnChange, useProps} from "@odoo/owl";
import {useOwnedDialogs, useService} from "@web/core/utils/hooks";
import {patch} from "@web/core/utils/patch";
import {Workbench} from "@nodo_draw/workbench";
import {unitPrice, useLiveSheetPrices} from "./live_sheet_prices";
import {AuxiliaryPicker} from "./auxiliary_picker";
import {AuxiliaryReview, modelStatusLabel} from "./auxiliary_review";

const MODEL = "nodo.draw.design";

class AuxiliaryCost extends Component {
    static template = "nodo_draw_cost.AuxiliaryCost";
    static components = {AuxiliaryReview};
    props = useProps({designId: t.number(), spec: t.string(), edit: t.number(), dirty: t.boolean(),
        active: t.boolean(), visible: t.boolean(), onCosts: t.function()});
    draft = signal(null);
    lockEditor = signal(false);
    lockExpanded = signal(true);
    onlyReview = signal(false);
    reviewKey = signal(null);
    ledger = signal.ref();
    saving = signal(false);
    refresh = signal(0);
    message = signal("");
    saveError = signal("");
    unitPrice = unitPrice;
    modelStatusLabel = modelStatusLabel;

    setup() {
        this.orm = useService("orm");
        this.addDialog = useOwnedDialogs();
        this.costs = useLiveSheetPrices(() => {
            if (!this.props.active) return null;
            this.refresh();
            return {designId: this.props.designId, spec: this.props.spec, edit: this.props.edit,
                draft: this.draft()?.values ?? null};
        }, (orm, key) => orm.call(MODEL, "preview_auxiliary_costs", [[key.designId], JSON.parse(key.spec), key.draft]),
        "nodo.cost/auxiliary_prices_changed", true);
        const mounted = signal(false);
        onMounted(() => mounted.set(true));
        useOnChange(() => mounted() ? [this.props.designId, this.props.edit, this.props.spec,
            this.currentData(), this.readError(), Boolean(this.draft()) || this.saving()] : [],
        (...args) => { if (args.length) this.props.onCosts(...args); });
    }

    sameSpec(key) {
        return key?.designId === this.props.designId && key.edit === this.props.edit && key.spec === this.props.spec;
    }

    rowsData() {
        const {key, value} = this.costs();
        return this.sameSpec(key) && value?.spec_edit === this.props.edit ? value : null;
    }

    currentData() {
        const {key, loading, error} = this.costs();
        return !loading && !error && key?.draft === (this.draft()?.values ?? null) ? this.rowsData() : null;
    }

    readError() {
        const {key, failedKey, value, error} = this.costs();
        if (this.sameSpec(failedKey) && failedKey.draft === (this.draft()?.values ?? null)) return error;
        if (this.sameSpec(key) && value?.spec_edit !== this.props.edit) return "柜体规格版本已更新，请重新打开后核对。";
        return "";
    }

    choices() {
        return this.draft()?.values ?? this.rowsData()?.saved;
    }

    remaining() {
        const selected = new Set(this.choices()?.items.map(row => row.id));
        return (this.rowsData()?.catalog ?? []).filter(row => !selected.has(row.id));
    }

    rowKey(row) { return row.source + ":" + (row.id || row.code); }

    visibleRows(rows) {
        return this.onlyReview() ? rows.filter(row => row.issue) : rows;
    }

    lockOpen() { return this.lockExpanded() || this.onlyReview(); }

    reviewQueue(data) {
        const standard = this.visibleRows(data.standard);
        const ordinary = standard.filter(row => !row.lock_item);
        const locks = this.lockOpen() ? standard.filter(row => row.lock_item) : [];
        return [...ordinary, ...locks, ...this.visibleRows(data.optional)];
    }

    reviewIndex(rows) {
        return rows.findIndex(row => this.rowKey(row) === this.reviewKey());
    }

    inspect(row) {
        this.reviewKey.set(this.rowKey(row));
    }

    moveReview(step) {
        const rows = this.reviewQueue(this.rowsData());
        const row = rows[this.reviewIndex(rows) + step];
        if (!row) return;
        this.inspect(row);
        const target = Array.from(this.ledger()?.querySelectorAll("[data-aux-review]") || [])
            .find(item => item.dataset.auxReview === this.reviewKey());
        target?.scrollIntoView({block:"nearest"});
    }

    setReviewFilter(enabled) {
        this.onlyReview.set(enabled);
        if (!enabled) return;
        const rows = this.reviewQueue(this.rowsData());
        const first = rows[this.reviewIndex(rows)] || rows[0];
        this.reviewKey.set(first ? this.rowKey(first) : null);
    }

    rowBasis(row) {
        if (row.condition) return row.condition;
        if (row.source === "handoff") return "交接清单";
        if (row.source === "manual") {
            return this.rowsData().standard.some(item => item.code === row.code) ? "增购" : "手工自选";
        }
        return "固定标配";
    }

    change(mutator) {
        const current = this.draft();
        const latest = this.rowsData();
        if (this.saving() || !latest) return;
        this.message.set("");
        this.saveError.set("");
        this.draft.set({revision: current?.revision ?? latest.revision, values: mutator(this.choices())});
    }

    openPicker() {
        if (!this.currentData() || this.saving() || this.choices().items.length >= 100) return;
        this.addDialog(AuxiliaryPicker, {
            catalog: () => this.remaining(),
            pricing: () => this.currentData(),
            add: (id, quantity) => {
                if (!this.currentData() || !this.remaining().some(row => row.id === id) ||
                    this.choices().items.length >= 100) return false;
                this.change(values => ({...values, items: [...values.items, {id, quantity}]}));
                return true;
            },
        });
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
        this.lockEditor.set(false);
        this.message.set("");
        this.saveError.set("");
        this.refresh.set(this.refresh() + 1);
    }

    async save() {
        const draft = this.draft();
        if (!draft || this.props.dirty || this.saving() || !this.rowsData()) return;
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
        this.tabs = this.tabs.filter(([id]) => id !== "parts");
        this.quotePage = signal("parts");
        this.quoteSheetCosts = signal(null);
        this.quoteAuxiliaryCosts = signal(null);
        this.reportQuoteSheetCosts = (designId, meshId, edit, prices, error) => {
            this.quoteSheetCosts.set({designId, meshId, edit, prices, error});
        };
        this.reportQuoteAuxiliaryCosts = (designId, edit, spec, value, error, pending) => {
            this.quoteAuxiliaryCosts.set({designId, edit, spec, value, error, pending});
        };
    },
    openInitialTab(tab) {
        if (tab === "auxiliary") this.openQuote("auxiliary");
        else super.openInitialTab(tab);
    },
    quoteOpen() { return !this.showFiles() && this.tab() === "parts"; },
    auxiliaryOpen() { return this.quoteOpen() && this.quotePage() === "auxiliary"; },
    openQuote(page = this.quotePage()) {
        if (!this.quoteOpen()) {
            this.quoteReturnTab = this.tabs.some(([id]) => id === this.tab()) ? this.tab() : "cabinet";
            this.selectTab("parts");
        }
        this.quotePage.set(page);
    },
    openDesign() {
        if (this.tab() === "parts") this.selectTab(this.quoteReturnTab ?? "cabinet");
        super.openDesign(...arguments);
    },
    showThree() {
        if (this.auxiliaryOpen()) this.openDesign();
        super.showThree(...arguments);
    },
    viewportPaused() {
        return super.viewportPaused() || this.auxiliaryOpen();
    },
    hasUnsavedChanges() {
        const auxiliary = this.quoteAuxiliaryCosts();
        return super.hasUnsavedChanges() || (auxiliary?.designId === this.doc()?.id && auxiliary?.pending);
    },
    auxiliarySpec(doc, form) {
        const selected = form.materials.parts?.wrap ?? form.materials.body;
        return JSON.stringify({kind: form.kind, width: form.width, height: form.height, depth: form.depth,
            material: selected?.category ?? doc.sheet_catalog.materials.groups.body});
    },
    quoteTotals(doc, form) {
        const sheet = this.quoteSheetCosts();
        const auxiliary = this.quoteAuxiliaryCosts();
        const meshId = this.sheetMeshId();
        const dirty = this.dirty() || this.busy();
        const board = sheet?.designId === doc.id && sheet.meshId === meshId && sheet.edit === doc.edit_number
            ? sheet : null;
        const supplies = auxiliary?.designId === doc.id && auxiliary.edit === this.localEdit
            && auxiliary.spec === this.auxiliarySpec(doc, form) ? auxiliary : null;
        const boardsTotal = dirty || !doc.sheet_usage_enabled ? null : board?.prices.value?.total ?? null;
        const suppliesTotal = supplies?.value?.total ?? null;
        const sum = boardsTotal !== null && suppliesTotal !== null ? boardsTotal + suppliesTotal : null;
        return {
            boards: boardsTotal,
            boardNote: !doc.sheet_usage_enabled ? "待匹配展开图" : dirty ? "待重算" :
                board?.prices.value?.missing ? "待补价" : board?.error || board?.prices.error ? "读取失败" :
                boardsTotal === null ? "核算中" : (board?.prices.value.trial ? "含测试价" : ""),
            supplies: suppliesTotal,
            auxiliaryNote: supplies?.error ? "读取失败" : supplies?.value && suppliesTotal === null ? "待核对" :
                suppliesTotal === null ? "核算中" : (supplies?.value.reference_count ? "含参考价" : ""),
            sum,
        };
    },
});
