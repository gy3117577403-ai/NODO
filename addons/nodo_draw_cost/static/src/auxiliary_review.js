import {Component, onMounted, onWillUnmount, signal, t, useProps} from "@odoo/owl";
import {useService} from "@web/core/utils/hooks";
import {AccessoryMesh, accessoryFaceNames, accessoryPreviewExample} from "@nodo_draw/accessory_library";
import {unitPrice} from "./live_sheet_prices";

const states = {
    unlinked: "待关联模型",
    retired: "模型已停用",
    other_company: "请切换到档案所属公司",
    no_mesh: "预览文件待生成",
    missing: "未匹配到辅材档案",
    loading: "正在读取三维模型…",
    error: "三维模型信息读取失败",
};

export const modelStatusLabel = status => ({
    available:"已关联模型", pending:"模型待工程核对", retired:"模型已停用", unlinked:"待关联模型",
})[status] || states.missing;

export class AuxiliaryModelPreview extends Component {
    static template = "nodo_draw_cost.AuxiliaryModelPreview";
    static components = {AccessoryMesh};
    props = useProps({rateId:t.number()});
    result = signal({status:"loading"});
    example = signal(null);
    request = 0;
    faceNames = accessoryFaceNames;

    setup() {
        this.orm = useService("orm");
        onMounted(() => this.readModel());
        onWillUnmount(() => this.request++);
    }

    status() { return states[this.result().status]; }

    version(model) {
        return model.code + " · V" + String(model.version).padStart(2, "0");
    }

    async readModel() {
        const request = ++this.request;
        if (!this.props.rateId) {
            this.result.set({status:"missing"});
            return;
        }
        this.result.set({status:"loading"});
        try {
            const result = await this.orm.call("nodo.cost.auxiliary.price", "auxiliary_model_preview", [[this.props.rateId]]);
            if (request === this.request) this.result.set(result);
        } catch {
            if (request === this.request) this.result.set({status:"error"});
        }
    }

    async showExample() {
        const request = ++this.request;
        this.example.set({loading:true});
        try {
            const model = await accessoryPreviewExample(this.orm);
            if (request === this.request) this.example.set({model, error:model ? "" : "附件库暂无可预览的模型。"});
        } catch {
            if (request === this.request) this.example.set({error:"示例读取失败，请重试。"});
        }
    }
}

export class AuxiliaryReview extends Component {
    static template = "nodo_draw_cost.AuxiliaryReview";
    static components = {AuxiliaryModelPreview};
    props = useProps({row:t.object(), position:t.number(), count:t.number(), move:t.function(), close:t.function(),
        basis:t.string()});
    unitPrice = unitPrice;
}
