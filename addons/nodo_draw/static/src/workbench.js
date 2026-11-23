import {Component, Portal, signal, onWillStart, onWillUnmount, untrack, useEffect, useListener, useProps} from "@odoo/owl";
import {registry} from "@web/core/registry";
import {useService} from "@web/core/utils/hooks";
import {loadBundle} from "@web/core/assets";
import {standardActionServiceProps} from "@web/webclient/actions/action_plugin";
import {useSetupAction} from "@web/search/action_hook";
import {FaceCanvas, containsMaterial, faceSurface} from "./mesh";
import {AccessoryCatalog, accessoryRestriction} from "./accessory_library";
import {ArchivedCabinet, DrawingViewport, fitView} from "./archive_preview";
import {ExplosionControls} from "./explosion_controls";
import {conflictsWithPlate, holeCoordinate, holeDimensionsReady, holeRecord, linkedHole, openingAt, sameHole, sameThickness} from "./hole_editing";
import {PartsPanel} from "./parts_panel";
import {SheetUsage} from "./sheet_usage";
import {SheetSettings} from "./sheet_settings";

const MODEL="nodo.draw.design";
const faceNames={door:"门板",door_right:"右门板",mount:"安装板",top:"顶板",bottom:"底板",back:"后板",left:"左侧板",right:"右侧板"};
const docTypes={assembly:"总装",formed:"成形",flat:"展开",weld:"焊接",bom:"零件明细",schedule:"孔位表"};
const clone=value=>JSON.parse(JSON.stringify(value));
const fieldNumber=(v)=>v===""?null:Number(v);
const defaultHole = face => ({type:"circle", face, u:95, v:110, diameter:18, width:40, height:24});
const freshHoleDraft = face => ({values: defaultHole(face), editing: null, copiedFrom: null, active: false});
const meshKind = mesh => mesh?.parameters?.configuration?.kind;
const boardViews = {door:"front", door_right:"front", mount:"front", top:"top", bottom:"bottom", back:"rear", left:"left", right:"right"};
const pendingHoleNotice = "请先确认或取消当前孔位。";
const minPanel = 270;
const maxPanel = 440;
const noParts = [];

