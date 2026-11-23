// Selection and drawing controls adapted from Jingneng sales c3c120987925ec1b4f417f6c3d398b7f7ce9e6ce.
import { Dialog } from "@web/core/dialog/dialog";
import { SelectionField, selectionField } from "@web/views/fields/selection/selection_field";
import { BinaryField, binaryField } from "@web/views/fields/binary/binary_field";
import { getDataURLFromFile } from "@web/core/utils/urls";
import { checkFileSize } from "@web/core/utils/files";
import { Component, onMounted, onWillStart, onWillUnmount, proxy, signal, t, useOnChange, useProps } from "@odoo/owl";
import { standardFieldProps } from "@web/views/fields/standard_field_props";
import { FloatField, floatField } from "@web/views/fields/float/float_field";
import { registry } from "@web/core/registry";
import { useService } from "@web/core/utils/hooks";
import { formView } from "@web/views/form/form_view";
import { FormController } from "@web/views/form/form_controller";
import { PdfViewerField, pdfViewerField } from "@web/views/fields/pdf_viewer/pdf_viewer_field";
import { ImageField, imageField } from "@web/views/fields/image/image_field";
import { Many2XAutocomplete } from "@web/views/fields/relational_utils";
import { Dropdown } from "@web/core/dropdown/dropdown";
import { DropdownItem } from "@web/core/dropdown/dropdown_item";
import { ConfirmationDialog } from "@web/core/confirmation_dialog/confirmation_dialog";
import { CheckBox } from "@web/core/checkbox/checkbox";
import { usePopover } from "@web/core/popover/popover_hook";
import { saleOrderFormView } from "@sale/views/sale_order_form_view/sale_order_form_view";
import { DrawingVisionSession } from "./vision";
import { bindDrawingOverview } from "./drawing_overview";
import { drawingSpecifications, specificationGroups, specificationValue } from "./drawing_results";

class ChineseRecognitionMessage extends Component {
    static template="nodo_contract.ChineseRecognitionMessage";
    props=useProps({...standardFieldProps});
    get message(){
        const labels={OCR:"文字识别",AI:"智能识别",API:"接口",JSON:"结构化数据",HTTP:"网络协议"};
        return String(this.props.record.data[this.props.name] || "").replace(/\b(OCR|AI|API|JSON|HTTP)\b/g,word=>labels[word]);
    }
}
registry.category("fields").add("nodo_contract_chinese_recognition_message",{component:ChineseRecognitionMessage,supportedTypes:["text","char"]});

const quoteSelectionSessions = new WeakMap();
const cabinetFieldSessions=new WeakMap();
function trackCabinetField(field){
    const record=field.props.record;
    const fields=cabinetFieldSessions.get(record) || new Set();
    fields.add(field);cabinetFieldSessions.set(record,fields);
    onWillUnmount(()=>fields.delete(field));
}

const parameterMaterials = [["SECC", "碳钢 SECC"], ["SUS304", "不锈钢 SUS304"], ["SUS316", "不锈钢 SUS316"]];
const parameterDoors = ["前单开门后背板", "前双开门后背板", "前后单开门",
    "前单开门后双开门", "前双开门后单开门", "前后双开门"];
const cabinetClone = value => JSON.parse(JSON.stringify(value));
const cabinetDoorOptions = series => ["JP","JS","JP WIDE","JS WIDE"].includes(series)
    ? parameterDoors : ["JA","JE"].includes(series) ? parameterDoors.slice(0,2) : parameterDoors.slice(0,1);
function cabinetValues(values, expression = values.width_expression ?? String(values.width_mm || "")) {
    expression = String(expression).trim();
    if (expression && (!/^\d+(?:\.\d+)?$/.test(expression) || !Number.isFinite(Number(expression)) || Number(expression) <= 0)) {
        throw Error("请填写一个大于零的单柜宽度，单位为毫米。");
    }
    const width = Number(expression);
    const options = cabinetDoorOptions(values.product_series);
    const previous = values.cabinet_configuration?.cabinets?.[0];
    const manual = previous?.door_manual === true && options.includes(previous.door_type);
    const door = manual ? previous.door_type : options[width > 800 && options.length > 1 ? 1 : 0];
    const cabinets = width ? [{ index: 0, width_mm: width, door_type: door, door_manual: manual }] : [];
    return {
        width_expression: width ? String(width) : "",
        width_mm: width,
        cabinet_configuration: {version: 1, cabinets},
        door_type: width ? door : "",
    };
}
const cabinetRows = values => values.cabinet_configuration?.cabinets || [];

class CabinetDoors extends Component {
    static template="nodo_contract.CabinetDoors";
    props=useProps({values:t.object(),readonly:t.boolean().optional(false),change:t.function()});
    get rows(){return cabinetRows(this.props.values);}
    get options(){return cabinetDoorOptions(this.props.values.product_series);}
    change(index,event){
        const config=cabinetClone(this.props.values.cabinet_configuration);
        config.cabinets[index]={...config.cabinets[index],door_type:event.target.value,door_manual:true};
        return this.props.change(config);
    }
}

class CabinetWidthField extends Component {
    static template="nodo_contract.CabinetWidthField";
    props=useProps({...standardFieldProps});
    setup() {
        this.state = proxy({error: "", draft: null});
        this.assist = drawingDimensionSession(this.props.record, useService("orm"));
        this.saving = Promise.resolve();
        trackCabinetField(this);
    }
    get value(){return this.state.draft ?? (this.props.record.data.width_expression || String(this.props.record.data.width_mm || ""));}
    get source() {
        const axis = dimensionAxes[0];
        const token = this.assist.token(axis);
        return token?.value === Number(this.value) ? this.assist.source(axis) : "";
    }
    focusSource() {
        this.assist.focus(dimensionAxes[0]);
    }
    get options() {
        return this.assist.options(dimensionAxes[0]);
    }
    chooseOption(event) {
        const token = this.options.find(item => item.id === event.target.value);
        if (token) this.assist.edit(dimensionAxes[0], token.value, token.id);
    }
    change(event){
        this.state.draft=event.target.value;
        this.saving=(async()=>{
            try{const changes=cabinetValues(this.props.record.data,this.state.draft);await this.props.record.resetFieldValidity(this.props.name);await this.props.record.update(changes);this.state.draft=null;this.state.error="";}
            catch(error){this.state.error=error.data?.message || error.message;await this.props.record.setInvalidField(this.props.name);}
        })();
        return this.saving;
    }
}
registry.category("fields").add("nodo_contract_cabinet_width",{component:CabinetWidthField,supportedTypes:["char"]});

class CabinetDoorsField extends Component {
    static template="nodo_contract.CabinetDoorsField";
    static components={CabinetDoors};
    props=useProps({...standardFieldProps});
    setup(){this.state=proxy({config:null,error:""});this.revision=0;this.saving=Promise.resolve();trackCabinetField(this);}
    get values(){const data=this.props.record.data;return {...data,...(this.state.config?{cabinet_configuration:this.state.config}:data.cabinet_configuration?{}:cabinetValues(data))};}
    change(config){
        const revision=++this.revision;
        this.state.config=config;this.state.error="";
        this.saving=(async()=>{
            try{
                await this.props.record.update({cabinet_configuration:config,door_type:config.cabinets[0]?.door_type || ""});
                if(revision===this.revision){this.state.config=null;await this.props.record.resetFieldValidity(this.props.name);}
            }catch(error){
                if(revision===this.revision){this.state.error=error.data?.message || error.message;await this.props.record.setInvalidField(this.props.name);}
            }
        })();
        return this.saving;
    }
}
registry.category("fields").add("nodo_contract_cabinet_doors",{component:CabinetDoorsField,supportedTypes:["json"]});

class CabinetAllocations extends Component {
    static template="nodo_contract.CabinetAllocations";
    props=useProps({values:t.object(),readonly:t.boolean().optional(false),change:t.function(),
        evidence:t.object().optional()});
    setup(){this.state=proxy({error:"",saving:false});}
    get data(){return this.props.values.accessory_selection_data || {};}
    get rows(){return this.data.allocations || [];}
    dimensionText(item) {
        return Object.keys(item.manual_inputs || {}).length ? JSON.stringify(item.manual_inputs) : "";
    }
    sourceText(item) {
        const fact = this.props.evidence?.[item.name];
        if (!fact) return "";
        if (fact.source === "part_number") return `图纸料号 · ${fact.part_number}`;
        return fact.source === "manual" ? "手动添加" : '图纸匹配 · ' + fact.match_rate + '% · ' + fact.overlap;
    }
    canRemove(item) {
        return !this.props.readonly && this.data.manual_names?.includes(item.name);
    }
    async remove(item) {
        if (!this.canRemove(item) || this.state.saving) return;
        const data = cabinetClone(this.data);
        data.allocations = data.allocations.filter(row => row.name !== item.name);
        data.manual_names = data.manual_names.filter(name => name !== item.name);
        delete data.choices[item.name];
        return this.save(data);
    }
    async update(index, field, event) {
        if (this.props.readonly || this.state.saving) return;
        const data = cabinetClone(this.data);
        const item = data.allocations[index];
        if (field === "quantity") {
            const value = event.target.value;
            item.quantity = value === "" ? null : Number(value);
            if (item.quantity !== null && (!Number.isFinite(item.quantity) || item.quantity <= 0)) {
                this.state.error = "附件每台用量须大于零。";
                return;
            }
        } else if (field === "model_code") {
            item.model_code = event.target.value;
        } else {
            item.selected = event.target.checked;
            data.choices[item.name] = item.selected;
        }
        return this.save(data);
    }
    async updateDimensions(index, event) {
        if (this.props.readonly || this.state.saving) return;
        const data = cabinetClone(this.data);
        try {
            const dimensions = JSON.parse(event.target.value || "{}");
            if (!dimensions || Array.isArray(dimensions) || typeof dimensions !== "object" ||
                Object.values(dimensions).some(value => !Number.isFinite(value) || value <= 0)) {
                throw Error();
            }
            data.allocations[index].manual_inputs = dimensions;
        } catch {
            this.state.error = '请输入有效毫米值，例如 {"长度": 600}。';
            return;
        }
        return this.save(data);
    }
    async save(data){
        this.state.saving=true;this.state.error="";
        try{await this.props.change(data);}catch(error){this.state.error=error.data?.message||error.message||"保存失败，请重试。";}
        finally{this.state.saving=false;}
    }
}

class QuoteParameterEditor extends Component {
    static template = "nodo_contract.QuoteParameterEditor";
    static components={CabinetDoors};
    props = useProps({ values: t.object(), save: t.function(), close: t.function() });
    rootRef = signal.ref();
    setup() {
        this.state = proxy({ values: cabinetClone(this.props.values), saving: false, error: "" });
        onMounted(() => this.rootRef()?.querySelector("select")?.focus());
    }
    get materials() {
        const current = this.props.values.material;
        return parameterMaterials.some(([value]) => value === current) || !current
            ? parameterMaterials : [...parameterMaterials, [current, current]];
    }
    get doors() {
        return cabinetDoorOptions(this.state.values.product_series);
    }
    changeCabinets(config){this.state.values.cabinet_configuration=config;this.state.values.door_type=config.cabinets[0]?.door_type || "";}
    change(name, event) { this.state.values[name] = event.target.value; this.state.error = ""; }
    async save() {
        if (this.state.saving) return;
        const values = { ...this.state.values, thickness_mm: Number(this.state.values.thickness_mm) };
        if (!values.material || !Number.isFinite(values.thickness_mm) || values.thickness_mm <= 0) {
            this.state.error = "请选择材质，并填写大于零的料厚。";
            return;
        }
        this.state.saving = true;
        try { await this.props.save(values); this.props.close(); }
        catch (error) { this.state.error = error.message || "保存失败，请重试。"; }
        finally { this.state.saving = false; }
    }
}

