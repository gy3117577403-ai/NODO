export const specificationGroups = [
    { label: "柜体规格", sizes: ["width_mm", "depth_mm", "overall_height_mm"], rows: [
        ["product_series", "material"], ["cabinet_height_mm", "base_height_mm"],
        ["quantity", "height_mm"], ["thickness_mm"],
    ] },
    { label: "外观配置", rows: [["door_type", "display_color"], ["coating_type"]] },
    { label: "附件与物料", rows: [["accessory", "accessory_details"]] },
    { label: "技术要求", rows: [["requirement"]] },
];

const definitions = {
    width_mm: { label: "宽度", unit: "mm", local: ["width_mm"], model: ["width_mm"], stored: true },
    depth_mm: { label: "深度", unit: "mm", local: ["depth_mm"], model: ["depth_mm"], stored: true },
    overall_height_mm: { label: "外形总高", unit: "mm", local: ["total_height"], model: ["overall_height_mm"] },
    product_series: { label: "柜体系列", model: ["product_series"], stored: true },
    material: { label: "箱体材质", model: ["material"], stored: true },
    cabinet_height_mm: { label: "柜体净高", unit: "mm", local: ["cabinet_height"], model: ["cabinet_height_mm"] },
    base_height_mm: { label: "底座高度", unit: "mm", local: ["base_height"], model: ["base_height_mm"], stored: true },
    quantity: { label: "数量", unit: "台", model: ["quantity"], stored: true },
    height_mm: { label: "报价高度", unit: "mm", local: ["height_mm", "cabinet_height", "total_height"],
        model: ["height_mm", "cabinet_height_mm", "overall_height_mm"], stored: true },
    thickness_mm: { label: "箱体料厚", unit: "mm", model: ["thickness_mm"], stored: true },
    door_type: { label: "门型", model: ["door_type"], stored: true },
    display_color: { label: "色号", model: ["display_color"], stored: true },
    coating_type: { label: "表面处理", model: ["coating"], stored: true },
    accessory: { label: "附件", model: ["accessory"], pane: "accessories" },
    accessory_details: { label: "型号/用量", model: ["accessory"], pane: "accessories" },
    requirement: { label: "技术要求", model: ["requirement", "mounting_thickness_mm", "door_thickness_mm"],
        pane: "accessories" },
};

const coatingLabels = { orange: "橘纹", gloss: "平光", none: "不喷塑" };
const localLabels = { total_height: "外形总高", cabinet_height: "柜体净高", height_mm: "图示高度" };
const sourceLabels = {
    front: "正视图", side: "侧视图", top: "俯视图", view: "视图",
    specification: "规格栏", title: "标题栏", material: "材料说明", finish: "工艺",
    requirements: "技术要求", handwriting: "手写", accessories: "附件", notes: "备注",
};
const formatter = new Intl.NumberFormat("zh-CN", { maximumFractionDigits: 3 });

export function specificationValue(value) {
    return typeof value === "number" ? formatter.format(value) : value || "";
}

function localEvidence(assist, key, definition) {
    if (!definition.local) return [];
    const axis = assist.axes?.find((entry) => entry.key === key);
    const chosen = axis ? assist.token(axis) : null;
    const options = [];
    for (const [role, box] of Object.entries(assist.state.boxes)) {
        for (const token of box.tokens || []) {
            if (!definition.local.includes(token.dimension_key) && token !== chosen) continue;
            options.push({
                key: `local-${role}-${token.id}`, role, token,
                label: localLabels[token.dimension_key] || definition.label,
                page: box.page, value: token.value, unit: definition.unit,
                chosen: role === assist.role(axis || { key }) && token.id === chosen?.id,
            });
        }
    }
    return options;
}

