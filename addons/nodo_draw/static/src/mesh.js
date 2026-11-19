/** The viewer consumes world-space triangles from the same CAD solids as STEP. */
const STEEL = [155, 174, 179];
const colors = {top:[177,193,196], bottom:STEEL, wrap:STEEL, mount:[158,173,162],
    door:[177,194,193], door_right:[167,188,187]};
const dot = (a,b) => a[0]*b[0]+a[1]*b[1]+a[2]*b[2];
const cross = (a,b) => [a[1]*b[2]-a[2]*b[1], a[2]*b[0]-a[0]*b[2], a[0]*b[1]-a[1]*b[0]];
const sub = (a,b) => a.map((v,i)=>v-b[i]);

// A depth buffer also identifies the surface under the pointer. Sorting whole
// triangles by average depth would show internal hardware through a closed door.
function fillTriangle(buffer,a,b,c,det,color,face){
    const {width,height,pixels,depth,hits}=buffer;
    const xmin=Math.max(0,Math.floor(Math.min(a[0],b[0],c[0])));
    const xmax=Math.min(width-1,Math.ceil(Math.max(a[0],b[0],c[0])));
    const ymin=Math.max(0,Math.floor(Math.min(a[1],b[1],c[1])));
    const ymax=Math.min(height-1,Math.ceil(Math.max(a[1],b[1],c[1])));
    const du=(c[1]-a[1])/det,dv=(a[1]-b[1])/det;
    for(let y=ymin;y<=ymax;y++){
        const dx=xmin+.5-a[0],dy=y+.5-a[1];
        let u=dx*du-dy*(c[0]-a[0])/det;
        let v=dx*dv+dy*(b[0]-a[0])/det;
        for(let x=xmin,pos=y*width+x;x<=xmax;x++,pos++,u+=du,v+=dv){
            if(u<0 || v<0 || u+v>1)continue;
            const z=a[2]+u*(b[2]-a[2])+v*(c[2]-a[2]);
            if(z<=depth[pos])continue;
            depth[pos]=z;pixels[pos]=color;hits[pos]=face;
        }
    }
}

export function facePoint(h, face) {
    return [h.anchor==="center" ? face.width/2+h.u : h.anchor==="right" ? face.width-h.u : h.u,
        h.anchorV==="center" ? face.height/2+h.v : h.anchorV==="top" ? face.height-h.v : h.v];
}