class QuoteProductAutocomplete extends Many2XAutocomplete {
    get autoCompleteProps() { return { ...super.autoCompleteProps, resetOnSelect: false }; }
}

class QuoteSelectionTable extends Component {
    static template = "nodo_contract.QuoteSelectionTable";
    static components = { Many2XAutocomplete: QuoteProductAutocomplete, Dropdown, DropdownItem, CheckBox, CabinetAllocations };
    props = useProps({ ...standardFieldProps });
    rootRef = signal.ref();
    setup() {
        this.orm = useService("orm");
        this.action = useService("action");
        this.dialog = useService("dialog");
        this.notification = useService("notification");
        this.parameterEditor = usePopover(QuoteParameterEditor, { position: "bottom-end", role: "dialog" });
        this.state = proxy({
            rows: [], attachments: [], drawing: false, editable: true, loading: false,
            busy: false, reloading: false, error: "", editing: "", showState: true,
        });
        try { this.state.showState = localStorage.getItem("nodo.contract.quoteSelection.showState") !== "false"; } catch { /* optional preference */ }
        this.axes = [{name:"width_mm",label:"宽度"},{name:"depth_mm",label:"深度"},{name:"height_mm",label:"高度"}];
        this.saving = Promise.resolve();
        this.pending = new Set();
        this.rowRevisions=new Map();
        this.next = 0;
        this.disposed = false;
        quoteSelectionSessions.set(this.props.record, this);
        onMounted(() => this.refresh());
        useOnChange(() => [this.props.record.resId, this.props.record.data.drawing_recognition_version],
            () => { if (!this.pending.size && !this.state.editing) this.refresh(); });
        onWillUnmount(() => { this.disposed = true; this.closeAccessoryPicker?.(); });
    }
    get editable() { return !this.props.readonly && this.state.editable && !this.state.loading; }
    get busy() { return this.state.busy || this.state.loading || this.state.reloading; }
    get columns() { return this.state.drawing && this.state.showState ? 5 : 4; }
    get hasProducts() { return this.state.rows.some(row => !row.display_type); }
    get pollingBlocked() { return !this.disposed && (this.busy || this.pending.size || this.state.editing); }
    toggleState() {
        this.state.showState = !this.state.showState;
        try { localStorage.setItem("nodo.contract.quoteSelection.showState",String(this.state.showState)); } catch { /* optional preference */ }
    }
    getDomain() {
        const domain = [["sale_ok", "=", true], ["product_tmpl_id.nodo_cabinet_series", "!=", false]];
        const company = this.props.record.data.company_id?.id;
        if (company) domain.push(["company_id", "in", [false, company]]);
        return domain;
    }
    async ensureOrder() {
        if (this.props.record.isNew || await this.props.record.isDirty()) {
            if (!await this.props.record.save()) throw Error("请先填写客户等必填信息，再继续操作。");
        }
        return this.props.record.resId;
    }
    async refresh(force = false) {
        if (this.disposed || this.pending.size) return;
        if (this.refreshPromise) {
            await this.refreshPromise;
            if (!force) return;
        }
        if (!this.props.record.resId) return;
        this.state.loading = true;
        this.refreshPromise = (async () => {
            try {
                if (await this.props.record.isDirty() && !await this.props.record.save()) return;
                const data = await this.orm.call("sale.order", "get_selection_table", [[this.props.record.resId]]);
                if (!this.disposed) {
                    const drafts = this.state.rows.filter(row => row.key.startsWith("new_") && !row.line_id);
                    this.state.rows = [...data.rows, ...drafts];
                    this.state.attachments = data.attachments;
                    this.state.drawing = data.drawing;
                    this.state.editable = data.editable;
                    this.state.error = "";
                }
            } catch (error) { this.fail(error); }
            finally { if (!this.disposed) this.state.loading = false; }
        })();
        try { await this.refreshPromise; }
        finally { this.refreshPromise = null; }
    }
    fail(error) { if (!this.disposed) this.state.error = error.data?.message || error.message || "保存失败，请重试。"; }
    status(row) { return row.state === "confirmed" ? "已选型" : "待选型"; }
    recognition(row) {
        return { idle: "待本地读取", queued: "本地读取排队中", processing: "本地读取中", review: "本地结果待核",
            done: "本地结果已核", failed: "本地未提取" }[row.recognition_state] || "";
    }
    isRecognizing(row) { return ["queued", "processing"].includes(row.recognition_state); }
    parameters(row) {
        const coating = { none: "无喷塑", gloss: "平光", orange: "橘纹" }[row.coating_type] || "";
        return [row.material, row.thickness_mm ? `${row.thickness_mm} 毫米` : "", cabinetRows(row).length>1?"":row.door_type,
            coating, row.display_color]
            .filter(Boolean).join(" · ");
    }
    editParameters(row, event) {
        if (!this.editable || this.busy || this.isRecognizing(row)) return;
        if (row.source === "drawing" && row.drawing_id && !row.independent) return this.configure(row);
        const names = ["material", "thickness_mm", "door_type", "coating_type", "display_color",
            "cabinet_configuration", "product_series", "width_expression", "width_mm", "depth_mm", "height_mm"];
        const values = Object.fromEntries(names.map(name => [name, row[name] ?? ""]));
        this.parameterEditor.open(event.currentTarget, {
            values,
            save: async changes => {
                if (this.disposed || !this.editable || !this.state.rows.includes(row)) throw Error("产品行已变化，请重新打开修改。");
                const previous = Object.fromEntries(names.map(name => [name, row[name]]));
                Object.assign(row, changes);
                if (row.product_id) {
                    await this.saveRow(row);
                    if (this.pending.has(row.key)) {
                        Object.assign(row, previous);
                        throw Error(this.state.error || "保存失败，请重试。");
                    }
                }
            },
        });
    }
    async add(displayType = false) {
        if (!this.editable || (this.state.drawing && !displayType)) return;
        this.state.rows.push({ key: `new_${++this.next}`, product_name: "", product_id: false,
            source: "manual", display_type: displayType, text: "", quantity: 1,
            width_mm: 0, depth_mm: 0, height_mm: 0, thickness_mm: 1.5,
            material: "SECC", coating_type: "orange", display_color: "RAL7035 浅灰" });
        requestAnimationFrame(() => {
            const cells = this.rootRef()?.querySelectorAll("tbody tr.o_quote_product_row input");
            cells?.[Math.max(0, cells.length - (displayType ? 1 : 5))]?.focus();
        });
    }
    async productChanged(row, records) {
        const product = records?.[0];
        row.product_id = product?.id || false;
        row.product_name = product?.display_name || product?.name || "";
        this.state.rows = [...this.state.rows];
        if (!row.product_id) {
            this.pending.add(row.key);
            this.state.error = "请选择产品后继续，或删除此行。";
            return;
        }
        if (row.product_id) {
            try{
            const requested=row.product_id;
            const fields=await this.orm.read("product.product",[row.product_id],["product_tmpl_id"]);
            const template=fields[0].product_tmpl_id;
            const templates=await this.orm.read("product.template",[Array.isArray(template)?template[0]:template.id||template],["nodo_cabinet_series"]);
            if(this.disposed || requested!==row.product_id)return;
            row.product_series=templates[0].nodo_cabinet_series || row.product_series;
            Object.assign(row,cabinetValues(row));
            await this.saveRow(row);
            }catch(error){this.pending.add(row.key);this.fail(error);}
        }
    }
    edit(row,field,event){
        if(!this.editable)return;
        if(field==="width_mm")row.width_expression=event.target.value;
        else row[field]=["quantity","depth_mm","height_mm"].includes(field)?Number(event.target.value || 0):event.target.value;
        this.rowRevisions.set(row.key,(this.rowRevisions.get(row.key)||0)+1);
        this.pending.add(row.key);
    }
    async change(row, field, event) {
        if(field==="width_mm"){
            row.width_expression=event.target.value;
            try{Object.assign(row,cabinetValues(row,row.width_expression));row.width_error="";}
            catch(error){row.width_error=error.message;this.pending.add(row.key);this.state.error=error.message;return;}
            return this.saveRow(row);
        }
        row[field] = ["quantity", "width_mm", "depth_mm", "height_mm", "thickness_mm"].includes(field)
            ? Number(event.target.value || 0) : event.target.value;
        await this.saveRow(row);
    }
    async saveRow(row) {
        if (!this.editable) return;
        if (!row.product_id && !row.display_type) return;
        if(row.width_error){this.pending.add(row.key);return false;}
        this.pending.add(row.key);
        const revision=(this.rowRevisions.get(row.key)||0)+1;
        this.rowRevisions.set(row.key,revision);
        const payload=JSON.parse(JSON.stringify(row));
        const work = async () => {
            try {
                const id = await this.ensureOrder();
                const result = await this.orm.call("sale.order", "save_selection_line",
                    [[id], {...payload,line_id:row.line_id || payload.line_id}]);
                row.line_id = result.line_id;
                if(this.rowRevisions.get(row.key)!==revision)return true;
                Object.assign(row,result.values || {});
                row.product_name = result.product_name;
                row.product_series = result.product_series || row.product_series;
                this.pending.delete(row.key);
                this.needsReload = true;
                this.state.error = "";
                return true;
            } catch (error) { this.fail(error); return false; }
        };
        this.saving = this.saving.then(work, work);
        return this.saving;
    }
    async flush() {
        let saving;
        do { saving=this.saving; await saving; } while(saving!==this.saving);
        return !this.pending.size;
    }
    async reloadRoot() {
        if (this.reloadPromise) return this.reloadPromise;
        this.state.reloading = true;
        this.reloadPromise = (async () => {
            try {
                if (!await this.flush()) return;
                this.state.editing = "";
                if (await this.props.record.isDirty() && !await this.props.record.save()) return;
                this.needsReload = false;
                await this.props.record.load();
                await this.refresh(true);
            } finally { this.state.reloading = false; }
        })();
        try { await this.reloadPromise; }
        finally { this.reloadPromise = null; }
    }
    async execute(method, args = [], open = false) {
        if (this.busy || !await this.flush()) return;
        this.state.busy = true;
        try {
            const id = await this.ensureOrder();
            const kwargs = method === "action_add_from_catalog"
                ? { context: { ...this.props.record.context, child_field: "order_line", order_id: id } }
                : {};
            const result = await this.orm.call("sale.order", method, [[id], ...args], kwargs);
            if (open) {
                await this.action.doAction(result, { onClose: () => this.reloadRoot() });
            } else { await this.reloadRoot(); }
        } catch (error) { this.fail(error); }
        finally { if (!this.disposed) this.state.busy = false; }
    }
    async upload() { return this.execute("action_upload_drawing", [], true); }
    async configure(row) {
        if (row.source === "drawing" && row.drawing_id && !row.independent) {
            return this.execute("open_selection_row", [row.drawing_id, row.candidate_id || 0], true);
        }
        if (this.state.editing === row.key) {
            if (!await this.flush()) return;
            this.state.editing = "";
            if (this.needsReload) await this.reloadRoot();
        } else { this.state.editing = row.key; }
    }
    accessories(row) {
        const data = row.accessory_selection_data || {};
        const names = new Set([...(data.manual_names || []), ...Object.keys(data.choices || {})]);
        return [...names].map(name => ({ name, selected: data.choices?.[name] !== false }));
    }
    selectedAccessories(row) { return this.accessories(row).filter(item => item.selected).length; }
    widthValue(row){return row.width_expression ?? (row.width_mm || "");}
    async changeAllocations(row,data){
        row.accessory_selection_data=data;
        if(!await this.saveRow(row))throw Error(this.state.error || "附件保存失败，请重试。");
    }
    async addAccessories(row) {
        if (!this.editable || this.busy) return;
        if (!row.product_id) {
            this.notification.add("请先选择产品，再添加附件。", { type: "warning" }); return;
        }
        try {
            await this.saving;
            const orderId = await this.ensureOrder();
            this.closeAccessoryPicker = this.dialog.add(DrawingAccessoryPicker, {
                orderId, existingNames: this.accessories(row).map(item => item.name),
                selectedNames: this.accessories(row).filter(item => item.selected).map(item => item.name),
                onApply: async changes => {
                    if (this.disposed || !this.state.rows.includes(row)) throw Error("产品行已变化，请重新选择附件。");
                    const data = row.accessory_selection_data || {};
                    row.accessory_selection_data = { ...data, version: 1, candidate_id: 0,
                        allocations: data.allocations?.map(item => Object.hasOwn(changes, item.name)
                            ? { ...item, selected: changes[item.name] } : item),
                        manual_names: [...new Set([...(data.manual_names || []), ...Object.keys(changes)
                            .filter(name => changes[name] && !Object.hasOwn(data.choices || {}, name))])],
                        choices: { ...(data.choices || {}), ...changes } };
                    if (!await this.saveRow(row)) throw Error(this.state.error || "附件保存失败，请重试。");
                },
            });
        } catch (error) { this.fail(error); }
    }
    async recognize(row) {
        if (this.isRecognizing(row)) return;
        const run = () => this.execute("run_selection_recognition", [row.drawing_id]);
        if (["review", "done"].includes(row.recognition_state)) {
            this.dialog.add(ConfirmationDialog, { title: "重新识别图纸", body: "将重新读取这份图纸的全部产品，已保存的报价明细会保留。是否继续？", confirmLabel: "重新识别", confirm: run });
        } else { await run(); }
    }
    async copy(row) {
        if (!row.line_id) { this.notification.add("请先完成当前产品的选型并保存后再复制。", { type: "warning" }); return; }
        await this.execute("copy_selection_line", [row.line_id]);
    }
    remove(row) {
        if (!row.line_id && row.source === "manual") {
            this.state.rows = this.state.rows.filter(item => item.key !== row.key);
            this.pending.delete(row.key);
            if (!this.pending.size) this.state.error = "";
            return;
        }
        this.dialog.add(ConfirmationDialog, { title: "删除产品行", body: "将移除此产品行，底部的图纸附件会保留。", confirmLabel: "删除", confirm: () => {
            this.pending.delete(row.key);
            return this.execute("remove_selection_row", [row.line_id || 0, row.drawing_id || 0, row.candidate_id || 0]);
        } });
    }
    removeFile(file) {
        this.dialog.add(ConfirmationDialog, { title: "删除图纸附件", body: "将删除这份图纸及其待选型项目。已写入报价明细的产品会保留。", confirmLabel: "删除附件", confirm: () =>
            this.execute("remove_selection_attachment", [file.id]) });
    }
    async catalog() { return this.execute("action_add_from_catalog", [], true); }
    async retry() { for (const row of this.state.rows.filter(item => this.pending.has(item.key))) await this.saveRow(row); }
}
registry.category("fields").add("nodo_contract_quote_selection", {
    component: QuoteSelectionTable, supportedTypes: ["one2many"],
});

