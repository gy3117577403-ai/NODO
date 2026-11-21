import {Component, onMounted, onWillStart, onWillUnmount, signal, t, useProps} from "@odoo/owl";
import {loadBundle} from "@web/core/assets";
import {Dialog} from "@web/core/dialog/dialog";
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

class AccessoryMesh extends Component {
    static template = "nodo_draw.AccessoryMesh";
    props = useProps({src:String, name:String});
    host = signal.ref();
    loading = signal(true);
    error = signal("");

    setup() {
        this.request = new AbortController();
        this.reset = 0;
        onMounted(() => this.load());
        onWillUnmount(() => {
            this.request.abort();
            this.view?.dispose();
        });
    }

    async load() {
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

class AccessoryCatalog extends Component {
    static template = "nodo_draw.AccessoryCatalog";
    static components = {AccessoryMesh};
    props = useProps({picker:t.object().optional(), choose:t.function().optional()});
    items = signal([]);
    filter = signal("");
    category = signal("");
    state = signal("");
    selectedId = signal(null);
    rulesOpen = signal(false);
    error = signal("");

    setup() {
        const orm = useService("orm");
        onWillStart(async () => {
            try {
                const rows = await orm.call("nodo.draw.accessory", "list_accessory_models", []);
                this.items.set(rows);
                const preferred = this.filtered().find(row => !this.restriction(row));
                this.selectedId.set(preferred?.id ?? null);
            } catch (error) {
                this.error.set(error.data?.message || "附件库暂时无法读取");
            }
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
    selected(rows) { return rows.find(item=>item.id===this.selectedId()) ?? rows[0]; }
    select(item) { this.selectedId.set(item.id); }
    version(item) { return `V${String(item.version).padStart(2,"0")}`; }
    stateName(status) { return labels[status]; }
    faceNames(item) { return item.faces.map(face=>faces[face]).filter(Boolean).join("、") || "待核对"; }
    cabinetKinds(item) {
        return item.state === "pending" ? "待核对" : item.kinds.map(kind=>kind==="double" ? "双开门" : "单开门").join("、");
    }

    status(item) {
        if (item.state === "pending") return "pending";
        const picker = this.props.picker;
        if (!picker) return "available";
        if (!item.kinds.includes(picker.kind)) return "cabinet";
        if (picker.versions[item.code] !== item.version) return "version";
        return picker.face && !item.faces.includes(picker.face) ? "face" : "selectable";
    }

    priority(item) {
        return this.restriction(item) ? 2 : Number(this.status(item)==="face");
    }

    restriction(item) {
        return blocked[this.status(item)] || "";
    }

    selectionNote(item) {
        if (!item) return "";
        return this.restriction(item) || (this.status(item) === "face" ? "选用后请在装配清单调整安装面" : "");
    }
}

export class AccessoryPicker extends Component {
    static template = "nodo_draw.AccessoryPicker";
    static components = {AccessoryCatalog, Dialog};
    props = useProps({picker:t.object(), choose:t.function(), close:t.function()});
    choose(item) { this.props.choose(item); this.props.close(); }
}

class AccessoryLibrary extends Component {
    static template = "nodo_draw.AccessoryLibrary";
    static components = {AccessoryCatalog};
    props = useProps({...standardActionServiceProps});
}

registry.category("actions").add("nodo_draw.accessory_library", AccessoryLibrary);