export class Workbench extends Component {
    static template="nodo_draw.Workbench";
    static components = {AccessoryCatalog, ArchivedCabinet, DrawingViewport, ExplosionControls, PartsPanel, Portal, SheetSettings, SheetUsage};
    props=useProps({...standardActionServiceProps});
    docs=signal([]); doc=signal(null); form=signal(null); tab=signal("cabinet");
    settingsDirty=signal(false); busy=signal(false); issue=signal(""); mesh=signal(null);
    draftPreview=signal(null);
    accessoryPicker=signal(null);
    placementReview=signal([]);
    referenceDrawings=signal({});
    referenceKind=signal(null);
    modelJob=signal(null); mode=signal("3d"); opened=signal(false); face=signal("door");
    explosion=signal(0);
    holeDraft=signal(freshHoleDraft("door"));
    holeHistory=signal({undo: [], redo: []});
    holeBases=signal({});
    holeAssembly=signal(false);
    drilling=signal(false);
    drillFace=signal(null);
    drillNotice=signal("");
    drillSnap=signal(1);
    boardView=signal(null);
    cameraRestore=signal(null);
    inspectedPart=signal(null);
    batch=signal(null); sheet=signal(null); showFiles=signal(false);
    archiveMode=signal("drawing");
    archiveMenu=signal(null);
    directoryHidden=signal(false);
    panelHidden=signal(false);
    panelWidth=signal(306);
    usageWidth=signal(this.constructor.usagePanelWidth ?? 540);
    partsView=signal("usage");
    selectedParts=signal(noParts);
    hiddenParts=signal(noParts);
    partFocus=signal(null);
    frontFacesOpen=signal(false);
    canvas=signal.ref();
    threeHost=signal.ref();
    viewReset=signal(0);
    viewerError=signal("");
    setup(){
        this.orm=useService("orm"); this.notification=useService("notification");
        this.action=useService("action");
        this.drawingViews = new Map();
        this.holeDrafts = new Map();
        this.savedHoles = null;
        this.holeInput = null;
        this.epoch=0;this.docTypes=docTypes;
        this.dims=[["width","宽"],["height","高"],["depth","深"]];
        this.holeAxes = [["u", "横向 U"], ["v", "纵向 V"]];
        this.holeBasisOptions = [["start", "从起边"], ["end", "从终边"], ["center", "从中心线"]];
        this.tabs=[["cabinet","规格"],["materials","材料"],["parts","零件"],["holes","孔位"]];
        this.assemblyReturn = null;
        this.focusSequence = 0;
        this.cameraSequence = 0;
        this.views=[["top","俯视"],["left","左视"],["door","正视"],["right","右视"],["back","后视"],["bottom","仰视"]];
        this.downloads=[["bundle","整套图包"],["step","整柜 STEP"],["bom","零件清单"],["holes","孔位表"]];
        useSetupAction({beforeLeave:()=>!this.dirty()||window.confirm("离开并放弃未保存的设计修改？")});
        useListener(document, "click", event => this.dismissArchiveMenu(event));
        useListener(document, "keydown", event => this.keyArchiveMenu(event));
        onWillStart(async()=>{
            try {
                await loadBundle("nodo_draw.assets_ae");
                if (!window.nodoDrawAE0573?.mount) throw new Error();
            } catch {
                this.viewerError.set("三维视口加载失败，请刷新后重试。");
            }
            const [designs, references] = await Promise.all([
                this.orm.call(MODEL,"list_designs",[]), this.orm.call(MODEL,"list_reference_drawings",[]),
            ]);
            this.docs.set(designs);
            this.referenceDrawings.set(references);
            const query = new URLSearchParams(window.location.search);
            const initialId = query.get("design");
            const initial = designs.find(design => String(design.id) === initialId) || designs[0];
            if (initial) {
                await this.loadDesign(initial.id);
                if (query.get("tab") === "parts") this.selectTab("parts");
            }
        });
        useEffect(()=>{
            const host = this.threeHost();
            if (!host || this.viewerError()) return;
            const view = window.nodoDrawAE0573.mount(host);
            this.threeView = view;
            untrack(() => this.updateThree());
            return () => { this.threeView = null; view.dispose(); };
        });
        useEffect(() => {
            const canvas = this.canvas();
            if (!canvas) return;
            const view = new FaceCanvas(canvas);
            this.faceView = view;
            untrack(() => view.set(this.displayMesh(), this.flatDisplay()));
            return () => { this.faceView = null; view.dispose(); };
        });
        useEffect(() => {
            this.updateThree();
        });
        useEffect(()=>{
            const data=this.displayMesh(), display=this.flatDisplay();
            this.faceView?.set(data,display);
        });
        onWillUnmount(() => {
            this.epoch++;
            clearTimeout(this.poll);
            this.aborter?.abort();
            clearTimeout(this.draftPreviewPoll);
            this.draftPreviewAbort?.abort();
        });
    }
    flatDisplay(){
        const overlay = this.holeOverlay();
        return {face:this.face(), holes:this.form()?.holes || [], active:overlay?.active, editing:overlay?.editing, issue:overlay?.issue};
    }
    designLabel(design){
        const versions = this.docs().filter(item => item.source === design.source);
        return design.source + " · " + design.name + (versions.length > 1 ? " · 交接版 " + design.source_version : "");
    }
    updateThree(){
        const mesh = this.displayMesh(), open = this.opened(), paused = this.mode() !== "3d", reset = this.viewReset();
        const selection = this.accessoryPicker();
        const boardView = this.boardView(), drillFace = this.drillFace();
        const picked = this.inspectedPart()?.id, showParts = this.tab() === "parts";
        const explode = this.drilling() ? 0 : this.explosion();
        let parts = {
            selected:showParts ? this.selectedParts() : !selection && picked ? [picked] : noParts,
            hidden:showParts ? this.hiddenParts() : noParts,
            focus:showParts ? this.partFocus() : null,
            pick:(id, face) => this.accessoryPicker() ? this.selectAccessoryFace(face) : this.inspectPart(id, face),
            clear:() => { if (!this.accessoryPicker()) this.inspectPart(null); },
        };
        const overlay = paused || explode ? null : this.holeOverlay(mesh);
        const drill = !paused && this.drilling() && !this.busy() && this.holeGeometryReady(mesh) ? {
            snap:this.drillSnap(),
            pick:(plane, surface, obstructed) => this.pickDrill(plane, surface, obstructed),
            move:(u,v) => this.moveDrill(u,v), end:() => this.endHoleInput(),
            edit:id => this.pickExistingHole(id),
        } : null;
        if (this.drilling()) {
            const part = this.board(drillFace)?.part;
            parts = {selected:part ? [part] : noParts, hidden:boardView && part
                ? mesh.parts.filter(item => item.id !== part).map(item => item.id) : noParts};
        }
        const orientation = {view:boardView ? boardViews[boardView.face] : "iso", restore:this.cameraRestore()};
        this.threeView?.update(mesh, !boardView && open, paused, reset,
            {parts, holePreview:overlay, drilling:drill, orientation, explode, installationFace:selection?.face,
                sheetSelection:this.usageOpen()});
    }
    cabinetParts() { return this.displayMesh()?.parts ?? noParts; }
    hasSheetUsage() { return !!this.doc()?.sheet_usage_enabled; }
    usageOpen() { return this.tab() === "parts" && this.hasSheetUsage() && this.partsView() === "usage"; }
    sheetMeshId() {
        const mesh = this.displayMesh(), draft = this.draftPreview();
        if (!mesh) return 0;
        if (draft?.mesh === mesh) return draft.snapshot === this.form() ? draft.jobId : 0;
        const job = this.modelJob();
        return !this.dirty() && job?.edit_number === this.doc().edit_number ? job.id : 0;
    }
    inspectPart(id, face = null) {
        this.inspectedPart.set(id ? {id, face} : null);
        if (this.tab() === "parts") this.selectParts(id ? [id] : noParts);
    }
    selectParts(ids, locate = false) {
        this.selectedParts.set(ids);
        if (ids.length !== 1) this.inspectedPart.set(null);
        else if (ids[0] !== this.inspectedPart()?.id) this.inspectedPart.set({id:ids[0], face:null});
        this.hiddenParts.set(this.hiddenParts().filter(id => !ids.includes(id)));
        if (locate) this.partFocus.set({ids, nonce: ++this.focusSequence});
    }
    toggleParts(ids) {
        const hidden = this.hiddenParts();
        this.hiddenParts.set(ids.every(id => hidden.includes(id))
            ? hidden.filter(id => !ids.includes(id)) : [...new Set([...hidden, ...ids])]);
    }
    resetParts() {
        this.inspectedPart.set(null);
        this.selectedParts.set(noParts);
        this.hiddenParts.set(noParts);
        this.partFocus.set(null);
    }
    previewScope() {
        if (this.tab() === "assembly" || (this.tab() === "holes" && this.holeAssembly())) return "design";
        return this.form()?.kind === this.doc()?.settings.kind ? "cabinet" : "base";
    }
    displayMesh() {
        const preview = this.draftPreview(), scope = this.previewScope(), kind = this.form()?.kind;
        const mesh = preview?.scope === scope && preview.mesh ? preview.mesh : this.mesh();
        if (!mesh || meshKind(mesh) !== kind) return null;
        if (scope !== "design" && mesh.parameters.accessories?.length) return null;
        if (scope === "base" && mesh.parameters.holes?.length) return null;
        return mesh;
    }
    previewNote() {
        if (this.tab() === "holes" && this.mode() === "3d" && (this.drilling() || !this.explosion()) && this.holeGeometryReady() &&
                (this.holeDraft().active || this.form().holes !== this.savedHoles)) {
            return "孔位轮廓预览 · 实体待更新";
        }
        const draft = this.draftPreview();
        if (draft?.mesh && draft.snapshot !== this.form()) return "草稿已修改，预览待更新";
        const mesh = this.displayMesh();
        if (mesh && this.previewScope() !== "design") {
            const label = mesh.parameters.holes?.length ? "柜体预览" : "基础预览";
            return this.dirty() ? `${label} · 未保存` : label;
        }
        if (draft?.mesh) return "草稿预览 · 未保存";
        if (this.dirty()) return "有未保存修改";
        return this.modelJob() && this.modelJob().edit_number !== this.doc().edit_number ? "显示上一版模型" : "";
    }
    kindName(kind) { return kind === "double" ? "双开门" : "单开门"; }
    fitView(){
        if (this.mode() === "3d") this.viewReset.set(this.viewReset() + 1);
        else this.faceView?.fit();
    }
    url(id,key){return "/nodo/draw/file/"+id+"/"+key;}
    version(value){return String(value).padStart(2,"0");}
    jobState(job){return {done:"已生成",failed:"生成失败",queued:"等待计算",running:"计算中"}[job.state];}
    faceName(id) {
        return id === "door" && this.form()?.kind === "double" ? "左门板" : faceNames[id];
    }
    board(id = this.face()) {
        return this.displayMesh()?.faces.find(face => face.id === id);
    }
    boards() {
        return Object.keys(faceNames).map(id => this.board(id)).filter(Boolean);
    }
    boardHoles(id = this.face()) {
        return this.form().holes.filter(hole => hole.face === id);
    }
    linkedHoles(id) {
        return (this.displayMesh()?.parameters?.holes || []).filter(hole => hole.face === id && hole.ownerAccessory).length;
    }
    mountingFaces(model){
        return (model.faces||[model.face]).filter(face=>face!=="door_right"||this.form().kind==="double");
    }
    async selectDesign(event){
        const current=this.doc().id, select=event.target;
        const chosen=Number(select.value);
        select.value=String(current);
        const archive = this.showFiles();
        const reference = this.referenceKind();
        if (await this.loadDesign(chosen) && archive) {
            if (reference) this.openReference();
            else this.openArchive();
        }
    }
    async loadDesign(id){
        if(this.dirty()&&!window.confirm("切换柜体并放弃未保存的修改？")) return;
        this.closeAccessoryPicker();
        this.leaveDrilling();
        this.explosion.set(0);
        this.cameraRestore.set(null);
        this.resetDraftPreview();
        this.resetParts();
        this.partsView.set("usage");
        clearTimeout(this.poll);this.aborter?.abort();this.mesh.set(null);this.modelJob.set(null);
        this.meshRequest=null;this.issue.set("");this.settingsDirty.set(false);this.sheet.set(null);
        this.showFiles.set(false);this.batch.set(null);this.referenceKind.set(null);this.face.set("door");
        this.drawingViews.clear();this.archiveMode.set("drawing");this.archiveMenu.set(null);
        this.holeDrafts.clear();this.frontFacesOpen.set(false);
        this.holeBases.set({});
        this.resetHoleHistory();
        this.holeAssembly.set(false);
        this.assemblyReturn = null;
        this.mode.set("3d");this.opened.set(false);this.tab.set("cabinet");
        this.holeDraft.set(freshHoleDraft("door"));this.busy.set(false);
        const epoch=++this.epoch;
        await this.refresh(id,epoch,true);
        return epoch === this.epoch;
    }
    async refresh(id,epoch,replace=false){
        clearTimeout(this.poll);
        const data=await this.orm.call(MODEL,"workspace",[[id]]);
        if(epoch!==this.epoch)return;
        this.doc.set(data);
        if (replace) {
            const form = {...clone(data.settings), positions:{}, assembly_positions:{}};
            this.savedHoles = form.holes;
            this.form.set(form);
            this.localEdit = data.edit_number;
            this.settingsDirty.set(false);
            this.placementReview.set([]);
            this.resetHoleHistory();
        }
        const current=data.jobs.find(j=>j.state==="done"&&j.files?.includes("mesh"));
        if(current&&this.modelJob()?.id!==current.id&&this.meshRequest!==current.id){
            this.meshRequest=current.id;
            this.aborter?.abort();this.aborter=new AbortController();
            fetch(this.url(current.id,"mesh"),{signal:this.aborter.signal}).then(async response=>{
                if(!response.ok)throw Error("三维模型读取失败");
                const mesh=await response.json();
                if(epoch===this.epoch&&this.meshRequest===current.id){
                    this.mesh.set(mesh);this.modelJob.set(current);
                    if (this.displayMesh() === mesh && !this.board()) this.setFace("door");
                    this.ensureDraftPreview();
                }
            }).catch(err=>{if(err.name!=="AbortError"&&epoch===this.epoch){this.issue.set(err.message);this.meshRequest=null;}});
        } else if (replace) {
            this.ensureDraftPreview();
        }
        const latest=data.jobs[0];
        if(latest?.state==="failed")this.issue.set(latest.error);
        if(latest?.issues?.length)this.issue.set(latest.issues.join(" · "));
        if(data.jobs.some(job=>["queued","running"].includes(job.state))){
            this.poll=setTimeout(()=>this.refresh(id,epoch).catch(e=>this.issue.set(e.message)),1600);
        }
    }
    dirty() { return this.settingsDirty() || !!this.form() && this.form().holes !== this.savedHoles; }
    patch(p){
        if (this.draftPreview()?.assembly) this.resetDraftPreview();
        this.form.set({...this.form(),...p});this.settingsDirty.set(true);this.issue.set("");
    }
    resetDraftPreview() {
        clearTimeout(this.draftPreviewPoll);
        this.draftPreviewAbort?.abort();
        this.draftPreview.set(null);
    }
    selectKind(kind) {
        if (this.busy()) return;
        const current = this.form();
        const preview = this.draftPreview();
        if (current.kind === kind && preview?.snapshot === current && !preview.error) return;
        if (current.kind !== kind) {
            this.patch({kind});
            this.explosion.set(0);
            this.resetParts();
            this.resetHoleHistory();
            this.setFace("door");
            this.opened.set(false);
        }
        this.resetDraftPreview();
        this.ensureDraftPreview();
    }
    ensureDraftPreview() {
        const snapshot = this.form();
        if (!snapshot?.kind || this.showFiles() || this.draftPreview() || this.displayMesh()) return;
        if (this.dims.some(([key]) => snapshot[key] === null)) return;
        const scope = this.previewScope();
        if (scope === "design" && snapshot.kind === this.doc().settings.kind &&
                this.doc().jobs.some(job => job.state !== "failed")) return;
        const id = this.doc().id;
        const expected = this.localEdit;
        const request = this.draftPreviewAbort = new AbortController();
        this.draftPreview.set({snapshot, scope, stage:"等待计算"});
        this.draftPreviewPoll = setTimeout(async () => {
            try {
                const job = await this.orm.call(MODEL, "preview_cabinet", [[id], expected, snapshot, scope]);
                await this.readDraftPreview(id, job, request.signal);
            } catch (error) {
                this.failDraftPreview(error, request.signal);
            }
        }, 160);
    }
    async readDraftPreview(id, jobId, signal) {
        if (signal.aborted) return;
        const job = await this.orm.call(MODEL, "cabinet_preview_status", [[id], jobId]);
        if (signal.aborted) return;
        if (job.state === "failed") throw Error(job.error);
        if (job.state === "done") {
            const response = await fetch(this.url(jobId, "mesh"), {signal});
            if (!response.ok) throw Error("三维模型读取失败");
            const mesh = await response.json();
            if (signal.aborted) return;
            if (meshKind(mesh) !== this.form().kind) throw Error("返回的模型与所选柜型不符，请重试。");
            this.draftPreview.set({...this.draftPreview(), mesh, issues:job.issues ?? [], jobId});
            return;
        }
        this.draftPreview.set({...this.draftPreview(), stage:job.stage});
        this.draftPreviewPoll = setTimeout(() => {
            this.readDraftPreview(id, jobId, signal).catch(error => this.failDraftPreview(error, signal));
        }, 650);
    }
    failDraftPreview(error, signal) {
        if (!signal.aborted) this.draftPreview.set({...this.draftPreview(), error:error.data?.message || error.message});
    }
    changeField(key,ev,numeric=false){this.patch({[key]:numeric?fieldNumber(ev.target.value):ev.target.value});}
    selectTab(id, in3d = false, scope = this.previewScope()) {
        const previous = this.previewScope();
        if (id !== "assembly") this.closeAccessoryPicker();
        if (id !== "holes" || !in3d) this.leaveDrilling();
        this.partFocus.set(null);
        if (id === "holes") this.holeAssembly.set(scope === "design");
        if (id === "parts" && this.tab() !== "parts" && this.inspectedPart()) {
            this.selectedParts.set([this.inspectedPart().id]);
        }
        this.tab.set(id);
        this.showFiles.set(false);
        this.panelHidden.set(false);
        if (id === "holes") this.mode.set(in3d ? "3d" : "2d");
        else if (id !== "materials") this.mode.set("3d");
        if (previous !== this.previewScope()) {
            this.resetDraftPreview();
            this.ensureDraftPreview();
        }
    }
    showThree() {
        this.leaveDrilling();
        this.mode.set("3d");
    }
    beginExplosion() {
        const board = this.drilling() && this.board(this.drillFace());
        if (board) this.inspectPart(board.part, board.id);
        this.showThree();
    }
    startDrilling() {
        if (this.drilling()) return;
        const picked = this.explosion() && this.inspectedPart();
        const boards = picked ? this.boards().filter(board => board.part === picked.id) : noParts;
        const board = boards.find(board => board.id === picked?.face) ?? (boards.length === 1 ? boards[0] : null);
        this.selectTab("holes", true);
        this.drilling.set(true);
        if (board) this.selectBoard(board.id);
        else this.drillFace.set(this.holeDraft().active ? this.face() : null);
        if (this.explosion()) this.fitView();
    }
    leaveDrilling() {
        if (!this.drilling()) return;
        this.returnToCabinet();
        this.drilling.set(false);
        this.drillFace.set(null);
        this.drillNotice.set("");
        this.endHoleInput();
        if (this.explosion()) this.fitView();
    }
    selectBoard(id) {
        if (this.drilling()) {
            if (this.boardView()?.face !== id) this.returnToCabinet();
            this.drillFace.set(id);
            this.drillNotice.set("");
        }
        this.setFace(id);
    }
    focusBoard() {
        if (this.boardView()) {
            this.returnToCabinet();
            return;
        }
        if (!this.holeGeometryReady() || !this.board()) return;
        this.selectBoard(this.face());
        this.boardView.set({face:this.face(), original:this.threeView?.camera()});
        this.cameraRestore.set(null);
        this.viewReset.set(this.viewReset()+1);
    }
    returnToCabinet() {
        const view = this.boardView();
        if (!view) return;
        this.boardView.set(null);
        const reset = this.viewReset()+1;
        if (view.original) this.cameraRestore.set({id:++this.cameraSequence, camera:{...view.original, view:"iso", reset}});
        this.viewReset.set(reset);
    }
    assemblyOpen() { return !this.showFiles() && this.tab() === "assembly"; }
    openAccessoryLibrary() { return this.action.doAction("nodo_draw.action_accessory_library"); }
    openAssembly() {
        if (this.assemblyOpen()) {
            const previous = this.assemblyReturn;
            this.selectTab(previous?.tab ?? "cabinet", previous?.in3d, previous?.scope);
            if (previous?.drilling) this.startDrilling();
        } else {
            this.assemblyReturn = {
                tab:this.tab(), in3d:this.mode() === "3d", scope:this.previewScope(), drilling:this.drilling(),
            };
            this.selectTab("assembly");
        }
    }
    startPanelResize(event) {
        if (!event.isPrimary || event.button !== 0) return;
        this.panelDrag = {id:event.pointerId, x:event.clientX, width:this.currentPanelWidth()};
        event.currentTarget.setPointerCapture(event.pointerId);
    }
    currentPanelWidth() { return this.usageOpen() ? this.usageWidth() : this.panelWidth(); }
    setPanelWidth(value) {
        if (this.usageOpen()) this.usageWidth.set(Math.max(390, Math.min(660, value)));
        else this.panelWidth.set(Math.max(minPanel, Math.min(maxPanel, value)));
    }
    movePanelResize(event) {
        if (this.panelDrag?.id === event.pointerId) {
            this.setPanelWidth(this.panelDrag.width + event.clientX - this.panelDrag.x);
        }
    }
    endPanelResize(event) {
        if (this.panelDrag?.id === event.pointerId) this.panelDrag = null;
    }
    keyPanelResize(event) {
        const delta = {ArrowLeft:-16, ArrowRight:16}[event.key];
        if (!delta) return;
        event.preventDefault();
        this.setPanelWidth(this.currentPanelWidth() + delta);
    }
    focusPendingHole(){
        const pending = this.holeDraft().active ? this.face() :
            [...this.holeDrafts].find(([face,draft]) => face !== this.face() && draft.active)?.[0];
        if (pending) {
            if (this.tab() !== "holes" || this.showFiles()) this.selectTab("holes", this.mode() === "3d");
            this.selectBoard(pending);
            if (this.drilling()) this.drillNotice.set(pendingHoleNotice);
            else this.issue.set(pendingHoleNotice);
            return true;
        }
        return false;
    }
    async apply(operation, previewId = null){
        if(this.busy() || this.accessoryPicker() || this.focusPendingHole())return;
        this.busy.set(true);this.issue.set("");
        const doc=this.doc(), epoch=this.epoch;
        try{
            const args=[[doc.id],this.localEdit,this.form(),operation];
            if (previewId) args.push(previewId);
            const out=await this.orm.call(MODEL,"apply_design",args);
            if(epoch!==this.epoch)return;
            this.resetDraftPreview();
            await this.refresh(doc.id,epoch,true);
            if(epoch!==this.epoch)return;
            if(out.issues.length)this.issue.set(out.issues.join(" · "));
            if(operation==="generate"){
                if (out.reference_kind) this.openReference(out.reference_kind);
                else {
                    this.setBuild(out.job_id);
                    this.archiveMode.set("drawing");
                    this.showFiles.set(true);
                }
            }
            if(operation==="assemble"){this.tab.set("assembly");this.mode.set("3d");}
        }catch(e){if(epoch===this.epoch)this.issue.set(e.data?.message||e.message);}
        finally{if(epoch===this.epoch)this.busy.set(false);}
    }
    async previewAssembly(){
        if(this.busy() || this.focusPendingHole())return;
        this.resetDraftPreview();
        this.issue.set("");
        this.busy.set(true);
        const snapshot = this.form(), id = this.doc().id, epoch = this.epoch;
        const request = this.draftPreviewAbort = new AbortController();
        this.draftPreview.set({snapshot, scope:"design", assembly:true, stage:"等待计算"});
        try {
            const job = await this.orm.call(MODEL,"preview_assembly",[[id],this.localEdit,snapshot]);
            await this.readDraftPreview(id,job,request.signal);
        } catch(error) {
            this.failDraftPreview(error,request.signal);
        } finally {
            if (epoch===this.epoch) this.busy.set(false);
        }
    }
    assemblyPreview(){
        const draft = this.draftPreview();
        return draft?.assembly && draft.snapshot===this.form() ? draft : null;
    }
    confirmAssembly(){
        const draft = this.assemblyPreview();
        if (draft?.mesh && !draft.issues.length) return this.apply("assemble",draft.jobId);
    }
    closeAssemblyPreview(){
        this.resetDraftPreview();
        this.ensureDraftPreview();
    }
    chooseAccessory(i){
        if (this.busy()) return;
        const doc = this.doc(), form = this.form(), row = this.rowInfo(i), line = doc.bom.lines[i];
        const face = row.validFace ? row.face : "";
        const kind = form.kind === "double" ? "双开门" : "单开门";
        this.accessoryPicker.set({row:i, label:`${doc.bom.source} ${kind} · 第 ${i+1} 行 ${line.code} × ${line.quantity}`,
            kind:form.kind, code:row.code, originalFace:face, face, item:null, choices:[], notice:"",
            versions:Object.fromEntries(Object.entries(doc.library).map(([code,model])=>[code,model.version])),
        });
    }