class SaleOrderFormRenderer extends saleOrderFormView.Renderer {
    async onWillChangeNotebookPage(...args) {
        const selection=quoteSelectionSessions.get(this.props.record);
        if(selection){
            if(!await selection.flush())return false;
            if(selection.needsReload)await selection.reloadRoot();
        }
        return super.onWillChangeNotebookPage(...args);
    }
}

class DrawingRecognitionFormController extends FormController {
    setup() {
        super.setup();
        this.drawingOrm = useService("orm");
        this.recognitionPolling = false;
        onMounted(() => {
            this.recognitionTimer = setInterval(() => this.refreshRecognition(), 3000);
        });
        onWillUnmount(() => clearInterval(this.recognitionTimer));
    }

    async refreshRecognition() {
        const record = this.model.root;
        if (quoteSelectionSessions.get(record)?.pollingBlocked || this.recognitionPolling || !record.resId ||
            !record.data.drawing_recognition_pending || await record.isDirty()) {
            return;
        }
        this.recognitionPolling = true;
        try {
            const progress = await this.drawingOrm.call(
                record.resModel, "get_drawing_recognition_progress", [[record.resId]]
            );
            if (this.model.root === record && !await record.isDirty() &&
                progress.version !== record.data.drawing_recognition_version) {
                await record.load();
            }
        } catch {
            // An interrupted request is retried while this form has pending work.
        } finally {
            this.recognitionPolling = false;
        }
    }

    async beforeExecuteActionButton(clickParams) {
        const record = this.model.root;
        const selectionTable = quoteSelectionSessions.get(record);
        if (selectionTable && !await selectionTable.flush()) return false;
        if (record.resModel === "nodo.contract.drawing" && clickParams.special !== "cancel") {
            for(const field of cabinetFieldSessions.get(record) || []){
                await field.saving;
                if(field.state.error)return false;
            }
            const assist = drawingDimensionSessions.get(record);
            if (assist) { await assist.reading; await assist.saving; }
            const accessories=drawingAccessorySessions.get(record);
            if (accessories) await accessories.flush();
        }
        if (record.resModel === "nodo.contract.drawing" && clickParams.special === "save") {
            const upload = drawingUploadSessions.get(record);
            if (upload) await upload.reading;
        }
        const localActions = ["action_apply_recognition", "action_recognize", "action_cancel_recognition"];
        if (record.resModel !== "nodo.contract.drawing" || !localActions.includes(clickParams.name)) {
            return super.beforeExecuteActionButton(clickParams);
        }
        if (await super.beforeExecuteActionButton(clickParams) === false) {
            return false;
        }
        await this.drawingOrm.call(record.resModel, clickParams.name, [[record.resId]]);
        await record.load();
        return false;
    }
}

registry.category("views").add("nodo_contract_sale_form", {
    ...saleOrderFormView,
    Renderer: SaleOrderFormRenderer,
    Controller: DrawingRecognitionFormController,
});

registry.category("views").add("nodo_contract_drawing_form", {
    ...formView,
    Controller: DrawingRecognitionFormController,
});

// These are the quotation client's verified presets. Keep the stored Char
// so existing drawing facts and manually entered grades remain readable.
class DrawingMaterialField extends SelectionField {
    setup() { super.setup(); this.type="selection"; }
    get options() {
        return parameterMaterials;
    }
}
registry.category("fields").add("nodo_contract_drawing_material",{
    ...selectionField,component:DrawingMaterialField,supportedTypes:["char"],
});

class DrawingDoorTypeField extends SelectionField {
    get value() { return super.value || false; }
    setup() { super.setup(); this.type = "selection"; }
    get options() {
        return cabinetDoorOptions(this.props.record.data.product_series).map(value => [value, value]);
    }
}
registry.category("fields").add("nodo_contract_drawing_door_type", {
    ...selectionField, component: DrawingDoorTypeField, supportedTypes: ["char"],
});

const drawingUploadSessions = new WeakMap();

class DrawingUploadField extends BinaryField {
    static template = "nodo_contract.DrawingUpload";
    inputRef = signal.ref();
    setup() {
        super.setup();
        this.state = proxy({loading:false,error:""});
        this.disposed = false;
        drawingUploadSessions.set(this.props.record,this);
        onWillUnmount(() => { this.disposed=true; drawingUploadSessions.delete(this.props.record); });
    }
    get files() { return this.props.record.data.upload_files || []; }
    select() { this.inputRef()?.click(); }
    onFiles(event) {
        const files = [...event.target.files];
        event.target.value = "";
        if (!files.length || this.state.loading) return;
        this.reading = this.readFiles(files);
    }
    async readFiles(files) {
        this.state.loading = true; this.state.error = "";
        try {
            const allowed = /\.(pdf|dwg|dxf|png|jpe?g|bmp|tiff?)$/i;
            for (const file of files) {
                if (!allowed.test(file.name)) throw Error(file.name+"：不支持此文件格式。");
                if (!file.size) throw Error(file.name+"：文件为空，请重新选择。");
                if (file.size > 24 * 1024 * 1024) throw Error(file.name + "：超过单文件 24 MB。");
                if (!checkFileSize(file.size,this.notification)) return;
            }
            const selected = [...this.files];
            for (const file of files) {
                const data = (await getDataURLFromFile(file)).split(",")[1];
                if (!selected.some(item=>item.name===file.name && item.content===data))
                    selected.push({name:file.name,content:data,size:file.size});
            }
            if (!checkFileSize(selected.reduce((sum,file)=>sum+(file.size || 0),0),this.notification)) return;
            if (!this.disposed) await this.setFiles(selected);
        } catch (error) {
            if (!this.disposed) this.state.error = error.message || "文件读取失败，请重新选择。";
        } finally { this.state.loading = false; }
    }
    async setFiles(files) {
        const first=files[0];
        await this.props.record.update({
            upload_files:files,
            name:first?.name || "",
            [this.props.name]: first ? {filename:first.name,content:first.content} : false,
        });
    }
    remove(index) {
        if (!this.state.loading) this.reading=this.setFiles(this.files.filter((_,i)=>i!==index));
    }
}
registry.category("fields").add("nodo_contract_drawing_upload",{...binaryField,component:DrawingUploadField});

const drawingAccessorySessions = new WeakMap();

