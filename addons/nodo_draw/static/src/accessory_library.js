import {Component, onMounted, onWillStart, onWillUnmount, signal, t, useEffect, useProps} from "@odoo/owl";
import {loadBundle} from "@web/core/assets";
import {registry} from "@web/core/registry";
import {useService} from "@web/core/utils/hooks";
import {standardActionServiceProps} from "@web/webclient/actions/action_plugin";

const labels = {
    available: "可用于装配",
    selectable: "可选用",
    face: "需调整板面",
    cabinet: "柜型不符",
    pending: "待工程核对",
    version: "版本未纳入",
};
const blocked = {
    cabinet: labels.cabinet,
    pending: "待工程核对，暂不可安装",
    version: "此版本未列入当前设计的附件库快照",
};
const faces = {door:"门板 / 左门", door_right:"右门板", top:"顶板", bottom:"底板", back:"围板背面", left:"左侧板", right:"右侧板", mount:"安装板"};

function accessoryStatus(item, picker) {
    if (item.state === "pending") return "pending";
    if (!picker) return "available";
    if (!item.kinds.includes(picker.kind)) return "cabinet";
    if (picker.versions[item.code] !== item.version) return "version";
    return picker.originalFace && !item.faces.includes(picker.originalFace) ? "face" : "selectable";
}

export function accessoryRestriction(item, picker) {
    return blocked[accessoryStatus(item,picker)] || "";
}

export function accessoryFaceNames(item) {
    return item.faces.map(face => faces[face]).filter(Boolean).join("、") || "待核对";
}

export class AccessoryMesh extends Component {
    static template = "nodo_draw.AccessoryMesh";
    props = useProps({src:t.string(), name:t.string()});
    host = signal.ref();
    loading = signal(true);
    error = signal("");

    setup() {
        this.reset = 0;
        onMounted(() => this.load());
        onWillUnmount(() => {
            this.request?.abort();
            this.view?.dispose();
        });
    }

    async load() {
        this.request?.abort();
        this.view?.dispose();
        this.view = null;
        this.request = new AbortController();
        this.error.set("");
        this.loading.set(true);
        const {signal} = this.request;
        try {
            await loadBundle("nodo_draw.assets_ae");
            const response = await fetch(this.props.src, {signal});
            if (!response.ok) throw Error();
            const mesh = await response.json();
            if (signal.aborted) return;
            this.mesh = mesh;
            this.view = window.nodoDrawAE0573.mount(this.host());
            this.updateView();
        } catch {
            if (!signal.aborted) this.error.set("附件模型暂时无法读取");
        } finally {
            if (!signal.aborted) this.loading.set(false);
        }
    }

    updateView() {
        this.view?.update(this.mesh, false, false, this.reset, {catalogPreview: true});
    }

    resetView() {
        this.reset++;
        this.updateView();
    }
}

export class AccessoryCatalog extends Component {
    static template = "nodo_draw.AccessoryCatalog";
    static components = {AccessoryMesh};
    props = useProps({picker:t.object().optional(), selectModel:t.function().optional(), selectFace:t.function().optional(),
        apply:t.function().optional(), cancel:t.function().optional(), initialModelId:t.number().optional()});
    items = signal([]);
    filter = signal("");
    category = signal("");
    state = signal("");
    selectedId = signal(null);
    view = signal("list");
    galleryDetail = signal(false);
    galleryList = signal.ref();
    search = signal.ref();
    rulesOpen = signal(false);
    error = signal("");

    setup() {
        const orm = useService("orm");
        this.galleryScroll = 0;
        onWillStart(async () => {
            try {
                const rows = await orm.call("nodo.draw.accessory", "list_accessory_models", []);
                const initialModelId = this.props.initialModelId;
                const picker = this.props.picker;
                const current = initialModelId ? rows.find(row => row.id === initialModelId) :
                    picker && rows.find(row => row.code === picker.code && row.version === picker.versions[row.code]);
                if (initialModelId && !current) {
                    this.error.set("当前无法查看所关联的型号版本。");
                    return;
                }
                this.items.set(rows);
                const preferred = current || this.filtered().find(row => !accessoryRestriction(row,picker));
                this.selectedId.set(preferred?.id ?? null);
                this.rulesOpen.set(Boolean(initialModelId));
            } catch (error) {
                this.error.set(error.data?.message || "附件库暂时无法读取");
            }
        });
        onMounted(() => {
            if (!this.props.picker) return;
            const item = this.items().find(row => row.id === this.selectedId());
            if (item) this.props.selectModel(item);
            this.search()?.focus({preventScroll:true});
        });
        useEffect(() => {
            const list = this.galleryList();
            if (list) list.scrollTop = this.galleryScroll;
        });
    }

    categories() { return [...new Set(this.items().map(item=>item.category))]; }
    states() {
        return this.props.picker ? ["selectable", "face", "cabinet", "pending", "version"] : ["available", "pending"];
    }
    filtered() {
        const words = this.filter().trim().toLowerCase().split(/\s+/).filter(Boolean);
        const rows = this.items().filter(item => (!this.category() || item.category===this.category()) &&
            (!this.state() || this.status(item)===this.state()) &&
            words.every(word => [item.name,item.code,...item.aliases].some(text=>text.toLowerCase().includes(word))));
        const picker = this.props.picker;
        if (!picker) return rows;
        return rows.sort((a,b) => this.priority(a)-this.priority(b) || Number(b.code===picker.code)-Number(a.code===picker.code));
    }
    selected(rows) {
        if (this.props.picker) return this.props.picker.item;
        return rows.find(item=>item.id===this.selectedId()) ?? rows[0];
    }

    select(item) {
        if (this.props.picker) this.props.selectModel(item);
        else this.selectedId.set(item.id);
    }

    setView(view) {
        if (this.galleryList()) this.galleryScroll = this.galleryList().scrollTop;
        this.view.set(view);
        this.galleryDetail.set(false);
    }

    inspectGallery(item) {
        this.galleryScroll = this.galleryList()?.scrollTop ?? 0;
        this.select(item);
        this.galleryDetail.set(true);
    }

    version(item) { return `V${String(item.version).padStart(2,"0")}`; }
    stateName(status) { return labels[status]; }
    faceNames = accessoryFaceNames;
    cabinetKinds(item) {
        return item.state === "pending" ? "待核对" : item.kinds.map(kind=>kind==="double" ? "双开门" : "单开门").join("、");
    }

    status(item) { return accessoryStatus(item,this.props.picker); }

    priority(item) {
        return accessoryRestriction(item,this.props.picker) ? 2 : Number(this.status(item)==="face");
    }

    selectionNote(item) {
        const picker = this.props.picker;
        if (!item) return "";
        return picker.notice || accessoryRestriction(item,picker) || (!picker.face ? "请选择安装面" : "");
    }
}

class AccessoryLibrary extends Component {
    static template = "nodo_draw.AccessoryLibrary";
    static components = {AccessoryCatalog};
    props = useProps({...standardActionServiceProps});
}

registry.category("actions").add("nodo_draw.accessory_library", AccessoryLibrary);
