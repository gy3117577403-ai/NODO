import {Component, onMounted, onWillStart, onWillUnmount, signal, t, useProps} from "@odoo/owl";
import {loadBundle} from "@web/core/assets";
import {Dialog} from "@web/core/dialog/dialog";
import {registry} from "@web/core/registry";
import {useService} from "@web/core/utils/hooks";
import {standardActionServiceProps} from "@web/webclient/actions/action_plugin";

const labels = {available:"可用于装配", pending:"待工程核对"};
const faces = {door:"门板 / 左门", door_right:"右门板", top:"顶板", bottom:"底板", back:"围板背面", left:"左侧板", right:"右侧板", mount:"安装板"};

class AccessoryMesh extends Component {
    static template = "nodo_draw.AccessoryMesh";
    props = useProps({src:String, name:String});
    host = signal.ref();
    loading = signal(true);
    error = signal("");

    setup() {
        this.request = new AbortController();
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
            this.view = window.nodoDrawAE0573.mount(this.host());
            this.view.update(mesh, false, false, 0);
        } catch {
            if (!signal.aborted) this.error.set("附件模型暂时无法读取");
        } finally {
            if (!signal.aborted) this.loading.set(false);
        }
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
    selectedTab = signal("model");
    error = signal("");

    setup() {
        const orm = useService("orm");
        onWillStart(async () => {
            try {
                const rows = await orm.call("nodo.draw.accessory", "list_accessory_models", []);
                this.items.set(rows);
                const preferred = rows.find(row=>row.code===this.props.picker?.code && row.version===this.props.picker?.versions[row.code]);
                this.selectedId.set(preferred?.id ?? rows.find(row=>row.state==="available")?.id);
            } catch (error) {
                this.error.set(error.data?.message || "附件库暂时无法读取");
            }
        });
    }

    categories() { return [...new Set(this.items().map(item=>item.category))]; }
    filtered() {
        const words = this.filter().trim().toLowerCase().split(/\s+/).filter(Boolean);
        return this.items().filter(item => (!this.category() || item.category===this.category()) &&
            (!this.state() || item.state===this.state()) &&
            words.every(word => [item.name,item.code,...item.aliases].some(text=>text.toLowerCase().includes(word))));
    }
    selected() { const rows = this.filtered(); return rows.find(item=>item.id===this.selectedId()) ?? rows[0]; }
    select(item) { this.selectedId.set(item.id); this.selectedTab.set("model"); }
    version(item) { return `V${String(item.version).padStart(2,"0")}`; }
    stateName(item) { return labels[item.state]; }
    faceNames(item) { return item.faces.filter(Boolean).map(face=>faces[face]).join("、") || "待核对"; }
    cabinetKinds(item) { return item.kinds.map(kind=>kind==="double" ? "双开门" : "单开门").join("、"); }
    restriction(item) {
        const context = this.props.picker;
        if (!context) return "";
        if (item.state!=="available") return "待工程核对，暂不可安装";
        if (!item.kinds.includes(context.kind)) return "柜型不符";
        if (context.versions[item.code]!==item.version) return "此版本未列入当前设计的附件库快照";
        return "";
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