class DrawingAccessoryPicker extends Component {
    static template="nodo_contract.DrawingAccessoryPicker";
    static components={Dialog};
    props=useProps({drawingId:t.number().optional(),orderId:t.number().optional(),existingNames:t.array(t.string()),
        selectedNames:t.array(t.string()),onApply:t.function(),close:t.function()});
    setup() {
        this.orm=useService("orm");
        this.state=proxy({items:[],query:"",category:"",picked:[...this.props.selectedNames],changes:{},
            loading:true,adding:false,error:""});
        this.disposed=false;
        onMounted(()=>this.load());
        onWillUnmount(()=>{this.disposed=true;});
    }
    async load() {
        this.state.loading=true;this.state.error="";
        try {
            const items=this.props.orderId
                ? await this.orm.call("sale.order","get_selection_accessory_catalog",[[this.props.orderId]])
                : await this.orm.call("nodo.contract.drawing","get_drawing_accessory_catalog",[[this.props.drawingId]]);
            if(!this.disposed)this.state.items=items;
        } catch {
            if(!this.disposed)this.state.error="附件库加载失败，请重试。";
        } finally {if(!this.disposed)this.state.loading=false;}
    }
    get items() {
        const query=this.state.query.trim().toLocaleLowerCase();
        return this.state.items.filter(item=>(!this.state.category || this.category(item)===this.state.category)
            && item.name.toLocaleLowerCase().includes(query));
    }
    category(item) {return (item.category || "附件").split(" / ")[0];}
    get categories() {return [...new Set(this.state.items.map(item=>this.category(item)))].sort((a,b)=>a.localeCompare(b,"zh-CN"));}
    get hasChanges() {return Object.keys(this.state.changes).length>0;}
    existing(name) {return this.props.existingNames.includes(name);}
    selected(name) {return this.state.picked.includes(name);}
    status(name) {
        if(Object.hasOwn(this.state.changes,name))return this.selected(name)?"待加入":"待取消";
        return this.existing(name)?(this.selected(name)?"已选用":"未选用"):"";
    }
    toggle(name,checked) {
        if(this.state.adding)return;
        this.state.picked=checked ? [...new Set([...this.state.picked,name])] : this.state.picked.filter(value=>value!==name);
        if(checked===this.props.selectedNames.includes(name))delete this.state.changes[name];
        else this.state.changes[name]=checked;
    }
    async add() {
        if(!this.hasChanges||this.state.adding)return;
        this.state.adding=true;this.state.error="";
        try {
            // Apply only edited names: untouched cabinet allocations and newly
            // arriving recognition matches keep their own saved selections.
            await this.props.onApply({...this.state.changes},this.state.items);
            if(!this.disposed)this.props.close();
        } catch(error) {
            if(!this.disposed)this.state.error=error.message || "添加失败，请重试。";
        } finally {if(!this.disposed)this.state.adding=false;}
    }
}

class DrawingAccessoriesField extends Component {
    static template = "nodo_contract.DrawingAccessories";
    static components={CabinetAllocations};
    props = useProps({...standardFieldProps});
    setup() {
        this.orm=useService("orm");this.dialog=useService("dialog");
        this.state=proxy({items:[],loading:true,pending:false,error:"",saving:false});
        this.saving=Promise.resolve();
        this.revision=0;this.disposed=false;this.overrides={};this.manualNames=new Set();
        drawingAccessorySessions.set(this.props.record,this);
        useOnChange(()=>[this.candidate,this.props.record.data.recognition_token,
            JSON.stringify(this.props.record.data[this.props.name] || {})],()=>{
            const context=this.candidate+":"+this.props.record.data.recognition_token;
            if(this.context!==context)this.state.items=[];
            this.context=context;this.overrides={};
            this.manualNames=new Set(this.saved.manual_names || []);
            this.refresh();
        });
        this.timer=setInterval(()=>{if(this.state.pending&&!this.state.loading)this.refresh();},3000);
        onWillUnmount(()=>{
            this.disposed=true;this.revision++;clearInterval(this.timer);this.closePicker?.();
            drawingAccessorySessions.delete(this.props.record);
        });
    }
    get candidate() { return this.props.record.data.active_recognition_id?.id || 0; }
    get saved() {
        const saved=this.props.record.data[this.props.name] || {};
        return saved.candidate_id===this.candidate ? saved : {};
    }
    get decisions() { return this.saved.choices || {}; }
    get selectionValues(){return {...this.props.record.data,accessory_selection_data:this.saved};}
    get hasAllocations(){return !!this.saved.allocations?.length;}
    get candidateItems() {
        const allocated = new Set((this.saved.allocations || []).map(item => item.name));
        return this.state.items.filter(item => !allocated.has(item.name));
    }
    get evidence() {
        return Object.fromEntries(this.state.items.map(item => [item.name, item]));
    }
    async changeAllocations(data){await this.props.record.update({[this.props.name]:data});}
    get selectedCount() { return this.state.items.filter(item=>this.selected(item.name)).length; }
    selected(name) {
        return this.overrides[name] ?? this.decisions[name] ?? this.state.items.find(item => item.name === name)?.selected ?? false;
    }
    async refresh() {
        const revision=++this.revision,candidate=this.candidate;
        this.state.loading=true;
        this.loadingPromise=(async()=>{
            try {
                const result=await this.orm.call("nodo.contract.drawing","get_drawing_accessories",
                    [[this.props.record.resId],candidate,[...this.manualNames]]);
                if(this.disposed||revision!==this.revision||candidate!==this.candidate)return;
                this.state.items=result.items;this.state.pending=result.pending;this.state.error="";
            } catch {
                if(!this.disposed&&revision===this.revision){this.state.error="附件匹配未完成，正在重试…";this.state.pending=true;}
            } finally {
                if(!this.disposed&&revision===this.revision)this.state.loading=false;
            }
        })();
        await this.loadingPromise;
    }
    toggle(name,checked) {
        if(this.props.readonly)return;
        this.overrides[name]=checked;
        return this.flush();
    }
    async openPicker() {
        if(this.props.readonly||this.disposed)return;
        await this.loadingPromise;
        if(this.props.readonly||this.disposed)return;
        const candidate=this.candidate;
        const names=[...new Set([...this.state.items.map(item=>item.name),...Object.keys(this.decisions),
            ...this.manualNames,...(this.saved.allocations || []).map(item=>item.name)])];
        this.closePicker=this.dialog.add(DrawingAccessoryPicker,{
            drawingId:this.props.record.resId,existingNames:names,selectedNames:names.filter(name=>this.selected(name)),
            onApply:async (changes,catalog)=>{
                if(this.disposed || candidate && candidate!==this.candidate)
                    throw Error("识别项目已变化，请重新打开附件选择。");
                await this.loadingPromise;
                const known=new Set(this.state.items.map(item=>item.name));
                Object.assign(this.overrides,changes);
                for(const [name,checked] of Object.entries(changes)) {
                    if(!checked||known.has(name))continue;
                    const item=catalog.find(item=>item.name===name);
                    if(!item)continue;
                    this.manualNames.add(name);known.add(name);
                    this.state.items.push({...item,source:"manual",selected:true});
                }
                await this.flush();
            },
        });
    }
    removeManual(name) {
        if(this.props.readonly||this.state.saving)return;
        this.manualNames.delete(name);this.overrides[name]=false;
        this.state.items=this.state.items.filter(item=>item.name!==name);
        return this.flush();
    }
    async flush() {
        if(this.props.readonly||this.disposed)return;
        await this.loadingPromise;
        if(this.disposed||this.state.error)return;
        const choices={...this.decisions,...this.overrides};
        const value={...this.saved,version:1,candidate_id:this.candidate,choices,manual_names:[...this.manualNames]};
        if(Array.isArray(value.allocations))value.allocations=value.allocations.map(item=>
            Object.hasOwn(this.overrides,item.name)?{...item,selected:this.overrides[item.name]}:item);
        this.state.saving=true;
        this.saving=this.saving.then(()=>this.props.record.update({[this.props.name]:value}))
            .finally(()=>{this.state.saving=false;});
        return this.saving;
    }
}
registry.category("fields").add("nodo_contract_drawing_accessories",{
    component:DrawingAccessoriesField,supportedTypes:["json"],
});

const drawingDimensionSessions = new WeakMap();
const dimensionAxes = [
    { key: "width_mm", label: "宽度", role: "front", direction: "horizontal" },
    { key: "depth_mm", label: "深度", role: "side", direction: "horizontal" },
    { key: "height_mm", label: "高度", role: "front", direction: "vertical" },
];
const drawingViewLabels = { front: "正视图", side: "侧视图" };

function rotateDrawingRect(rect, angle) {
    const [x,y,w,h] = rect;
    angle = (angle+360)%360;
    if (angle === 90) return [1-y-h,x,h,w];
    if (angle === 180) return [1-x-w,1-y-h,w,h];
    if (angle === 270) return [y,1-x-w,h,w];
    return rect;
}

function evidenceMagnification(width, height, pageWidth, pageHeight, rect) {
    return Math.max(1, Math.min(1.7, (width - 40) / (pageWidth * rect[2]),
        (height - 40) / (pageHeight * rect[3])));
}

function evidenceCenter(point, pageSpan, viewportSpan) {
    const margin = Math.max(0, Math.min(.5, (viewportSpan / 2 - 14) / pageSpan));
    return Math.max(margin, Math.min(1 - margin, point));
}