    selectAccessoryModel(item) {
        const picker = this.accessoryPicker();
        if (!picker) return;
        const definition = this.doc().library[item.code];
        const choices = definition && !accessoryRestriction(item,picker)
            ? this.mountingFaces(definition).filter(face => this.faceName(face)).map(id => ({id,name:this.faceName(id)})) : [];
        const face = [picker.face,picker.originalFace].find(id => choices.some(choice => choice.id === id)) || "";
        this.accessoryPicker.set({...picker,item,choices,face,notice:""});
    }

    selectAccessoryFace(face) {
        const picker = this.accessoryPicker();
        if (!picker?.item || !picker.choices.length) return;
        if (!picker.choices.some(choice => choice.id === face)) {
            const name = this.faceName(face);
            this.accessoryPicker.set({...picker,notice:name ? `此型号不支持${name}` : "请选择可用安装面"});
            return;
        }
        this.accessoryPicker.set({...picker,face,notice:""});
    }

    applyAccessoryPicker() {
        const picker = this.accessoryPicker();
        if (!picker?.item || !picker.choices.some(choice => choice.id === picker.face)) return;
        this.commitAccessoryMatch(picker.row,picker.item.code,picker.face);
        this.closeAccessoryPicker();
    }

    closeAccessoryPicker() { this.accessoryPicker.set(null); }