function modelEvidence(runs, fields, details) {
    if (!fields) return [];
    const seen = new Set();
    const options = [];
    for (const run of runs) {
        for (const item of run.items) {
            if (!fields.includes(item.field)) continue;
            if (details && !item.model_code && !item.quantity) continue;
            const key = JSON.stringify([item.field, item.candidate, item.value, item.unit, item.status, run.page,
                item.field === "accessory" ? item.text : null]);
            if (seen.has(key)) continue;
            seen.add(key);
            let value = item.candidate ?? item.value;
            if (details) value = [item.model_code, item.quantity].filter(Boolean).join(" · ");
            if (item.field === "coating") value = coatingLabels[value] || value;
            options.push({
                key: `vision-${run.id}-${item.id}`, run, item, page: run.page, label: item.label,
                value, unit: item.field === "accessory" ? "" : item.unit,
                pending: !item.decision, sourceLabel: sourceLabels[item.source_kind],
            });
        }
    }
    return options;
}

export function drawingSpecifications(assist) {
    const { record, vision } = assist;
    const data = record.data;
    const runs = vision.runs;
    const missing = new Set(runs.find((run) => run.mode === "page")?.missing_fields || []);
    const startedReading = runs.length || Object.keys(assist.state.boxes).length ||
        ["review", "done", "failed"].includes(data.recognition_state);
    const selections = (data.accessory_selection_data?.allocations || []).filter((item) => item.selected !== false);
    const entries = {};
    for (const [key, definition] of Object.entries(definitions)) {
        const current = definition.stored ? data[key] || "" : "";
        const local = localEvidence(assist, key, definition);
        const model = modelEvidence(runs, definition.model, key === "accessory_details");
        const chosen = local.find((option) => option.chosen) || model.find((option) =>
            option.item.decision === "apply" && (option.item.reviewed_value ?? option.item.candidate) === current);
        const pending = key === "height_mm" && chosen ? undefined : model.find((option) => option.pending);
        const read = local[0] || model.find((option) => option.item.status === "explicit");
        const evidence = pending || chosen || (definition.stored ? model.find((option) =>
            option.item.decision === "keep") : read || model[0]);
        let value = current || (!definition.stored ? read?.value || read?.item?.text : "");
        let unit = definition.unit || "";
        let status = "";
        let statusLabel = "";
        if (!definition.stored && !local.length && read) unit = read.item?.reviewed_unit || read.unit || "";
        if (key === "coating_type") value = coatingLabels[value] || value;
        if (key === "width_mm" && data.width_expression?.includes("+")) value = data.width_expression;
        if (key === "accessory" && selections.length) {
            value = [...new Set(selections.map((item) => item.name).filter(Boolean))].join("、");
        }
        if (key === "requirement") value = data.selection_notes || value || read?.item?.text || "";
        if (key === "accessory_details") {
            const first = selections[0];
            const complete = selections.every((item) => item.model_code && item.quantity > 0);
            if (first && complete) {
                value = selections.length === 1 ? `${first.model_code} · ${first.quantity} 件/台` : `已录 ${selections.length} 项`;
            } else if (!first && evidence) {
                value = evidence.value;
            } else if (selections.length || entries.accessory.value) {
                status = "missing";
                statusLabel = "缺失";
            }
        }
        if (["accessory", "requirement"].includes(key) && !value && pending?.item.text) value = pending.item.text;
        if (pending || (key === "height_mm" && !chosen && local.some((option) => !option.chosen))) {
            status = "pending";
            statusLabel = "待确认";
        } else if (!value && !status && key !== "accessory_details") {
            const absent = definition.model?.every((name) => missing.has(name));
            status = absent || (!definition.model && !definition.local) ? "missing" : startedReading ? "unread" : "idle";
            statusLabel = { unread: "未识别", idle: "待识读", missing: "缺失" }[status];
        }
        const candidateValue = definition.stored && key !== "height_mm" && pending?.value;
        const comparison = pending?.item.candidate ?? candidateValue;
        const conflict = Boolean(candidateValue && current &&
            String(comparison).toUpperCase() !== String(current).toUpperCase());
        if (candidateValue && !current) {
            value = candidateValue;
            unit = pending.unit || "";
        }
        const options = [...local, ...model.filter((option) => option.pending || option === evidence)];
        entries[key] = {
            key, label: definition.label, value, unit, status, statusLabel, evidence, options, conflict,
            candidate: conflict ? specificationValue(candidateValue) : "",
            candidateUnit: conflict ? pending.unit || "" : "",
            pane: definition.pane || "parameters",
        };
    }
    return entries;
}