function drawingDimensionSession(record, orm) {
    if (drawingDimensionSessions.has(record)) {
        return drawingDimensionSessions.get(record);
    }
    const clone = (value) => JSON.parse(JSON.stringify(value));
    const session = {
        record, orm, axes: dimensionAxes, listeners: new Set(), navigators: new Set(), history: [], request: 0,
        pendingUpdates: 0, clients: 0, contextCandidate: record.data.active_recognition_id?.id || 0,
        saving: Promise.resolve(), orientationLoads: new Map(), orientationAngles: new Map(),
        state: proxy({ boxes: {}, values: {}, chosen: {}, busy: false, error: "", applied: false,
            heightReviewed: false, focus: null, focusToken: null, orienting: false,
            pane: "results", tool: null, viewerReady: false, pendingSelection: null }),
        get editable() { return Boolean(record.data.can_edit_selection); },
        get candidate() { return record.data.active_recognition_id?.id || 0; },
        get canView() { return this.state.viewerReady && !this.state.orienting; },
        get canFrame() {
            return this.editable && this.canView && !this.state.busy
                && !this.vision.state.saving;
        },
        get activeTool() { return this.state.tool; },
        get heightCheck() {
            const box = this.state.boxes.side;
            return box?.tokens.find((token) => token.id === box.vertical)?.value;
        },
        get conflict() {
            return this.heightCheck && this.state.values.height_mm &&
                Math.abs(this.heightCheck - this.state.values.height_mm) > 0.01;
        },
        get hint() {
            if (!this.state.viewerReady || this.state.orienting) return "正在准备原图…";
            if (this.state.busy) return `正在读取${drawingViewLabels[this.state.pendingSelection?.role] || "选区"}…`;
            if (this.state.tool) return `拖动框选${drawingViewLabels[this.state.tool]}，包含尺寸标注`;
            return "";
        },
        choosePane(pane) {
            this.state.pane = pane;
        },
        chooseTool(role) {
            if (!this.canFrame) return;
            const tool = this.state.tool === role ? null : role;
            this.vision.state.focus = null;
            this.state.tool = tool;
            this.state.error = "";
            if (tool) this.choosePane("results");
            this.emit();
        },
        cancelTool() {
            if (!this.activeTool || this.vision.state.saving) return false;
            this.state.tool = null;
            this.state.error = "";
            this.emit();
            return true;
        },
        fit() {
            this.fitPreview?.();
            this.emit();
        },
        rotate(angle) {
            if (this.canView) this.rotatePreview?.(angle);
        },
        zoom(step) {
            if (this.canView) this.zoomPreview?.(step);
        },
        orientation(page) {
            const cached = record.data.orientation_data?.pages?.[String(page)];
            if (cached) { this.orientationAngles.set(page,cached.angle || 0); return Promise.resolve(cached); }
            const key = `${record.data.name}:${record.data.orientation_token}:${page}`;
            if (!this.orientationLoads.has(key)) {
                this.orientationLoads.set(key, (async () => {
                    while (this.clients) {
                        const result = await orm.call("nodo.contract.drawing", "get_drawing_orientation", [[record.resId],page]);
                        if (!["queued","processing"].includes(result.state)) {
                            this.orientationAngles.set(page,result.angle || 0); return result;
                        }
                        await new Promise(resolve => setTimeout(resolve,1000));
                    }
                    return {angle:null};
                })().catch(() => ({angle:null})));
            }
            return this.orientationLoads.get(key);
        },
        snapshot() {
            return clone({ version: 1, direct: true, candidate_id: this.candidate, boxes: this.state.boxes,
                values: this.state.values, chosen: this.state.chosen, heightRole: this.state.heightRole });
        },
        emit() { for (const listener of this.listeners) listener(); },
        remember() { this.history.push(this.snapshot()); if (this.history.length > 20) this.history.shift(); },
        restore(value, useSnapshot = false) {
            if (this.contextCandidate !== this.candidate) this.state.tool = null;
            this.contextCandidate = this.candidate;
            const data = value?.version === 1 && value.candidate_id === this.candidate ? value : {};
            this.state.boxes = clone(data.boxes || {});
            this.state.values = Object.fromEntries(dimensionAxes.map((axis) => [axis.key,
                useSnapshot ? Number(data.values?.[axis.key]) || 0 : Number(record.data[axis.key]) || 0]));
            this.state.chosen = clone(data.chosen || {});
            this.state.heightRole = data.heightRole || "front";
            for (const axis of dimensionAxes) {
                if (this.state.values[axis.key] !== data.values?.[axis.key]) this.state.chosen[axis.key] = "";
            }
            this.state.error = ""; this.state.focus = null; this.state.focusToken = null;
            this.emit();
        },
        persist(updateDimensions = true) {
            const data = this.snapshot();
            const dimensions = updateDimensions ? clone(this.state.values) : {};
            if(cabinetRows(record.data).length>1)delete dimensions.width_mm;
            this.pendingUpdates++;
            this.saving = this.saving.then(() => record.update({ ...dimensions, dimension_assist_data: data })).catch(() => {
                this.state.error = "尺寸复核记录未保存，请重试。";
            }).finally(() => { this.pendingUpdates--; });
            this.emit();
            return this.saving;
        },
        token(axis) {
            return this.state.boxes[this.role(axis)]?.tokens.find((item) => item.id === this.state.chosen[axis.key]);
        },
        role(axis) { return axis.key === "height_mm" ? this.state.heightRole || "front" : axis.role; },
        options(axis) {
            return this.state.boxes[this.role(axis)]?.tokens.filter((item) => item.axis ===
                (axis.direction === "horizontal" ? "horizontal" : "vertical") &&
                (!item.dimension_key || item.dimension_key === axis.key ||
                    (axis.key === "height_mm" && ["total_height", "cabinet_height"].includes(item.dimension_key)))) || [];
        },
        source(axis) {
            const role = this.role(axis), token = this.token(axis), box = this.state.boxes[role];
            if (!token || !box) return this.state.values[axis.key] ? "手工填写" : "尚未读取";
            return `第 ${box.page} 页 · ${role === "front" ? "正视图" : "侧视图"} · ${token.text}`;
        },
        readRole(role) {
            const box = this.state.boxes[role];
            for (const axis of dimensionAxes.filter((axis) => axis.role === role)) {
                const token = box?.tokens.find((item) => item.id === box[axis.direction]);
                if (token && (!token.dimension_key || token.dimension_key === axis.key)) {
                    this.state.values[axis.key] = token.value;
                    this.state.chosen[axis.key] = token.id;
                    if (axis.key === "height_mm") this.state.heightRole = "front";
                } else if (axis.key !== "height_mm" || this.state.heightRole !== "side") {
                    if (this.state.chosen[axis.key]) this.state.values[axis.key] = 0;
                    this.state.chosen[axis.key] = "";
                }
            }
            const side = this.state.boxes.side;
            const sideHeight = side?.tokens.find((token) => token.id === side.vertical);
            const front = this.state.boxes.front;
            const frontHeight = front?.tokens.find((token) => token.id === front.vertical);
            if (!frontHeight && sideHeight && (!this.state.values.height_mm || this.state.heightRole === "side")) {
                this.state.values.height_mm = sideHeight.value;
                this.state.chosen.height_mm = sideHeight.id;
                this.state.heightRole = "side";
            } else if (!side && this.state.heightRole === "side") {
                this.state.values.height_mm = 0; this.state.chosen.height_mm = ""; this.state.heightRole = "front";
            }
        },
        select(role, page, rect, rotation, orientation = 0) {
            this.reading = this.selectRect(role, page, rect, rotation, orientation);
            return this.reading;
        },
        async selectRect(role, page, rect, rotation, orientation = 0) {
            if (!this.canFrame || !drawingViewLabels[role]) return;
            const point = [rect[0]+rect[2]/2,rect[1]+rect[3]/2];
            const revision = ++this.request, candidate = this.candidate;
            this.state.busy = true; this.state.error = "";
            this.state.pendingSelection = {role,page,rotation,regions:[rect],regionIndex:0}; this.emit();
            try {
                const result = await orm.call("nodo.contract.drawing", "get_dimension_view",
                    [[record.resId], page, point, rotation, orientation, rect]);
                if (revision !== this.request || candidate !== this.candidate) return;
                const previous = this.state.boxes.front || this.state.boxes.side;
                if (previous && previous.file_sha256 !== result.file_sha256) {
                    throw new Error("原图已变化，请清除选区后重新框选。");
                }
                this.remember();
                this.state.boxes[role] = { ...result, regionIndex: 0 };
                this.readRole(role); this.state.focus = role; this.state.focusToken = null;
                this.state.tool = this.state.tool === "front" && role === "front" && !this.state.boxes.side ? "side" : null;
                await this.persist();
            } catch (error) {
                if (revision === this.request) this.state.error = error.data?.message || error.message || "读取未完成，请重新框选。";
            } finally {
                if (revision === this.request) { this.state.busy = false; this.state.pendingSelection = null; this.emit(); }
            }
        },
        remove(role) {
            if (!this.editable || this.state.busy) return;
            this.remember(); delete this.state.boxes[role]; this.readRole(role);
            this.state.error = ""; this.state.focusToken = null; this.persist();
        },
        undo() {
            if (!this.editable || this.state.busy || !this.history.length) return;
            this.restore(this.history.pop(), true); this.persist();
        },
        clear() {
            if (!this.editable || this.state.busy) return;
            this.remember(); this.restore(null); this.persist();
        },
        swap() {
            if (!this.editable || this.state.busy) return;
            this.remember();
            [this.state.boxes.front, this.state.boxes.side] = [this.state.boxes.side, this.state.boxes.front];
            this.readRole("front"); this.readRole("side"); this.state.focusToken = null; this.persist();
        },
        edit(axis, value, id = "", role = this.role(axis)) {
            if (!this.editable || this.state.busy) return;
            this.remember(); this.state.values[axis.key] = Number(value) || 0;
            if (axis.key === "height_mm") this.state.heightRole = role;
            this.state.chosen[axis.key] = id; this.persist();
        },
        focus(axis) {
            this.focusDimension(this.role(axis), this.token(axis));
        },
        focusDimension(role, token) {
            this.vision.state.focus = null;
            this.state.focus = role; this.state.focusToken = token?.id || null;
            const box = this.state.boxes[role];
            if (box) {
                this.revealPreview?.();
                for (const navigate of this.navigators) navigate(box, token);
            }
            this.emit();
        },
    };
    session.vision = new DrawingVisionSession(session);
    session.restore(record.data.dimension_assist_data);
    drawingDimensionSessions.set(record, session);
    return session;
}

class DrawingDimensionsField extends Component {
    static template = "nodo_contract.DrawingDimensions";
    static components = { Dropdown, DropdownItem };
    props = useProps({ ...standardFieldProps, toolbar: t.boolean().optional(false) });
    toolbarRef = signal.ref();
    setup() {
        this.assist = drawingDimensionSession(this.props.record, useService("orm"));
        this.views = Object.entries(drawingViewLabels).map(([key, label]) => ({ key, label }));
        const revealPreview = () => this.toolbarRef()?.closest(".o_sale_drawing_preview")?.scrollIntoView({
            block: "nearest", inline: "nearest",
        });
        this.assist.revealPreview = revealPreview;
        useOnChange(() => [this.toolbarRef()], (toolbar) => {
            const modal = toolbar?.closest(".modal-content");
            if (!modal) return;
            const exitDrawingTool = (event) => {
                if (event.key !== "Escape" || !this.assist.cancelTool()) return;
                event.preventDefault();
                event.stopPropagation();
            };
            modal.addEventListener("keydown", exitDrawingTool, true);
            return () => modal.removeEventListener("keydown", exitDrawingTool, true);
        });
        this.assist.clients++;
        onWillUnmount(() => {
            if (this.assist.revealPreview === revealPreview) this.assist.revealPreview = null;
            if (--this.assist.clients === 0) { this.assist.request++; this.assist.state.busy = false; }
        });
        this.axes = dimensionAxes;
        useOnChange(() => dimensionAxes.map((axis) => this.props.record.data[axis.key]), () => {
            if (this.assist.pendingUpdates || this.assist.candidate !== this.assist.contextCandidate) return;
            let changed = false;
            for (const axis of dimensionAxes) {
                const value = Number(this.props.record.data[axis.key]) || 0;
                if (this.assist.state.values[axis.key] !== value) {
                    this.assist.state.values[axis.key] = value;
                    this.assist.state.chosen[axis.key] = ""; changed = true;
                    if (axis.key === "height_mm") this.assist.state.heightRole = "front";
                }
            }
            if (changed && this.assist.editable) this.assist.persist(false);
        });
        useOnChange(() => [this.props.record.data.active_recognition_id?.id,
            this.props.record.data.dimension_assist_data], () => {
            const saved = this.props.record.data.dimension_assist_data;
            if (this.assist.pendingUpdates && this.assist.candidate === this.assist.contextCandidate) return;
            if (JSON.stringify(saved || {}) !== JSON.stringify(this.assist.snapshot())) {
                this.assist.request++; this.assist.state.busy = false;
                this.assist.restore(saved); this.assist.history = [];
            }
        });
    }
}

class DrawingDimensionValueField extends FloatField {
    static template = "nodo_contract.DrawingDimensionValue";
    setup() {
        super.setup();
        this.assist = drawingDimensionSession(this.props.record, useService("orm"));
        this.axis = dimensionAxes.find((axis) => axis.key === this.props.name);
    }
    onOption(event) {
        const token = this.assist.options(this.axis).find((token) => token.id === event.target.value);
        if (token) this.assist.edit(this.axis, token.value, token.id);
    }
}

class DrawingVisionField extends Component {
    static template = "nodo_contract.DrawingVision";
    props = useProps({ ...standardFieldProps });

    setup() {
        this.assist = drawingDimensionSession(this.props.record, useService("orm"));
        this.vision = this.assist.vision;
        useOnChange(() => [this.props.record.data.active_recognition_id?.id,
            this.props.record.data.recognition_token], () => {
            this.vision.reset();
            this.vision.refresh();
        });
        const timer = setInterval(() => {
            if (this.vision.active && !this.vision.state.saving) this.vision.refresh();
        }, 900);
        onWillUnmount(() => { clearInterval(timer); this.vision.reset(); });
    }
}

class DrawingSectionsField extends Component {
    static template = "nodo_contract.DrawingSections";
    static components = { Dropdown, DropdownItem };
    props = useProps({ ...standardFieldProps });
    setup() {
        this.assist = drawingDimensionSession(this.props.record, useService("orm"));
    }
    get panes() {
        const panes = [{ key: "parameters", label: "参数" }];
        if (this.props.record.data.file_kind === "pdf") {
            panes.push({ key: "vision", label: "识图记录" });
        }
        panes.push({ key: "accessories", label: "附件与要求" });
        return panes;
    }
}