export class CabinetView {
    constructor(canvas) {
        this.canvas=canvas;
        this.context=canvas.getContext("2d");
        this.yaw=.48; this.pitch=.25; this.zoom=1;
        this.frame=0; this.facets=[];
        this.resize=new ResizeObserver(()=>this.schedule());
        this.resize.observe(canvas);
    }
    dispose() { this.resize.disconnect(); cancelAnimationFrame(this.frame); }
    set(mesh, display) { this.mesh=mesh; this.display=display; this.schedule(); }
    schedule() {
        cancelAnimationFrame(this.frame);
        this.frame=requestAnimationFrame(()=>this.paint());
    }
    fit() { this.zoom=1; this.yaw=.48; this.pitch=.25; this.schedule(); }
    drag(dx,dy) {
        this.yaw-=dx*.009;
        this.pitch=Math.max(-1.3,Math.min(1.3,this.pitch+dy*.007));
        this.schedule();
    }
    scale(delta) { this.zoom=Math.max(.5,Math.min(3,this.zoom*Math.exp(-delta*.0013))); this.schedule(); }
    paint() {
        const c=this.canvas, ctx=this.context;
        const w=c.clientWidth, h=c.clientHeight;
        if (!w || !h) return;
        const d=Math.max(1.25,Math.min(window.devicePixelRatio||1,1.5));
        if (c.width!==Math.round(w*d) || c.height!==Math.round(h*d)) {
            c.width=Math.round(w*d); c.height=Math.round(h*d);
        }
        ctx.setTransform(d,0,0,d,0,0);ctx.clearRect(0,0,w,h);
        if (!this.mesh || !this.display) return;
        if (this.display.mode==="2d") { this.paintFace(w,h); return; }
        const {width}=this.mesh.dimensions;
        const right=[Math.cos(this.yaw),Math.sin(this.yaw),0];
        const front=[right[1]*Math.cos(this.pitch),-right[0]*Math.cos(this.pitch),Math.sin(this.pitch)];
        const up=cross(front,right);
        const cameraParts=this.mesh.parts.map(part=>{
            const moving=this.display.open && ["door","door_right"].includes(part.group);
            const sign=part.group==="door_right"?1:-1;
            const originX=sign===1?width-this.mesh.hinge[0]:this.mesh.hinge[0];
            const originY=this.mesh.hinge[1],angle=moving?sign*1.2:0,cs=Math.cos(angle),sn=Math.sin(angle);
            function rotate([x,y,z]){
                if(!moving)return [x,y,z];
                return [originX+(x-originX)*cs-(y-originY)*sn,originY+(x-originX)*sn+(y-originY)*cs,z];
            }
            return {part,rotate,cs,sn};
        });
        let left=Infinity,bottom=Infinity,rightmost=-Infinity,top=-Infinity;
        for(const {part,rotate} of cameraParts){
            const [lo,hi]=part.bounds;
            for(const x of [lo[0],hi[0]])for(const y of [lo[1],hi[1]])for(const z of [lo[2],hi[2]]){
                const point=rotate([x,y,z]),u=dot(point,right),v=dot(point,up);
                left=Math.min(left,u);rightmost=Math.max(rightmost,u);bottom=Math.min(bottom,v);top=Math.max(top,v);
            }
        }
        const size=Math.min(c.width*.83/(rightmost-left),c.height*.77/(top-bottom))*this.zoom;
        const centerX=(rightmost+left)/2,centerY=(top+bottom)/2;
        if(this.buffer?.width!==c.width || this.buffer?.height!==c.height){
            const data=ctx.createImageData(c.width,c.height);
            this.buffer={width:c.width,height:c.height,data,pixels:new Uint32Array(data.data.buffer),
                depth:new Float32Array(c.width*c.height),hits:new Int32Array(c.width*c.height)};
        }
        const buffer=this.buffer;
        buffer.pixels.fill(0);buffer.depth.fill(-Infinity);buffer.hits.fill(0);
        const faces=[];
        for(const {part,rotate,cs,sn} of cameraParts){
            const vertices=part.vertices.map(vertex=>{
                const v=rotate(vertex);
                return [c.width/2+(dot(v,right)-centerX)*size,c.height*.49-(dot(v,up)-centerY)*size,dot(v,front)];
            });
            const base=part.accessoryId?[186,119,62]:(colors[part.id]||[116,131,138]);
            for (const [i,j,k] of part.triangles) {
                const a=vertices[i],b=vertices[j],third=vertices[k];
                const signed=(b[0]-a[0])*(third[1]-a[1])-(b[1]-a[1])*(third[0]-a[0]);
                if(signed>=-.01)continue;
                const n=cross(sub(part.vertices[j],part.vertices[i]),sub(part.vertices[k],part.vertices[i]));
                const length=Math.hypot(...n)||1;
                const normal=[n[0]*cs-n[1]*sn,n[0]*sn+n[1]*cs,n[2]];
                const light=.83+.23*dot(normal,[-.28,-.58,.76])/length;
                const [r,g,bv]=base.map(x=>Math.min(255,Math.round(x*light)));
                const color=(255<<24)|(bv<<16)|(g<<8)|r;
                faces.push({id:part.id,n});
                fillTriangle(buffer,a,b,third,signed,color,faces.length);
            }
        }
        ctx.putImageData(buffer.data,0,0);
        this.facets=faces;
    }
    paintFace(w,h) {
        const ctx=this.context,f=this.mesh.faces.find(x=>x.id===this.display.face);
        this.flat=null;
        if (!f) return;
        const s=Math.min((w-88)/f.width,(h-92)/f.height)*Math.min(1.4,this.zoom);
        const x=(w-f.width*s)/2,y=(h+f.height*s)/2;
        this.flat={x,y,s,face:f};
        const part=this.mesh.parts.find(p=>p.id===f.part);
        const surface=new Path2D();
        let triangles=0;
        if(part){
            const projected=part.vertices.map(vertex=>{
                const delta=sub(vertex,f.origin);
                return {x:x+dot(delta,f.uAxis)*s,y:y-dot(delta,f.vAxis)*s,height:dot(delta,f.normal)};
            });
            for(const indices of part.triangles){
                const [a,b,c]=indices.map(i=>projected[i]);
                if([a,b,c].some(p=>Math.abs(p.height)>.02))continue;
                surface.moveTo(a.x,a.y);surface.lineTo(b.x,b.y);surface.lineTo(c.x,c.y);surface.closePath();
                triangles++;
            }
        }
        const steel="#c3d7cc";
        ctx.fillStyle=steel;
        if(triangles)ctx.fill(surface);
        ctx.strokeStyle="#58816f";ctx.lineWidth=1;ctx.setLineDash([4,4]);
        ctx.strokeRect(x,y-f.height*s,f.width*s,f.height*s);ctx.setLineDash([]);
        const outline=(hole,pad=0)=>{
            const [u,v]=facePoint(hole,f),px=x+u*s,py=y-v*s;
            ctx.beginPath();
            if(hole.type==="circle")ctx.arc(px,py,hole.diameter*s/2+pad,0,2*Math.PI);
            else ctx.roundRect(px-hole.width*s/2-pad,py-hole.height*s/2-pad,hole.width*s+2*pad,hole.height*s+2*pad,
                hole.type==="slot"?Math.min(hole.width,hole.height)*s/2+pad:0);
        };
        // Restore the last saved user cuts before overlaying the edited positions.
        // Structural openings remain those of the actual planar CAD face.
        for(const cut of this.mesh.parameters.holes||[]){
            if(cut.face===f.id && !cut.ownerAccessory && /^H\d+$/.test(cut.id)){
                outline(cut,.4);ctx.fill();
            }
        }
        const holes=[...(this.mesh.parameters.holes||[]).filter(h=>h.ownerAccessory),...this.display.holes];
        for (const hole of holes.filter(h=>h.face===f.id)) {
            ctx.strokeStyle=hole.ownerAccessory?"#a36732":"#116857";ctx.fillStyle="#f8fbf9";
            outline(hole);
            ctx.fill();ctx.stroke();
        }
        ctx.fillStyle="#45635c";ctx.font="12px sans-serif";ctx.textAlign="center";
        ctx.fillText(f.width.toFixed(1)+" mm",w/2,y+22);
        ctx.textAlign="left";ctx.fillText("U →   V ↑",x,y-f.height*s-12);
        ctx.fillText(f.height.toFixed(1)+" mm",x+4,y-7);
    }
    pick(x,y) {
        if (this.display?.mode==="2d" && this.flat) {
            const f=this.flat,u=(x-f.x)/f.s,v=(f.y-y)/f.s;
            if (u>=0&&u<=f.face.width&&v>=0&&v<=f.face.height) return {face:f.face.id,u:+u.toFixed(2),v:+v.toFixed(2)};
        } else if(this.mesh && this.buffer) {
            const px=Math.floor(x*this.buffer.width/this.canvas.clientWidth);
            const py=Math.floor(y*this.buffer.height/this.canvas.clientHeight);
            const tri=this.facets[this.buffer.hits[py*this.buffer.width+px]-1];
            if(tri){
                const list=this.mesh.faces.filter(f=>f.part===tri.id);
                if (!list.length) return null;
                list.sort((a,b)=>dot(b.normal,tri.n)-dot(a.normal,tri.n));
                return {face:list[0].id};
            }
        }
        return null;
    }
}
