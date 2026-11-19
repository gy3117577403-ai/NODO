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
    pick(x, y) {
        if (!this.flat) return null;
        const {x: left, y: bottom, s, face} = this.flat;
        const u = (x - left) / s, v = (bottom - y) / s;
        if (u < 0 || u > face.width || v < 0 || v > face.height) return null;
        return {face: face.id, u: +u.toFixed(2), v: +v.toFixed(2)};
    }
}