class DrawingResultsField extends Component {
    static template = "nodo_contract.DrawingResults";
    props = useProps({ ...standardFieldProps });

    setup() {
        this.assist = drawingDimensionSession(this.props.record, useService("orm"));
        this.groups = specificationGroups;
        this.format = specificationValue;
        this.state = proxy({ key: "", option: "" });
        useOnChange(() => [this.assist.candidate, this.props.record.data.recognition_token], () => {
            this.state.key = "";
            this.state.option = "";
        });
    }

    get entries() { return drawingSpecifications(this.assist); }

    resultLabel(field) {
        const current = this.format(field.value);
        const values = field.conflict
            ? ["图纸", field.candidate, field.candidateUnit, "现值", current, field.unit]
            : [current, current && field.unit];
        return [field.label, ...values, field.statusLabel].filter(Boolean).join(" ");
    }

    activate(event) {
        const key = event.currentTarget.dataset.field;
        const field = this.entries[key];
        this.state.key = key;
        this.selectEvidence(field.evidence);
    }

    selectEvidence(option) {
        this.state.option = option?.key || "";
        if (option?.item) this.assist.vision.focus(option.run, option.item);
        else if (option?.token) this.assist.focusDimension(option.role, option.token);
        else {
            this.assist.state.focusToken = null;
            this.assist.vision.state.focus = null;
            this.assist.emit();
        }
    }

    activeEvidence(field) {
        return field.options.find((option) => option.key === this.state.option) || field.evidence;
    }

    optionLabel(field, option) {
        const value = this.format(option.value);
        if (field.key === "height_mm") return [option.label, value, option.unit].filter(Boolean).join(" ");
        return value ? [value, option.unit].filter(Boolean).join(" ") : option.label;
    }

    apply(field, option) {
        if (option.item) {
            const choice = this.assist.vision.canConfirmMillimetres(option.item) ? "apply_mm" : "apply";
            return this.assist.vision.confirm(option.run, option.item, choice);
        }
        const axis = dimensionAxes.find((entry) => entry.key === field.key);
        if (!axis || !this.assist.editable || this.assist.state.busy) return;
        this.assist.edit(axis, option.value, option.token.id, option.role);
    }
}

registry.category("fields").add("nodo_contract_drawing_results", {
    component: DrawingResultsField, supportedTypes: ["integer"],
});

registry.category("fields").add("nodo_contract_drawing_sections", {
    component: DrawingSectionsField, supportedTypes: ["integer"],
});

registry.category("fields").add("nodo_contract_drawing_vision", {
    component: DrawingVisionField, supportedTypes: ["selection"],
});

registry.category("fields").add("nodo_contract_drawing_dimension_value", {
    ...floatField, component: DrawingDimensionValueField,
});

registry.category("fields").add("nodo_contract_drawing_dimensions", {
    component: DrawingDimensionsField, supportedTypes: ["json"],
    extractProps: ({ options }) => ({ toolbar: Boolean(options.toolbar) }),
});

function bindDrawingDimensionSelection(surface, currentPage, assist, navigate) {
    const doc = surface.ownerDocument, view = doc.defaultView;
    const preview = surface.closest(".o_sale_drawing_preview") || view.frameElement?.closest(".o_sale_drawing_preview");
    const theme = preview?.ownerDocument.defaultView.getComputedStyle(preview);
    const ink = theme?.getPropertyValue("--nodo-drawing-ink").trim() || "currentColor";
    const fill = theme?.getPropertyValue("--nodo-drawing-fill").trim() || "transparent";
    const evidenceInk = theme?.getPropertyValue("--nodo-drawing-evidence").trim() || ink;
    const evidenceFill = theme?.getPropertyValue("--nodo-drawing-evidence-fill").trim() || fill;
    const abort = new view.AbortController(), options = { signal: abort.signal, capture: true };
    const style = doc.createElement("style");
    style.textContent = `.o_drawing_manual_select .page,.o_drawing_manual_select img{cursor:crosshair;user-select:none}
        .o_drawing_dimension_overlay{position:absolute;pointer-events:none;z-index:12;inset:0}
        .o_drawing_dimension_region{position:absolute;border:1.5px dashed ${ink};background:${fill};box-sizing:border-box}
        .o_drawing_dimension_region[data-role=side]{border-style:dotted;border-width:2px}
        .o_drawing_dimension_region[data-focus=true]{border-style:solid}
        .o_drawing_dimension_tag{position:absolute;left:-1px;top:0;background:white;color:${ink};white-space:nowrap;font:600 12px/24px system-ui,sans-serif;padding:0 6px;border:1px solid ${ink};border-radius:0 0 4px 0;pointer-events:auto}
        .o_drawing_manual_select .o_drawing_dimension_tag{pointer-events:none}
        .o_drawing_dimension_tag button{border:0;background:transparent;color:inherit;font:inherit;padding:0 5px;cursor:pointer}
        .o_drawing_dimension_evidence{position:absolute;border:2px solid ${evidenceInk};box-sizing:border-box;background:${evidenceFill}}`;
    doc.head.appendChild(style);
    const overlay = doc.createElement("div"); overlay.className = "o_drawing_dimension_overlay";
    let pointer = null, frame, disposed = false;
    const selection = doc.createElement("div"); selection.className = "o_drawing_dimension_region";
    selection.style.borderStyle = "solid";
    function dragRect(event) {
        if (!pointer) return null;
        const r = pointer.element.getBoundingClientRect();
        const u = Math.max(0,Math.min(1,(event.clientX-r.left)/r.width));
        const v = Math.max(0,Math.min(1,(event.clientY-r.top)/r.height));
        return [Math.min(pointer.u,u),Math.min(pointer.v,v),Math.abs(u-pointer.u),Math.abs(v-pointer.v)];
    }
    function render() {
        if (disposed) return;
        surface.classList.toggle("o_drawing_manual_select", Boolean(assist.activeTool) && assist.canFrame);
        const page = currentPage();
        if (!page?.element?.isConnected) { overlay.remove(); return; }
        if (page.element.tagName === "IMG") {
            if (overlay.parentElement !== surface) surface.appendChild(overlay);
            const r = page.element.getBoundingClientRect(), s = surface.getBoundingClientRect();
            Object.assign(overlay.style, { left: `${r.left-s.left}px`, top: `${r.top-s.top}px`,
                width: `${r.width}px`, height: `${r.height}px`, right: "auto", bottom: "auto" });
        } else if (overlay.parentElement !== page.element) page.element.appendChild(overlay);
        overlay.replaceChildren();
        const focus = assist.vision.state.focus;
        if (focus?.page === page.page) {
            const r = rotateDrawingRect(focus.rect, page.rotation - focus.rotation);
            const mark = doc.createElement("div");
            mark.className = "o_drawing_dimension_evidence";
            Object.assign(mark.style, { left: `${r[0] * 100}%`, top: `${r[1] * 100}%`,
                width: `${r[2] * 100}%`, height: `${r[3] * 100}%` });
            overlay.appendChild(mark);
        }
        if (pointer?.rect) {
            const r=pointer.rect;
            Object.assign(selection.style,{left:`${r[0]*100}%`,top:`${r[1]*100}%`,width:`${r[2]*100}%`,height:`${r[3]*100}%`});
            selection.dataset.role = pointer.role;
            overlay.appendChild(selection);
        }
        for (const role of ["front", "side"]) {
            const pending = assist.state.pendingSelection?.role === role;
            const box = pending ? assist.state.pendingSelection : assist.state.boxes[role];
            if (!box || box.page !== page.page) continue;
            const r = rotateDrawingRect(box.regions[box.regionIndex || 0],page.rotation-box.rotation);
            if (!r) continue;
            const region = doc.createElement("div"); region.className = "o_drawing_dimension_region";
            region.dataset.role = role; region.dataset.focus = String(assist.state.focus === role);
            Object.assign(region.style, { left: `${r[0]*100}%`, top: `${r[1]*100}%`,
                width: `${r[2]*100}%`, height: `${r[3]*100}%` });
            const tag = doc.createElement("span"); tag.className = "o_drawing_dimension_tag";
            tag.append(doc.createTextNode(drawingViewLabels[role] + " "));
            if (!pending && assist.editable && !assist.state.busy && !assist.activeTool) {
                const remove = doc.createElement("button"); remove.type = "button"; remove.textContent = "×";
                remove.setAttribute("aria-label", role === "front" ? "取消正视图" : "取消侧视图");
                remove.addEventListener("click", (event) => { event.stopPropagation(); assist.remove(role); });
                tag.appendChild(remove);
            }
            region.appendChild(tag); overlay.appendChild(region);
            if (assist.state.focus === role && assist.state.focusToken) {
                const token = box.tokens?.find((item) => item.id === assist.state.focusToken);
                if (token) {
                    const evidence = doc.createElement("div"); evidence.className = "o_drawing_dimension_evidence";
                    const r = rotateDrawingRect(token.rect,page.rotation-box.rotation);
                    Object.assign(evidence.style, { left: `${r[0]*100}%`, top: `${r[1]*100}%`,
                        width: `${r[2]*100}%`, height: `${r[3]*100}%` }); overlay.appendChild(evidence);
                }
            }
        }
    }
    function schedule() { view.cancelAnimationFrame(frame); frame = view.requestAnimationFrame(render); }
    surface.addEventListener("pointerdown", (event) => {
        const role = assist.activeTool;
        if (event.button !== 0 || !role || !assist.canFrame) return;
        const page = currentPage(); if (!page?.element) return;
        const r = page.element.getBoundingClientRect();
        const u=(event.clientX-r.left)/r.width,v=(event.clientY-r.top)/r.height;
        if (![u,v].every(value=>Number.isFinite(value)&&value>=0&&value<=1)) return;
        pointer = {u,v,x:event.clientX,y:event.clientY,id:event.pointerId,role,...page};
        surface.setPointerCapture(event.pointerId);
        event.preventDefault();event.stopPropagation();
    }, options);
    surface.addEventListener("pointermove", (event) => {
        if (!pointer || event.pointerId!==pointer.id) return;
        pointer.rect=dragRect(event);schedule();event.preventDefault();event.stopPropagation();
    }, options);
    surface.addEventListener("pointerup", (event) => {
        if (!pointer || event.button!==0 || event.pointerId!==pointer.id) return;
        const start=pointer,rect=dragRect(event);pointer=null;
        if (surface.hasPointerCapture(event.pointerId)) surface.releasePointerCapture(event.pointerId);
        event.preventDefault();event.stopPropagation();schedule();
        if (Math.hypot(event.clientX-start.x,event.clientY-start.y)<8 || rect[2]<.005 || rect[3]<.005) return;
        if (start.role !== assist.activeTool) return;
        assist.select(start.role,start.page,rect,start.rotation,start.orientation || 0);
    }, options);
    const cancel = () => { pointer=null;schedule(); };
    surface.addEventListener("pointercancel",cancel,options);
    surface.addEventListener("lostpointercapture",cancel,options);
    view.addEventListener("blur",cancel,{signal:abort.signal});
    doc.addEventListener("keydown", (event) => {
        if (event.key !== "Escape") return;
        const exitingTool = assist.cancelTool();
        if (!pointer && !exitingTool) return;
        event.preventDefault();
        event.stopPropagation();
        const id = pointer?.id;
        cancel();
        if (id != null && surface.hasPointerCapture(id)) surface.releasePointerCapture(id);
    }, options);
    for (const name of ["scroll", "wheel", "pointermove"]) surface.addEventListener(name, schedule, { signal: abort.signal, passive: true });
    const resize = new view.ResizeObserver(schedule); resize.observe(surface);
    const image = surface.querySelector("img");
    const mutation = image ? new view.MutationObserver(schedule) : null;
    mutation?.observe(image, { attributes: true, attributeFilter: ["style", "src"] });
    assist.listeners.add(schedule); render();
    if (navigate) assist.navigators.add(navigate);
    return { render: schedule, destroy() {
        disposed = true; abort.abort(); resize.disconnect(); mutation?.disconnect();
        surface.classList.remove("o_drawing_manual_select");
        assist.listeners.delete(schedule); view.cancelAnimationFrame(frame); overlay.remove(); style.remove();
        if (navigate) assist.navigators.delete(navigate);
    } };
}


