/** Planar editor in CAD face coordinates (millimetres). */
const dot = (a, b) => a[0]*b[0] + a[1]*b[1] + a[2]*b[2];
const sub = (a, b) => a.map((value, index) => value - b[index]);

export function facePoint(h, face) {
    return [h.anchor==="center" ? face.width/2+h.u : h.anchor==="right" ? face.width-h.u : h.u,
        h.anchorV==="center" ? face.height/2+h.v : h.anchorV==="top" ? face.height-h.v : h.v];
}

export class FaceCanvas {
    constructor(canvas) {
        this.canvas = canvas;
        this.context = canvas.getContext("2d");
        this.zoom = 1;
        this.frame = 0;
        this.resize = new ResizeObserver(() => this.schedule());
        this.resize.observe(canvas);
    }
    dispose() {
        this.resize.disconnect();
        cancelAnimationFrame(this.frame);
    }
    set(mesh, display) {
        this.mesh = mesh;
        this.display = display;
        this.flat = null;
        this.schedule();
    }
    schedule() {
        cancelAnimationFrame(this.frame);
        this.frame = requestAnimationFrame(() => {
            const w = this.canvas.clientWidth, h = this.canvas.clientHeight;
            if (!w || !h) return;
            const ratio = Math.max(1, Math.min(window.devicePixelRatio || 1, 2));
            this.canvas.width = Math.round(w * ratio);
            this.canvas.height = Math.round(h * ratio);
            this.context.setTransform(ratio, 0, 0, ratio, 0, 0);
            if (this.mesh) this.paintFace(w, h);
        });
    }
    fit() {
        this.zoom = 1;
        this.schedule();
    }
    scale(delta) {
        this.zoom = Math.max(.5, Math.min(1.4, this.zoom * Math.exp(-delta * .0013)));
        this.schedule();
    }
    projectFace(f,x,y,s) {
        const cached = this.projection;
        if (cached?.mesh === this.mesh && cached.face === f && cached.x === x && cached.y === y && cached.scale === s) {
            return cached;
        }
        const part=this.mesh.parts.find(p=>p.id===f.part);
        const surface=new Path2D(), boundary=new Path2D(), edges=new Map();
        let triangles=0;
        if(part){
            const projected=part.vertices.map(vertex=>{
                const delta=sub(vertex,f.origin);
                const u=dot(delta,f.uAxis), v=dot(delta,f.vAxis);
                return {x:x+u*s,y:y-v*s,height:dot(delta,f.normal),
                    key:Math.round(u*1000)+"/"+Math.round(v*1000)};
            });
            for(const indices of part.triangles){
                const [a,b,c]=indices.map(i=>projected[i]);
                if([a,b,c].some(p=>Math.abs(p.height)>.02))continue;
                surface.moveTo(a.x,a.y);surface.lineTo(b.x,b.y);surface.lineTo(c.x,c.y);surface.closePath();
                for (const [start,end] of [[a,b],[b,c],[c,a]]) {
                    const key = start.key < end.key ? start.key+"|"+end.key : end.key+"|"+start.key;
                    if (edges.has(key)) edges.get(key).count++;
                    else edges.set(key,{start,end,count:1});
                }
                triangles++;
            }
        }
        for (const {start,end,count} of edges.values()) {
            if (count !== 1) continue;
            boundary.moveTo(start.x,start.y);
            boundary.lineTo(end.x,end.y);
        }
        return this.projection = {mesh:this.mesh, face:f, x, y, scale:s, surface, boundary, triangles};
    }
    paintFace(w,h) {
        const ctx=this.context,f=this.mesh.faces.find(x=>x.id===this.display.face);
        this.flat=null;
        if (!f) return;
        const s=Math.min((w-88)/f.width,(h-92)/f.height)*Math.min(1.4,this.zoom);
        const x=(w-f.width*s)/2,y=(h+f.height*s)/2;
        this.flat={x,y,s,face:f};
        const {surface,boundary,triangles}=this.projectFace(f,x,y,s);
        const steel="#fff";
        ctx.fillStyle=steel;
        if(triangles){
            ctx.fill(surface);
            ctx.strokeStyle="#53665f";ctx.lineWidth=1;
            ctx.stroke(boundary);
        }
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
                outline(cut,.8);ctx.fill();
            }
        }
        const holes=[...(this.mesh.parameters.holes||[]).filter(h=>h.ownerAccessory),...this.display.holes];
        for (const hole of holes.filter(h=>h.face===f.id)) {
            if (this.display.active && hole.id === this.display.editing) continue;
            ctx.strokeStyle=hole.ownerAccessory?"#a36732":"#116857";ctx.fillStyle="#f8fbf9";
            outline(hole);
            ctx.fill();ctx.stroke();
        }
        const active = this.display.active;
        if (active?.face === f.id) {
            ctx.strokeStyle = this.display.issue ? "#a13530" : "#a56614";
            ctx.fillStyle = this.display.issue ? "#f8d9d480" : "#fbe4b780";
            ctx.setLineDash([4,3]);
            outline(active);
            ctx.fill();ctx.stroke();
            ctx.setLineDash([]);
            const [u,v] = facePoint(active,f), px=x+u*s, py=y-v*s;
            ctx.beginPath();ctx.moveTo(px-5,py);ctx.lineTo(px+5,py);ctx.moveTo(px,py-5);ctx.lineTo(px,py+5);ctx.stroke();
        }
        const ax=x-12, ay=y+12;
        ctx.beginPath();
        ctx.moveTo(ax,ay-22);ctx.lineTo(ax,ay);ctx.lineTo(ax+22,ay);
        ctx.moveTo(ax-3,ay-17);ctx.lineTo(ax,ay-22);ctx.lineTo(ax+3,ay-17);
        ctx.moveTo(ax+17,ay-3);ctx.lineTo(ax+22,ay);ctx.lineTo(ax+17,ay+3);
        ctx.strokeStyle="#45635c";ctx.lineWidth=1;ctx.stroke();
        ctx.fillStyle="#45635c";ctx.font="12px sans-serif";ctx.textAlign="left";
        ctx.fillText("V",ax-4,ay-26);ctx.fillText("U",ax+27,ay+4);ctx.fillText("0",ax-10,ay+11);
    }
    pick(x, y) {
        if (!this.flat) return null;
        const {x: left, y: bottom, s, face} = this.flat;
        const u = (x - left) / s, v = (bottom - y) / s;
        if (u < 0 || u > face.width || v < 0 || v > face.height) return null;
        return {face: face.id, u: +u.toFixed(2), v: +v.toFixed(2)};
    }
}
