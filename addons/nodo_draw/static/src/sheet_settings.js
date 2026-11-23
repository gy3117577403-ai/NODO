import {Component, signal, useProps} from "@odoo/owl";

const groupNames = {body: "箱体", door: "门板", mount: "安装板"};
const groupPart = {body: "wrap", door: "door", mount: "mount"};

function groupMaterial(materials, catalog, group) {
    return materials[group] ?? {category: catalog.groups[group]};
}

function partMaterial(materials, catalog, part) {
    const group = catalog.parts[part];
    const value = materials.parts?.[part] ?? materials[group] ??
        {...groupMaterial(materials, catalog, group), finish: catalog.sourceFinish[part] || ""};
    return {...value, finish: materials.finishes?.[part] ?? value.finish};
}

export class SheetSettings extends Component {
    static template = "nodo_draw.SheetSettings";
    props = useProps({designId: Number, catalog: Object, values: Object, disabled: Boolean, change: Function, save: Function});
    byPart = signal(false);
    detail = signal(null);

    setup() {
        this.fields = [["grade", "牌号"], ["condition", "来料状态或镀层"], ["finish", "表面处理"], ["note", "材料依据"]];
    }

    rows() {
        const {materials, thickness, kind} = this.props.values;
        const catalog = this.props.catalog;
        if (!this.byPart()) {
            return Object.entries(groupPart).map(([key, part]) => {
                const rule = catalog.sheets.parts[part];
                const overrides = Object.keys(catalog.sheets.parts).filter(id =>
                    catalog.materials.parts[id] === key &&
                    (materials.parts?.[id] || Object.hasOwn(thickness.parts || {}, id))).length;
                return {key, name: groupNames[key], rule, material: groupMaterial(materials, catalog.materials, key),
                    thickness: Object.hasOwn(thickness, key) ? thickness[key] : rule.default, overrides};
            });
        }
        return Object.entries(catalog.sheets.parts).map(([key, rule]) => {
            const group = catalog.materials.parts[key];
            const independentMaterial = Object.hasOwn(materials.parts || {}, key);
            const independentThickness = Object.hasOwn(thickness.parts || {}, key);
            const groupThickness = Object.hasOwn(thickness, rule.group) ? thickness[rule.group] : rule.default;
            return {key, rule, name: rule.name + (key === "door" && kind === "double" ? "（双门共用）" : ""),
                material: partMaterial(materials, catalog.materials, key),
                thickness: independentThickness ? thickness.parts[key] : groupThickness,
                independent: independentMaterial || independentThickness,
                source: !independentMaterial && !independentThickness && key !== "brace"
                    ? "跟随" + groupNames[group]
                    : (independentMaterial ? "材料独立" : "材料跟随" + groupNames[group]) + " · " +
                        (independentThickness ? "厚度独立" : key === "brace" ? "厚度取原图" : "厚度跟随" + groupNames[group])};
        });
    }

    toggleMode() {
        this.detail.set(null);
        this.byPart.set(!this.byPart());
    }

    changeCategory(row, category) {
        const old = row.material;
        if (category === old.category) return;
        this.writeMaterial(row.key, {category, ...(old.finish !== undefined ? {finish: old.finish} : {}),
            ...(old.note ? {note: old.note} : {})});
    }

    changeDetail(row, field, value) {
        this.writeMaterial(row.key, {...row.material, [field]: value}, field === "finish");
    }

    writeMaterial(key, choice, setGroupFinish = false) {
        this.props.change({materials:this.materialValues(key, choice, setGroupFinish)});
    }

    materialValues(key, choice, setGroupFinish = false) {
        const before = this.props.values.materials;
        const catalog = this.props.catalog.materials;
        const finishes = {...before.finishes};
        const next = {...before};
        if (this.byPart()) {
            next.parts = {...before.parts, [key]: choice};
            delete finishes[key];
        } else {
            next[key] = choice;
            for (const part of Object.keys(catalog.parts)) {
                if (catalog.parts[part] !== key || before.parts?.[part]) continue;
                if (setGroupFinish) delete finishes[part];
                else finishes[part] = partMaterial(before, catalog, part).finish || "";
            }
        }
        if (Object.keys(finishes).length) next.finishes = finishes;
        else delete next.finishes;
        return next;
    }

    changeThickness(key, text) {
        this.props.change({thickness:this.thicknessValues(key, text === "" ? null : Number(text))});
    }

    thicknessValues(key, value) {
        const thickness = {...this.props.values.thickness};
        if (this.byPart()) thickness.parts = {...thickness.parts, [key]: value};
        else thickness[key] = value;
        return thickness;
    }

    restore(part) {
        const materials = {...this.props.values.materials};
        const thickness = {...this.props.values.thickness};
        for (const [config, key] of [[materials, "parts"], [materials, "finishes"], [thickness, "parts"]]) {
            const overrides = {...config[key]};
            delete overrides[part];
            if (Object.keys(overrides).length) config[key] = overrides;
            else delete config[key];
        }
        this.props.change({materials, thickness});
    }
}