const DRAWING_GESTURES = {
    minScale: 0.1,
    maxScale: 8,
    wheelStep: 1.15,
    pixelsPerStep: 100,
    doubleClickMs: 500,
    clickTolerance: 5,
};

function bindDrawingMouseControls(surface, controls) {
    const view = surface.ownerDocument.defaultView;
    const abort = new view.AbortController();
    const options = { signal: abort.signal, capture: true };
    let drag = null;
    let lastClick = null;

    function finishDrag(event, cancelled = false) {
        if (!drag) {
            return;
        }
        const previous = drag;
        drag = null;
        surface.classList.remove("o_drawing_pan_active");
        if (surface.hasPointerCapture(previous.pointerId)) {
            surface.releasePointerCapture(previous.pointerId);
        }
        lastClick = !cancelled && !previous.moved
            ? { time: view.performance.now(), x: event.clientX, y: event.clientY }
            : null;
    }

    surface.addEventListener("wheel", (event) => {
        if (!event.deltaY) {
            return;
        }
        event.preventDefault();
        event.stopImmediatePropagation();
        const unit = event.deltaMode === 1 ? 40 : event.deltaMode === 2 ? surface.clientHeight : 1;
        const pixels = Math.max(-300, Math.min(300, event.deltaY * unit));
        controls.zoom(Math.exp(-pixels * Math.log(DRAWING_GESTURES.wheelStep) /
            DRAWING_GESTURES.pixelsPerStep), event.clientX, event.clientY);
    }, { ...options, passive: false });

    surface.addEventListener("pointerdown", (event) => {
        if (event.button !== 1) {
            return;
        }
        event.preventDefault();
        event.stopImmediatePropagation();
        if (lastClick && view.performance.now() - lastClick.time <= DRAWING_GESTURES.doubleClickMs &&
            Math.hypot(event.clientX - lastClick.x, event.clientY - lastClick.y) <= DRAWING_GESTURES.clickTolerance) {
            lastClick = null;
            controls.fit();
            return;
        }
        drag = {
            pointerId: event.pointerId,
            startX: event.clientX, startY: event.clientY,
            x: event.clientX, y: event.clientY, moved: false,
        };
        controls.startPan?.();
        surface.setPointerCapture(event.pointerId);
        surface.classList.add("o_drawing_pan_active");
    }, options);

    surface.addEventListener("pointermove", (event) => {
        if (!drag) {
            return;
        }
        if (!(event.buttons & 4)) {
            finishDrag(event, true);
            return;
        }
        event.preventDefault();
        event.stopImmediatePropagation();
        drag.moved ||= Math.hypot(event.clientX - drag.startX, event.clientY - drag.startY) >
            DRAWING_GESTURES.clickTolerance;
        controls.pan(event.clientX - drag.x, event.clientY - drag.y);
        drag.x = event.clientX;
        drag.y = event.clientY;
    }, options);

    surface.addEventListener("pointerup", (event) => finishDrag(event), options);
    surface.addEventListener("pointercancel", (event) => finishDrag(event, true), options);
    surface.addEventListener("lostpointercapture", (event) => finishDrag(event, true), options);
    surface.addEventListener("auxclick", (event) => {
        if (event.button === 1) {
            event.preventDefault();
            event.stopImmediatePropagation();
        }
    }, options);
    view.addEventListener("blur", (event) => finishDrag(event, true), { signal: abort.signal });

    return {
        get dragging() { return Boolean(drag); },
        destroy() {
            finishDrag({}, true);
            abort.abort();
        },
    };
}

function bindDrawingPdfOrientation(application, assist, mouse, render) {
    const viewer = application.pdfViewer;
    const manual = new Map();
    const oriented = new Set();
    let revision = 0, disposed = false, applying = false, settled = false;
    const orient = async () => {
        if (!application.isInitialViewSet || !viewer.pdfDocument) return;
        const page = viewer.currentPageNumber, current = ++revision;
        settled = false; assist.state.orienting = true; viewer.viewer.style.visibility="hidden";
        const result = await assist.orientation(page);
        if (disposed || current !== revision || page !== viewer.currentPageNumber) return;
        const angle = manual.has(page) ? manual.get(page) : result.angle || 0;
        applying = true;
        if (viewer.pagesRotation !== angle) {
            viewer.pagesRotation = angle;
            if (oriented.has(page)) mouse.restore(); else mouse.fit();
        }
        oriented.add(page);
        applying = false; settled = true; assist.state.orienting = false; viewer.viewer.style.visibility=""; render();
    };
    const rotated = () => {
        if (settled && !applying) manual.set(viewer.currentPageNumber, viewer.pagesRotation);
    };
    application.eventBus.on("documentinit", orient);
    application.eventBus.on("pagechanging", orient);
    application.eventBus.on("rotationchanging", rotated);
    orient();
    return () => {
        disposed = true; revision++; assist.state.orienting = false; viewer.viewer.style.visibility="";
        application.eventBus.off("documentinit", orient);
        application.eventBus.off("pagechanging", orient);
        application.eventBus.off("rotationchanging", rotated);
    };
}

function setupDrawingPdfControls(frame, application, positions) {
    const doc = frame.contentDocument;
    const view = frame.contentWindow;
    const viewer = application.pdfViewer;
    const container = viewer.container;
    const style = doc.createElement("style");
    style.textContent = `
        #toolbarViewerMiddle, #pageRotateCw, #pageRotateCcw { display: none !important; }
        #viewerContainer { overscroll-behavior: none; scrollbar-gutter: stable; }
        #viewer { box-sizing: content-box; width: max-content; padding: 50vh 50vw; }
        #viewer .page { margin: 0 !important; border: 0 !important; }
        #viewerContainer.o_drawing_pan_active,
        #viewerContainer.o_drawing_pan_active * { cursor: grabbing !important; user-select: none !important; }
    `;
    doc.head.appendChild(style);
    let activePage = viewer.currentPageNumber;
    let fitted = true;
    let requestedScale = viewer.currentScale;
    let restoring = false;
    let zooming = false;
    let disposed = false;
    let restoreFrame;
    let finishFrame;
    let panPosition;
    let documentReady = false;

    function pageRect(page = activePage) {
        return viewer.getPageView(page - 1)?.div.getBoundingClientRect();
    }

    function savePosition() {
        if (!documentReady || restoring || !viewer.pdfDocument) {
            return;
        }
        const page = pageRect();
        if (!page?.width || !page.height) {
            return;
        }
        const bounds = container.getBoundingClientRect();
        positions.set(activePage, {
            scale: viewer.currentScale, fitted,
            x: (bounds.left + container.clientWidth / 2 - page.left) / page.width,
            y: (bounds.top + container.clientHeight / 2 - page.top) / page.height,
        });
    }

    function centerAt(x, y) {
        const page = pageRect();
        if (!page?.width) {
            return;
        }
        const bounds = container.getBoundingClientRect();
        container.scrollLeft += page.left + page.width * x - bounds.left - container.clientWidth / 2;
        container.scrollTop += page.top + page.height * y - bounds.top - container.clientHeight / 2;
        viewer.update();
    }

    function restorePosition(reset = false) {
        if (!viewer.pdfDocument) {
            return;
        }
        restoring = true;
        view.cancelAnimationFrame(restoreFrame);
        view.cancelAnimationFrame(finishFrame);
        restoreFrame = view.requestAnimationFrame(() => {
            if (disposed) {
                return;
            }
            const saved = reset ? null : positions.get(activePage);
            viewer.update();
            fitted = saved ? saved.fitted : true;
            if (fitted) {
                viewer.currentScaleValue = "page-fit";
            } else {
                viewer.currentScale = saved.scale;
            }
            if (viewer.currentPageNumber !== activePage) {
                viewer.currentPageNumber = activePage;
            }
            requestedScale = viewer.currentScale;
            centerAt(saved && !reset ? saved.x : 0.5, saved && !reset ? saved.y : 0.5);
            finishFrame = view.requestAnimationFrame(() => {
                if (!disposed) {
                    restoring = false;
                    savePosition();
                }
            });
        });
    }

    const gestures = {
        zoom(factor, clientX, clientY) {
            if (restoring || !viewer.pdfDocument) {
                return;
            }
            const before = pageRect();
            if (!before?.width) {
                return;
            }
            const x = (clientX - before.left) / before.width;
            const y = (clientY - before.top) / before.height;
            requestedScale = Math.max(DRAWING_GESTURES.minScale,
                Math.min(DRAWING_GESTURES.maxScale, requestedScale * factor));
            zooming = true;
            fitted = false;
            viewer.updateScale({ scaleFactor: requestedScale / viewer.currentScale, drawingDelay: 80 });
            const after = pageRect();
            container.scrollLeft += after.left + after.width * x - clientX;
            container.scrollTop += after.top + after.height * y - clientY;
            viewer.update();
            zooming = false;
            savePosition();
        },
        startPan() {
            fitted = false;
            viewer.currentScale = viewer.currentScale;
            panPosition = { x: container.scrollLeft, y: container.scrollTop };
        },
        pan(dx, dy) {
            panPosition.x = Math.max(0, Math.min(container.scrollWidth - container.clientWidth,
                panPosition.x - dx));
            panPosition.y = Math.max(0, Math.min(container.scrollHeight - container.clientHeight,
                panPosition.y - dy));
            container.scrollLeft = panPosition.x;
            container.scrollTop = panPosition.y;
            savePosition();
        },
        fit() { restorePosition(true); },
    };
    const controls = bindDrawingMouseControls(container, gestures);
    const removeOverview = bindDrawingOverview(doc, application, (x, y) => {
        if (restoring) return;
        fitted = false;
        centerAt(x, y);
        savePosition();
    });

    const onPageChange = ({ pageNumber }) => {
        if (restoring) {
            return;
        }
        savePosition();
        activePage = pageNumber;
        if (!controls.dragging && !zooming) {
            restorePosition();
        }
    };
    const onScaleChange = () => {
        if (documentReady && !zooming && !restoring) {
            requestedScale = viewer.currentScale;
            fitted = false;
            savePosition();
        }
    };
    const onDocumentInit = () => {
        restoring = true;
        viewer.scrollMode = 3;
        viewer.spreadMode = 0;
        activePage = viewer.currentPageNumber;
        documentReady = true;
        restorePosition();
    };
    application.eventBus.on("documentinit", onDocumentInit);
    application.eventBus.on("pagechanging", onPageChange);
    application.eventBus.on("scalechanging", onScaleChange);
    container.addEventListener("scroll", savePosition, { passive: true });
    const resize = new view.ResizeObserver(() => {
        if (fitted && application.isInitialViewSet && !restoring) {
            restorePosition(true);
        }
    });
    resize.observe(container);
    if (application.isInitialViewSet && viewer.pdfDocument) {
        onDocumentInit();
    }

    const cleanup = () => {
        savePosition();
        disposed = true;
        controls.destroy();
        removeOverview();
        resize.disconnect();
        view.cancelAnimationFrame(restoreFrame);
        view.cancelAnimationFrame(finishFrame);
        container.removeEventListener("scroll", savePosition);
        application.eventBus.off("documentinit", onDocumentInit);
        application.eventBus.off("pagechanging", onPageChange);
        application.eventBus.off("scalechanging", onScaleChange);
        style.remove();
    };
    cleanup.fit = () => restorePosition(true);
    cleanup.restore = () => restorePosition();
    cleanup.zoom = (step) => {
        const bounds = container.getBoundingClientRect();
        gestures.zoom(DRAWING_GESTURES.wheelStep ** step,
            bounds.left + container.clientWidth / 2, bounds.top + container.clientHeight / 2);
    };
    cleanup.rotate = (angle) => {
        if (!viewer.pdfDocument) return;
        savePosition();
        const saved = positions.get(activePage);
        if (saved) {
            const [x, y] = rotateDrawingRect([saved.x, saved.y, 0, 0], angle);
            positions.set(activePage, { ...saved, x, y });
        }
        restoring = true;
        viewer.pagesRotation = (viewer.pagesRotation + angle + 360) % 360;
        restorePosition();
    };
    cleanup.focus = (box, rect) => {
        if (!viewer.pdfDocument || !rect || viewer.currentPageNumber !== box.page) return;
        restoring = true;
        view.cancelAnimationFrame(restoreFrame);
        view.cancelAnimationFrame(finishFrame);
        activePage = box.page;
        restoreFrame = view.requestAnimationFrame(() => {
            if (disposed) return;
            viewer.currentScaleValue = "page-fit";
            const page = pageRect(box.page);
            if (!page?.width || viewer.currentPageNumber !== box.page) {
                restoring = false;
                return;
            }
            const [x, y, w, h] = rotateDrawingRect(rect, viewer.pagesRotation - box.rotation);
            const factor = evidenceMagnification(container.clientWidth, container.clientHeight, page.width,
                page.height, [x, y, w, h]);
            fitted = false;
            viewer.currentScale = Math.min(DRAWING_GESTURES.maxScale, viewer.currentScale * factor);
            requestedScale = viewer.currentScale;
            const zoomedPage = pageRect();
            centerAt(evidenceCenter(x + w / 2, zoomedPage.width, container.clientWidth),
                evidenceCenter(y + h / 2, zoomedPage.height, container.clientHeight));
            finishFrame = view.requestAnimationFrame(() => {
                restoring = false;
                savePosition();
            });
        });
    };
    return cleanup;
}

