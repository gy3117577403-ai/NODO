import {Component, signal, onWillStart, onWillUnmount, untrack, useEffect, useProps} from "@odoo/owl";
import {registry} from "@web/core/registry";
import {useService} from "@web/core/utils/hooks";
import {standardActionServiceProps} from "@web/webclient/actions/action_plugin";
import {useSetupAction} from "@web/search/action_hook";
import {CabinetView} from "./mesh";

const MODEL="nodo.draw.design";
const faceNames={door:"门板",door_right:"右门板",top:"顶板",bottom:"底板",back:"围板背面",left:"左侧板",right:"右侧板",mount:"安装板"};
const docTypes={assembly:"总装",formed:"成形",flat:"展开",weld:"焊接",bom:"零件明细",schedule:"孔位表"};
const clone=value=>JSON.parse(JSON.stringify(value));
const fieldNumber=(v)=>v===""?null:Number(v);

export class Workbench extends Component {
    static template="nodo_draw.Workbench";
    props=useProps({...standardActionServiceProps});
    docs=signal([]); doc=signal(null); form=signal(null); tab=signal("cabinet");
    dirty=signal(false); busy=signal(false); issue=signal(""); mesh=signal(null);
    modelJob=signal(null); mode=signal("3d"); opened=signal(false); face=signal("door");
    hole=signal({type:"circle",face:"door",u:95,v:110,diameter:18,width:40,height:24});
    editing=signal(null); batch=signal(null); sheet=signal(null); showFiles=signal(false);
    canvas=signal.ref();
    setup(){
        this.orm=useService("orm"); this.notification=useService("notification");
        this.epoch=0;this.faceNames=faceNames;this.docTypes=docTypes;
        this.dims=[["width","宽"],["height","高"],["depth","深"]];
        this.gauges=[["body","箱体"],["door","门板"],["mount","安装板"]];
        this.tabs=[["cabinet","柜体规格"],["assembly","附件装配"],["holes","自定义孔"]];
        useSetupAction({beforeLeave:()=>!this.dirty()||window.confirm("离开并放弃未保存的设计修改？")});
        onWillStart(async()=>{
            this.docs.set(await this.orm.call(MODEL,"list_designs",[]));
            if(this.docs().length) await this.loadDesign(this.docs()[0].id);
        });
        useEffect(()=>{
            const canvas=this.canvas();
            if(!canvas) return;
            const view=new CabinetView(canvas); this.viewer=view;
            untrack(()=>view.set(this.mesh(),this.display()));
            return ()=>{view.dispose();if(this.viewer===view)this.viewer=null;};
        });
        useEffect(()=>{
            const data=this.mesh(), display=this.display();
            if(this.viewer)this.viewer.set(data,display);
        });
        onWillUnmount(()=>{this.epoch++;clearTimeout(this.poll);this.aborter?.abort();});
    }
    display(){return {mode:this.mode(),open:this.opened(),face:this.face(),holes:this.form()?.holes||[]};}
    url(id,key){return "/nodo/draw/file/"+id+"/"+key;}
    version(value){return String(value).padStart(2,"0");}
    jobState(job){return {done:"已生成",failed:"生成失败",queued:"等待计算",running:"计算中"}[job.state];}
    faces(){ return Object.entries(faceNames).filter(([id])=>id!=="door_right"||this.form()?.kind==="double"); }
    mountingFaces(model){
        return (model.faces||[model.face]).filter(face=>face!=="door_right"||this.form().kind==="double");
    }
    async selectDesign(event){
        const current=this.doc().id, select=event.target;
        const chosen=Number(select.value);
        select.value=String(current);
        await this.loadDesign(chosen);
    }
    async loadDesign(id){
        if(this.dirty()&&!window.confirm("切换柜体并放弃未保存的修改？")) return;
        clearTimeout(this.poll);this.aborter?.abort();this.mesh.set(null);this.modelJob.set(null);
        this.meshRequest=null;this.issue.set("");this.dirty.set(false);this.sheet.set(null);
        this.showFiles.set(false);this.batch.set(null);this.editing.set(null);this.face.set("door");
        this.hole.set({...this.hole(),face:"door"});this.busy.set(false);
        const epoch=++this.epoch;
        await this.refresh(id,epoch,true);
    }
    async refresh(id,epoch,replace=false){
        clearTimeout(this.poll);
        const data=await this.orm.call(MODEL,"workspace",[[id]]);
        if(epoch!==this.epoch)return;
        this.doc.set(data);
        if(replace){this.form.set({...clone(data.settings),positions:{}});this.localEdit=data.edit_number;this.dirty.set(false);}
        const current=data.jobs.find(j=>j.state==="done"&&j.files?.includes("mesh"));
        if(current&&this.modelJob()?.id!==current.id&&this.meshRequest!==current.id){
            this.meshRequest=current.id;
            this.aborter?.abort();this.aborter=new AbortController();
            fetch(this.url(current.id,"mesh"),{signal:this.aborter.signal}).then(async response=>{
                if(!response.ok)throw Error("三维模型读取失败");
                const mesh=await response.json();
                if(epoch===this.epoch&&this.meshRequest===current.id){this.mesh.set(mesh);this.modelJob.set(current);}
            }).catch(err=>{if(err.name!=="AbortError"&&epoch===this.epoch){this.issue.set(err.message);this.meshRequest=null;}});
        }
        const latest=data.jobs[0];
        if(latest?.state==="failed")this.issue.set(latest.error);
        if(latest?.issues?.length)this.issue.set(latest.issues.join(" · "));
        if(data.jobs.some(job=>["queued","running"].includes(job.state))){
            this.poll=setTimeout(()=>this.refresh(id,epoch).catch(e=>this.issue.set(e.message)),1600);
        }
    }
    patch(p){this.form.set({...this.form(),...p});this.dirty.set(true);this.issue.set("");}
    changeField(key,ev,numeric=false){this.patch({[key]:numeric?fieldNumber(ev.target.value):ev.target.value});}
    selectTab(id){this.tab.set(id); this.showFiles.set(false);if(id==="holes")this.mode.set("2d");else this.mode.set("3d");}
    async apply(operation){
        if(this.busy())return;
        this.busy.set(true);this.issue.set("");
        try{
            const doc=this.doc();
            const out=await this.orm.call(MODEL,"apply_design",[[doc.id],this.localEdit,this.form(),operation]);
            await this.refresh(doc.id,this.epoch,true);
            if(out.issues.length)this.issue.set(out.issues.join(" · "));
            if(operation==="generate"){this.batch.set(null);this.sheet.set(null);this.showFiles.set(true);}
            if(operation==="assemble"){this.tab.set("assembly");this.mode.set("3d");}
        }catch(e){this.issue.set(e.data?.message||e.message);}
        finally{this.busy.set(false);}
    }
    links(i,k,val){
        const f=this.form(),matches={...f.matches,[i]:{...f.matches[i],[k]:val}};
        this.patch({matches});
    }
    rowInfo(i){
        const form=this.form(),line=this.doc().bom.lines[i],choice=form.matches[i]||{};
        const code=choice.code||line.code,model=this.doc().library[code];
        const face=choice.face||line.face||model?.face;
        const placed=form.instances.filter(a=>a.row===i && a.code===code&&a.face===face).length;
        const validFace=model && this.mountingFaces(model).includes(face);
        const status=!model?"待匹配":!validFace?"待选安装面":placed===line.quantity?"已装配":"待装配";
        return {code,model,face,placed,validFace,status};
    }
    position(a,key,ev){
        const positions={...this.form().positions},p={u:a.u,v:a.v,rotation:a.rotation,...positions[a.id]};
        positions[a.id]={...p,[key]:fieldNumber(ev.target.value)};this.patch({positions});
    }
    setFace(value){this.face.set(value);this.hole.set({...this.hole(),face:value});}
    setHole(key,value){this.hole.set({...this.hole(),[key]:value});}
    addHole(){
        const item=this.hole(),holes=clone(this.form().holes),edit=this.editing();
        const id=edit||"H"+(Math.max(0,...holes.map(h=>Number(h.id.slice(1))))+1);
        const row={...item,id};
        if(edit)holes[holes.findIndex(h=>h.id===edit)]=row;
        else holes.push(row);
        this.patch({holes});this.editing.set(null);this.mode.set("2d");
    }
    editHole(row){this.editing.set(row.id);this.hole.set({...row});this.face.set(row.face);}
    removeHole(id){this.patch({holes:this.form().holes.filter(h=>h.id!==id)});if(this.editing()===id)this.editing.set(null);}
    builds(){return (this.doc()?.jobs||[]).filter(j=>j.operation==="build");}
    selectedBuild(){return this.builds().find(j=>j.id===this.batch())||this.builds()[0];}
    pointerDown(ev){this.drag={x:ev.clientX,y:ev.clientY,startX:ev.clientX,startY:ev.clientY};ev.target.setPointerCapture(ev.pointerId);}
    pointerMove(ev){if(!this.drag)return;const d=this.drag;if(this.mode()==="3d")this.viewer?.drag(ev.clientX-d.x,ev.clientY-d.y);d.x=ev.clientX;d.y=ev.clientY;}
    pointerUp(ev){
        const d=this.drag;this.drag=null;if(!d||Math.hypot(ev.clientX-d.startX,ev.clientY-d.startY)>5)return;
        const r=ev.target.getBoundingClientRect(),point=this.viewer?.pick(ev.clientX-r.left,ev.clientY-r.top);
        if(!point)return;
        this.tab.set("holes");this.setFace(point.face);this.mode.set("2d");
        if("u" in point)this.hole.set({...this.hole(),u:point.u,v:point.v});
    }
}
registry.category("actions").add("nodo_draw.workbench",Workbench);