    setAssemblyFace(i, face) { this.commitAccessoryMatch(i,this.rowInfo(i).code,face); }

    commitAccessoryMatch(i, code, face) {
        const row = this.rowInfo(i);
        if (row.code === code && row.face === face) return;
        const f = this.form();
        const prefix = `a${i+1}n`;
        const positions = Object.entries(f.assembly_positions);
        const remaining = positions.filter(([key]) => !key.startsWith(prefix));
        if (remaining.length !== positions.length || f.instances.some(item => item.row === i)) {
            this.placementReview.set([...new Set([...this.placementReview(),i])]);
        }
        this.patch({matches:{...f.matches,[i]:{code,face}},assembly_positions:Object.fromEntries(remaining)});
    }
    rowInfo(i){
        const form=this.form(),line=this.doc().bom.lines[i],choice=form.matches[i]||{};
        const library=this.doc().library;
        let code=choice.code||line.code;
        const alias=code.trim().toLowerCase();
        const candidates=!Object.hasOwn(library,code) && !choice.code ? Object.entries(library).filter(([,model])=>model.aliases?.some(value=>value.trim().toLowerCase()===alias)) : [];
        if (candidates.length===1) code=candidates[0][0];
        const model=Object.hasOwn(library,code) ? library[code] : null;
        const face=choice.face||line.face||model?.face;
        const placed=form.instances.filter(a=>a.row===i && a.code===code&&a.face===face).length;
        const validFace=model && this.mountingFaces(model).includes(face);
        const wrongKind=model?.cabinetKinds && !model.cabinetKinds.includes(form.kind);
        const status=!model?(candidates.length>1?"有多个匹配":"待匹配"):wrongKind?"柜型不符":!validFace?"待选安装面":placed===line.quantity&&!this.dirty()?"已装配":"待装配";
        return {code,model,face,placed,validFace,status};
    }
    assemblyPositions(i,row,line){
        if (!row.validFace || row.status==="柜型不符" || !["step","lock"].includes(row.model.kind) || line.quantity>row.model.maxQuantity) return [];
        const f=this.form(), placement=row.model.placement ?? {};
        return Array.from({length:line.quantity},(_,n)=>{
            const id=`a${i+1}n${n+1}`;
            const saved=f.instances.find(item=>item.id===id && item.face===row.face && item.code===row.code);
            const initial={id,rotation:0};
            for (const axis of ["u","v"]) {
                initial[axis]=line.quantity===1 || placement.spacing ? (placement[axis] ?? 0)+n*(placement.spacing?.[axis] ?? 0) : null;
            }
            return {...initial,...saved,...f.assembly_positions[id]};
        });
    }
    position(a,key,ev){
        const location={u:a.u,v:a.v,rotation:a.rotation,[key]:fieldNumber(ev.target.value)};
        this.patch({assembly_positions:{...this.form().assembly_positions,[a.id]:location}});
    }
    setFace(value) {
        if (value === this.face()) return;
        this.endHoleInput();
        this.holeDrafts.set(this.face(), this.holeDraft());
        this.face.set(value);
        this.holeDraft.set(this.holeDrafts.get(value) ?? freshHoleDraft(value));
        this.frontFacesOpen.set(false);
        this.faceView?.fit();
    }
    hole() { return this.holeDraft().values; }
    editing() { return this.holeDraft().editing; }
    holeGeometryReady(mesh = this.displayMesh()) {
        return !!mesh && this.dims.every(([key]) => mesh.dimensions[key] === this.form()[key]) &&
            sameThickness(mesh.parameters.thickness ?? {}, this.form().thickness ?? {});
    }
    holeBasis(axis) { return this.holeBases()[this.face()]?.[axis] ?? "start"; }
    setHoleBasis(axis, basis) {
        this.endHoleInput();
        const face = this.face(), bases = this.holeBases();
        this.holeBases.set({...bases, [face]: {...bases[face], [axis]:basis}});
    }
    holeValue(axis) { return holeCoordinate(this.hole()[axis], this.board(), axis, this.holeBasis(axis)); }
    setHoleValue(axis, text) {
        this.setHole(axis, holeCoordinate(fieldNumber(text), this.board(), axis, this.holeBasis(axis), true), axis);
    }
    setHoleSize(key, text) {
        this.setHole(key, fieldNumber(text), key);
    }
    centerHole(axis) {
        if (!this.holeGeometryReady()) return;
        const size = axis === "u" ? this.board().width : this.board().height;
        this.setHole(axis, size / 2);
    }
    setHole(key, value, input = null) {
        if (this.busy() || this.hole()[key] === value) return;
        this.recordHoleChange(() => this.changeHoleDraft({[key]:value}), input);
    }
    changeHoleDraft(values) {
        const draft = this.holeDraft();
        if (this.drilling() && !this.drillFace()) this.drillFace.set(this.face());
        this.holeDraft.set({...draft, values:{...draft.values,...values}, active:true});
        this.drillNotice.set("");
    }
    attachmentHole(id) { return (this.displayMesh()?.parameters?.holes ?? []).some(hole => hole.id === id && linkedHole(hole)); }
    holeIssue() {
        if (!this.holeGeometryReady() || !this.board()) return "请先保存并预览当前规格。";
        if (this.drilling() && !this.holeDraft().active) return "请在板面定位孔位。";
        const hole = this.hole(), editing = this.editing(), rows = this.boardHoles();
        if (editing && this.attachmentHole(editing)) return "此孔属于附件，请在装配中调整。";
        if (!holeDimensionsReady(hole)) return "请输入完整的孔中心坐标和有效尺寸。";
        if (!editing && this.form().holes.length >= 300) return "单柜自定义孔已达 300 个。";
        const duplicate = rows.find(row => row.id !== editing && sameHole(row, hole));
        if (duplicate) return `与 ${duplicate.id} 位置、孔型和尺寸相同，请调整孔位。`;
        const mesh = this.displayMesh(), board = this.board();
        const linked = (mesh.parameters.holes ?? []).filter(row => row.face === hole.face && linkedHole(row));
        const shapes = window.nodoDrawAE0573;
        const placement = shapes?.checkHolePlacement?.(hole, board, [...rows, ...linked], editing);
        if (placement) return placement;
        if (shapes?.cutPoints && conflictsWithPlate(mesh, board, hole, shapes)) return "孔轮廓与原图开孔或板件边界相交。";
        return "";
    }
    holeOverlay(mesh) {
        if (this.tab() !== "holes" || !this.holeGeometryReady(mesh) || !this.board()) return null;
        const draft = this.holeDraft();
        const active = draft.active && holeDimensionsReady(draft.values)
            ? {...draft.values, id:draft.editing ?? ""} : null;
        return {holes:this.boardHoles(), active, editing:draft.editing, issue:active ? this.holeIssue() : ""};
    }
    setHoleRecords(holes) {
        if (holes !== this.form().holes) this.form.set({...this.form(), holes});
        this.issue.set("");
    }
    captureHoles() {
        return {face:this.face(), drillFace:this.drillFace(), draft:this.holeDraft(), drafts:new Map(this.holeDrafts), holes:this.form().holes};
    }
    endHoleInput() { this.holeInput = null; }
    resetHoleHistory() {
        this.endHoleInput();
        this.holeHistory.set({undo:[], redo:[]});
    }
    recordHoleChange(change, input = null) {
        const before = this.captureHoles();
        const {undo} = this.holeHistory();
        const coalesce = input !== null && input === this.holeInput && undo.length;
        change();
        const entry = {before:coalesce ? undo.at(-1).before : before, after:this.captureHoles()};
        this.holeHistory.set({undo:[...(coalesce ? undo.slice(0, -1) : undo), entry], redo:[]});
        this.holeInput = input;
    }
    travelHoleHistory(direction) {
        if (this.busy()) return;
        const history = this.holeHistory(), entry = history[direction].at(-1);
        if (!entry) return;
        const undoing = direction === "undo", other = undoing ? "redo" : "undo";
        const target = undoing ? entry.before : entry.after;
        const switchFace = target.face !== this.face();
        this.setHoleRecords(target.holes);
        if (this.drilling()) {
            if (switchFace || this.boardView()?.face !== target.face) this.returnToCabinet();
            this.drillFace.set(target.drillFace ?? (target.draft.active ? target.face : null));
            this.drillNotice.set("");
        }
        this.face.set(target.face);
        this.holeDraft.set(target.draft);
        this.holeDrafts = new Map(target.drafts);
        this.holeHistory.set({[direction]:history[direction].slice(0, -1), [other]:[...history[other], entry]});
        this.endHoleInput();
        if (switchFace) this.faceView?.fit();
    }
    addHole() {
        if (this.busy() || this.holeIssue()) return;
        const values = this.hole(), draft = this.holeDraft(), holes = this.form().holes;
        const original = holes.find(row => row.id === draft.editing);
        const id = original?.id ?? "H" + (Math.max(0, ...holes.map(row => Number(row.id.slice(1)))) + 1);
        const row = holeRecord(values, id);
        this.recordHoleChange(() => {
            if (!original || !sameHole(original, row)) {
                this.setHoleRecords(original ? holes.map(item => item.id === id ? row : item) : [...holes, row]);
            }
            this.holeDraft.set({...draft, editing:null, copiedFrom:null, active:false});
        });
        this.clearHoleNotice();
    }
    editHole(row, asCopy = false) {
        if (this.busy() || this.attachmentHole(row.id)) return;
        const select = () => {
            this.setFace(row.face);
            this.holeDraft.set({values:{...defaultHole(row.face), ...row}, active:true,
                editing:asCopy ? null : row.id, copiedFrom:asCopy ? row.id : null});
        };
        if (asCopy) this.recordHoleChange(select);
        else { this.endHoleInput(); select(); }
    }
    cancelHoleDraft() {
        if (this.busy()) return;
        this.recordHoleChange(() => this.holeDraft.set(freshHoleDraft(this.face())));
        this.clearHoleNotice();
    }
    clearHoleNotice() {
        this.drillNotice.set("");
        if (this.issue() === pendingHoleNotice) this.issue.set("");
    }
    removeHole(id) {
        if (this.busy() || this.attachmentHole(id)) return;
        this.recordHoleChange(() => {
            this.setHoleRecords(this.form().holes.filter(hole => hole.id !== id));
            if (this.editing() === id) this.holeDraft.set(freshHoleDraft(this.face()));
        });
    }
    pickExistingHole(id) {
        if (this.busy() || !this.drilling()) return false;
        const row = this.form().holes.find(hole => hole.id === id);
        if (!row) return false;
        if (this.attachmentHole(id)) {
            this.drillNotice.set("此处是附件关联孔位，请在装配中调整。");
            return false;
        }
        const switching = row.face !== this.face();
        if (!switching && this.holeDraft().active && this.editing() !== id) {
            this.drillNotice.set(pendingHoleNotice);
            return false;
        }
        const select = () => {
            this.selectBoard(row.face);
            if (this.editing() !== id) this.editHole(row);
        };
        if (switching) this.recordHoleChange(select);
        else select();
        return true;
    }
    pickDrill(plane, surface, obstructed) {
        if (!this.drilling() || this.busy() || !this.holeGeometryReady()) return;
        if (!plane) {
            this.drillNotice.set("请点击模型上可见的加工板面。");
            return;
        }
        const face = this.board(plane.face), mesh = this.displayMesh(), shapes = window.nodoDrawAE0573;
        const reserved = openingAt(mesh, face, plane, shapes);
        if (reserved) {
            this.selectBoard(face.id);
            this.drillNotice.set(reserved);
            return;
        }
        const onFace = surface?.face === face.id;
        if (obstructed && !onFace) {
            this.drillNotice.set("当前板面被遮挡，可旋转柜体或正对板面查看。");
            return;
        }
        const point = onFace ? surface : plane;
        const contains = hole => hole.face === face.id && shapes.holeContains(hole, face, point.u, point.v);
        const existing = this.form().holes.find(contains);
        const oldCut = (mesh.parameters.holes ?? []).some(hole => !linkedHole(hole) && /^H\d+$/.test(hole.id) && contains(hole));
        if (!onFace && !existing && !oldCut) {
            const material = faceSurface(mesh, face);
            if (material.triangles.length && !containsMaterial(material, [point.u, point.v])) {
                this.selectBoard(face.id);
                this.drillNotice.set("此处是原图开孔或空白区域，请在有板材的位置开孔。");
            } else {
                this.drillNotice.set("请选择可加工的板件主面。");
            }
            return;
        }
        if (face.id !== this.face() && this.holeDrafts.get(face.id)?.active) {
            this.recordHoleChange(() => this.selectBoard(face.id));
            this.drillNotice.set("已恢复此面的待确认孔位。");
            return;
        }
        if (existing) {
            this.pickExistingHole(existing.id);
            return;
        }
        this.recordHoleChange(() => {
            this.selectBoard(face.id);
            this.changeHoleDraft({face:face.id, u:Number(point.u.toFixed(2)), v:Number(point.v.toFixed(2))});
        });
    }
    moveDrill(u,v) {
        if (!this.drilling() || this.busy() || !this.holeDraft().active || !this.holeGeometryReady() ||
                !Number.isFinite(u) || !Number.isFinite(v) || (this.hole().u === u && this.hole().v === v)) return;
        this.recordHoleChange(() => this.changeHoleDraft({u,v}), "3d-drag");
    }
    builds(){return (this.doc()?.jobs||[]).filter(j=>j.operation==="build");}
    selectedBuild() {
        const builds = this.builds(), id = this.batch();
        return id === null ? builds[0] : builds.find(job => job.id === id);
    }
    selectedDrawing() {
        const reference = this.referenceDrawings()[this.referenceKind()];
        if (!reference) return this.selectedBuild();
        return {...reference, id:`original-${reference.kind}`, reference:true,
            state:reference.sheets.length ? "done" : "unavailable"};
    }
    openArchive() {
        this.closeAccessoryPicker();
        this.returnToCabinet();
        if (!this.selectedBuild()) {
            this.openReference();
            return;
        }
        this.referenceKind.set(null);
        this.batch.set(this.selectedBuild()?.id ?? null);
        this.archiveMenu.set(null);
        this.showFiles.set(true);
    }
    openReference(kind = this.form().kind || "single") {
        this.closeAccessoryPicker();
        this.returnToCabinet();
        this.referenceKind.set(kind);
        this.sheet.set(null);
        this.archiveMode.set("drawing");
        this.archiveMenu.set(null);
        this.showFiles.set(true);
    }
    openDesign() {
        this.archiveMenu.set(null);
        this.showFiles.set(false);
        this.ensureDraftPreview();
    }
    selectDrawingVersion(event) {
        const value = event.target.value;
        if (value.startsWith("original-")) this.openReference(value.slice("original-".length));
        else this.setBuild(Number(value));
    }
    setBuild(id) {
        this.referenceKind.set(null);
        this.batch.set(id);
        this.sheet.set(null);
        this.archiveMenu.set(null);
    }
    selectedSheet(job) {
        return job.sheets.find(sheet => sheet.key === this.sheet()) || job.sheets[0];
    }
    drawingFile(job, sheet, extension) {
        if (job.reference) return `/nodo/draw/reference/${job.kind}/${sheet.key}/${extension}`;
        return this.url(job.id, sheet.key + (extension === "svg" ? "p" : ""));
    }
    drawingView(key) { return this.drawingViews.get(key) || fitView; }
    rememberDrawingView(key, view) { this.drawingViews.set(key, view); }
    toggleArchiveMenu(menu) { this.archiveMenu.set(this.archiveMenu() === menu ? null : menu); }
    dismissArchiveMenu(event) {
        if (this.archiveMenu() && !event.target.closest?.(".nd-workbar .nd-menu")) this.archiveMenu.set(null);
    }
    keyArchiveMenu(event) {
        if (event.key === "Escape" && this.accessoryPicker()) {
            this.closeAccessoryPicker();
            return;
        }
        if (event.key !== "Escape" || !this.archiveMenu()) return;
        document.querySelector('.nd-workbar .nd-menu > button[aria-expanded="true"]')?.focus();
        this.archiveMenu.set(null);
    }
    flatPointerDown(ev){
        if (ev.button !== 0 || this.tab() !== "holes") return;
        this.flatPress = {id: ev.pointerId, x: ev.clientX, y: ev.clientY};
        ev.target.setPointerCapture(ev.pointerId);
    }
    flatPointerUp(ev){
        const start = this.flatPress;
        this.flatPress = null;
        if (!start || start.id !== ev.pointerId || Math.hypot(ev.clientX-start.x, ev.clientY-start.y) > 5) return;
        const rect = ev.target.getBoundingClientRect();
        const point = this.faceView?.pick(ev.clientX - rect.left, ev.clientY - rect.top);
        if (point && !this.busy() && this.holeGeometryReady()) {
            this.recordHoleChange(() => this.changeHoleDraft(point));
        }
    }
}
registry.category("actions").add("nodo_draw.workbench",Workbench);
