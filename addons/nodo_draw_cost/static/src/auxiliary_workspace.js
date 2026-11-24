import {Component, onWillStart, onWillUnmount, signal, useOnChange, useProps} from "@odoo/owl";
import {registry} from "@web/core/registry";
import {user} from "@web/core/user";
import {useOwnedDialogs, useService} from "@web/core/utils/hooks";
import {listView} from "@web/views/list/list_view";
import {ListRenderer, listRendererProps} from "@web/views/list/list_renderer";
import {FormViewDialog} from "@web/views/view_dialogs/form_view_dialog";
import {AccessoryMesh, accessoryFaceNames} from "@nodo_draw/accessory_library";
import {unitPrice} from "./live_sheet_prices";

const modelStatusMessages = {
    unlinked: ["待关联模型", "关联对应的型号和版次后，三维模型会显示在这里。"],
    loading: ["正在读取模型", ""],
    no_mesh: ["预览文件待生成", "此版已关联，三维预览文件准备好后即可查看。"],
    retired: ["模型已停用", "可在辅料档案中核对适用的型号版本。"],
    restricted: ["三维预览限技术岗位和管理员", ""],
    other_company: ["请切换到档案所属公司", "三维预览使用当前公司的附件模型。"],
    error: ["模型信息读取失败", "可以重新读取当前版本。"],
};

class AuxiliaryWorkspace extends Component {
    static template = "nodo_draw_cost.AuxiliaryWorkspace";
    static components = {AccessoryMesh, ListRenderer};
    props = useProps(listRendererProps);
    selectedId = signal(null);
    preview = signal(null);
    example = signal(null);
    permissions = signal({});
    readRequest = 0;
    exampleRequest = 0;
    unitPrice = unitPrice;
    faceNames = accessoryFaceNames;

    setup() {
        this.orm = useService("orm");
        this.dialog = useOwnedDialogs();
        onWillStart(async () => {
            const [admin, engineering, costing] = await Promise.all([
                user.hasGroup("base.group_system"),
                user.hasGroup("nodo_base.group_role_engineering"),
                user.hasGroup("nodo_base.group_role_costing"),
            ]);
            this.permissions.set({preview:admin || engineering, edit:admin || costing});
        });
        useOnChange(() => {
            const record = this.record();
            return [record?.resId, record?.data.cad_model_status, record?.data.cad_model_label, this.canPreview];
        }, () => this.readModel());
        onWillUnmount(() => {
            this.readRequest++;
            this.exampleRequest++;
        });
    }

    get canPreview() { return this.permissions().preview; }
    get canEdit() { return this.permissions().edit; }

    record() {
        if (this.props.list.isGrouped) return null;
        const records = this.props.list.records;
        return records.find(item => item.resId === this.selectedId()) ?? records[0];
    }

    label(field, value) {
        return this.props.list.fields[field]?.selection?.find(([key]) => key === value)?.[1] || "—";
    }

    version(model) {
        return model.code + " · V" + String(model.version).padStart(2, "0");
    }

    async readModel() {
        const request = ++this.readRequest;
        this.closeExample();
        this.preview.set(null);
        const record = this.record();
        if (!this.canPreview || !record || !["available", "pending"].includes(record.data.cad_model_status)) return;
        const id = record.resId;
        try {
            const result = await this.orm.call(record.resModel, "auxiliary_model_preview", [[id]]);
            if (request === this.readRequest) this.preview.set({id, ...result});
        } catch {
            if (request === this.readRequest) this.preview.set({id, status:"error"});
        }
    }

    async showExample() {
        const id = this.record()?.resId;
        if (!id || !this.canPreview || this.example()?.loading) return;
        const request = ++this.exampleRequest;
        this.example.set({id, loading:true});
        try {
            const models = await this.orm.call("nodo.draw.accessory", "list_accessory_models", []);
            const model = models.find(item => item.state === "available" && item.mesh);
            if (request !== this.exampleRequest) return;
            this.example.set({id, model, error:model ? "" : "附件库中暂时没有可预览的模型。"});
        } catch {
            if (request === this.exampleRequest) this.example.set({id, error:"示例模型读取失败，请重试。"});
        }
    }

    closeExample() {
        this.exampleRequest++;
        this.example.set(null);
    }

    viewport(record) {
        const example = this.example()?.id === record.resId ? this.example() : null;
        const result = this.preview()?.id === record.resId ? this.preview() : null;
        const status = record.data.cad_model_status;
        const state = status === "unlinked" || status === "retired" ? status :
            !this.canPreview ? "restricted" : result?.status ?? "loading";
        return {state, model:example?.model || result?.model, example,
            message:modelStatusMessages[state] || modelStatusMessages.error};
    }

    openRecord(record) {
        this.dialog(FormViewDialog, {
            resModel:record.resModel, resId:record.resId,
            context:{...record.context, form_view_ref:"nodo_cost.auxiliary_library_form"},
            title:this.canEdit ? "编辑辅料档案" : "辅料档案",
            readonly:!this.canEdit, preventCreate:true, canExpand:false, size:"xl",
            onRecordSaved:() => this.props.list.load(),
        });
    }
}

registry.category("views").add("nodo_auxiliary_library", {...listView, Renderer:AuxiliaryWorkspace});