class DrawingPdfViewerField extends PdfViewerField {
    setup() {
        super.setup();
        const assist = drawingDimensionSession(this.props.record, useService("orm"));
        this.drawingPagePositions = new Map();
        useOnChange(() => [this.iframeViewerPdfRef()], (frame) => {
            if (!frame) {
                return;
            }
            let revision = 0;
            let removeControls = () => {};
            const install = async () => {
                const currentRevision = ++revision;
                removeControls();
                removeControls = () => {};
                const document = frame.contentDocument;
                frame.title = "原始 PDF 图纸";
                const application = frame.contentWindow?.PDFViewerApplication;
                if (!application) {
                    return;
                }
                await application.initializedPromise;
                if (currentRevision === revision && frame.contentDocument === document) {
                    const viewer = application.pdfViewer;
                    const previewPage = () => viewer.pdfDocument ? {
                        page: viewer.currentPageNumber, rotation: viewer.pagesRotation,
                    } : null;
                    assist.vision.previewPage = previewPage;
                    const updateViewerReady = () => {
                        assist.state.viewerReady = Boolean(application.pdfDocument);
                    };
                    updateViewerReady();
                    application.eventBus.on("pagesinit", updateViewerReady);
                    const removeMouse = setupDrawingPdfControls(frame, application, this.drawingPagePositions);
                    assist.fitPreview = removeMouse.fit;
                    assist.rotatePreview = removeMouse.rotate;
                    assist.zoomPreview = removeMouse.zoom;
                    let focusRevision = 0;
                    const dimensions = bindDrawingDimensionSelection(application.pdfViewer.container, () => {
                        const viewer = application.pdfViewer;
                        return viewer.pdfDocument ? { element: viewer.getPageView(viewer.currentPageNumber-1)?.div,
                            page: viewer.currentPageNumber, rotation: viewer.pagesRotation,
                            orientation: assist.orientationAngles.get(viewer.currentPageNumber) || 0 } : null;
                    }, assist, async (box, token) => {
                        const viewer = application.pdfViewer;
                        if (!viewer.pdfDocument) return;
                        const request = ++focusRevision;
                        if (viewer.currentPageNumber !== box.page) viewer.currentPageNumber = box.page;
                        if (!token?.rect) return;
                        if (assist.state.orienting) await assist.orientation(box.page);
                        if (request === focusRevision && revision === currentRevision) {
                            removeMouse.focus(box, token.rect);
                        }
                    });
                    const events = ["pagerendered", "pagechanging", "rotationchanging", "scalechanging"];
                    for (const name of events) application.eventBus.on(name, dimensions.render);
                    const removeOrientation = bindDrawingPdfOrientation(application, assist, removeMouse, dimensions.render);
                    removeControls = () => {
                        application.eventBus.off("pagesinit", updateViewerReady);
                        if (assist.vision.previewPage === previewPage) {
                            assist.vision.previewPage = null;
                            assist.state.viewerReady = false;
                            assist.fitPreview = null;
                            assist.rotatePreview = null;
                            assist.zoomPreview = null;
                        }
                        for (const name of events) application.eventBus.off(name, dimensions.render);
                        removeOrientation(); dimensions.destroy(); removeMouse();
                    };
                }
            };
            frame.addEventListener("load", install);
            install();
            return () => {
                revision++;
                frame.removeEventListener("load", install);
                removeControls();
            };
        });
    }

    get url() {
        const source = super.url;
        return source ? source + "&zoom=page-fit" : source;
    }
}

class DrawingImageField extends ImageField {
    static template = "nodo_contract.DrawingImagePreview";
    viewportRef = signal.ref();

    setup() {
        super.setup();
        const assist = drawingDimensionSession(this.props.record, useService("orm"));
        useOnChange(() => [this.viewportRef()], (surface) => {
            if (!surface) {
                return;
            }
            const image = surface.querySelector("img");
            const view = { x: 0, y: 0, scale: 1, fitted: true, width: 0, height: 0, angle: 0 };
            let disposed = false, requested = false;
            const displaySize = () => view.angle % 180 ? [image.naturalHeight,image.naturalWidth] : [image.naturalWidth,image.naturalHeight];
            const apply = () => {
                image.style.width = image.naturalWidth + "px";
                image.style.height = image.naturalHeight + "px";
                const [ox,oy] = {0:[0,0],90:[image.naturalHeight,0],180:[image.naturalWidth,image.naturalHeight],270:[0,image.naturalWidth]}[view.angle];
                image.style.transform = `translate(${view.x+ox*view.scale}px, ${view.y+oy*view.scale}px) rotate(${view.angle}deg) scale(${view.scale})`;
            };
            const fit = () => {
                if (!image.naturalWidth) {
                    return;
                }
                const [w,h] = displaySize();
                view.scale = Math.min(DRAWING_GESTURES.maxScale, surface.clientWidth / w, surface.clientHeight / h);
                view.x = (surface.clientWidth - w * view.scale) / 2;
                view.y = (surface.clientHeight - h * view.scale) / 2;
                view.fitted = true;
                apply();
            };
            const onLoad = () => {
                assist.state.viewerReady = Boolean(image.naturalWidth);
                if (view.width !== image.naturalWidth || view.height !== image.naturalHeight) {
                    view.width = image.naturalWidth;
                    view.height = image.naturalHeight;
                    fit();
                } else {
                    apply();
                }
                if (!requested && image.naturalWidth) {
                    requested = true; assist.state.orienting = true; image.style.visibility="hidden";
                    assist.orientation(1).then((result) => {
                        if (disposed) return;
                        if (result.angle && result.angle !== view.angle) { view.angle = result.angle; fit(); }
                        assist.state.orienting = false; image.style.visibility=""; dimensions.render();
                    });
                }
            };
            image.addEventListener("load", onLoad);
            const controls = bindDrawingMouseControls(surface, {
                zoom(factor, clientX, clientY) {
                    if (!image.naturalWidth) {
                        return;
                    }
                    const bounds = surface.getBoundingClientRect();
                    const x = clientX - bounds.left;
                    const y = clientY - bounds.top;
                    const scale = Math.max(DRAWING_GESTURES.minScale,
                        Math.min(DRAWING_GESTURES.maxScale, view.scale * factor));
                    view.x = x - (x - view.x) * scale / view.scale;
                    view.y = y - (y - view.y) * scale / view.scale;
                    view.scale = scale;
                    view.fitted = false;
                    apply();
                },
                pan(dx, dy) {
                    view.x += dx;
                    view.y += dy;
                    view.fitted = false;
                    apply();
                },
                fit,
            });
            assist.fitPreview = fit;
            const dimensions = bindDrawingDimensionSelection(surface,
                () => ({ element: image, page: 1, rotation: view.angle,
                    orientation: assist.orientationAngles.get(1) || 0 }), assist, (box, token) => {
                    if (!token || !image.naturalWidth) return;
                    const p = rotateDrawingRect(token.rect,view.angle-box.rotation), [w,h] = displaySize();
                    const fitScale = Math.min(surface.clientWidth / w, surface.clientHeight / h);
                    const factor = evidenceMagnification(surface.clientWidth, surface.clientHeight, w * fitScale, h * fitScale, p);
                    view.scale = Math.min(DRAWING_GESTURES.maxScale, fitScale * factor);
                    view.x = surface.clientWidth / 2 - evidenceCenter(p[0] + p[2] / 2, w * view.scale, surface.clientWidth) * w * view.scale;
                    view.y = surface.clientHeight / 2 - evidenceCenter(p[1] + p[3] / 2, h * view.scale, surface.clientHeight) * h * view.scale;
                    view.fitted = false; apply();
                });
            const resize = new ResizeObserver(() => {
                if (view.fitted) {
                    fit();
                }
            });
            resize.observe(surface);
            if (image.complete) {
                onLoad();
            }
            return () => {
                disposed = true; assist.state.orienting = false;
                if (assist.fitPreview === fit) {
                    assist.state.viewerReady = false;
                    assist.fitPreview = null;
                }
                controls.destroy();
                dimensions.destroy();
                resize.disconnect();
                image.removeEventListener("load", onLoad);
            };
        });
    }
}

registry.category("fields").add("nodo_contract_drawing_pdf", {
    ...pdfViewerField,
    component: DrawingPdfViewerField,
});
registry.category("fields").add("nodo_contract_drawing_image", {
    ...imageField,
    component: DrawingImageField,
});
