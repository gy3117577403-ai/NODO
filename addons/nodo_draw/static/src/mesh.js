/** Planar editor in CAD face coordinates (millimetres). */
const dot = (a, b) => a[0]*b[0] + a[1]*b[1] + a[2]*b[2];
const sub = (a, b) => a.map((value, index) => value - b[index]);
const surfaces = new WeakMap();

export function facePoint(h, face) {
    return [h.anchor==="center" ? face.width/2+h.u : h.anchor==="right" ? face.width-h.u : h.u,
        h.anchorV==="center" ? face.height/2+h.v : h.anchorV==="top" ? face.height-h.v : h.v];
}

export function faceSurface(mesh, face) {
    if (!surfaces.has(mesh)) surfaces.set(mesh, new Map());
    const cache = surfaces.get(mesh);
    if (cache.has(face.id)) return cache.get(face.id);
    const part = mesh.parts.find(item => item.id === face.part);
    const projected = (part?.vertices ?? []).map(vertex => {
        const delta = sub(vertex, face.origin);
        const u = dot(delta, face.uAxis), v = dot(delta, face.vAxis);
        return {uv: [u, v], depth: dot(delta, face.normal), key: `${Math.round(u*1000)}/${Math.round(v*1000)}`};
    });
    const triangles = [], edges = new Map();
    for (const indices of part?.triangles ?? []) {
        const [a,b,c] = indices.map(index => projected[index]);
        if ([a,b,c].some(point => Math.abs(point.depth) > .02)) continue;
        const [[ax,ay],[bx,by],[cx,cy]] = [a.uv,b.uv,c.uv];
        if (Math.abs((bx-ax)*(cy-ay)-(by-ay)*(cx-ax)) < 1e-9) continue;
        triangles.push([a.uv,b.uv,c.uv]);
        for (const [start,end] of [[a,b],[b,c],[c,a]]) {
            const key = start.key < end.key ? `${start.key}|${end.key}` : `${end.key}|${start.key}`;
            if (!edges.has(key)) edges.set(key, {points:[start.uv,end.uv], count:0});
            edges.get(key).count++;
        }
    }
    const boundary = [...edges.values()].filter(edge => edge.count === 1).map(edge => edge.points);
    const surface = {triangles, boundary};
    cache.set(face.id, surface);
    return surface;
}

export function containsMaterial(surface, [u,v]) {
    const side = ([x1,y1], [x2,y2]) => (x2-x1)*(v-y1) - (y2-y1)*(u-x1);
    return surface.triangles.some(([a,b,c]) => {
        const areas = [side(a,b),side(b,c),side(c,a)];
        return areas.every(area => area >= -1e-6) || areas.every(area => area <= 1e-6);
    });
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
        const surface=new Path2D(), boundary=new Path2D();
        const geometry = faceSurface(this.mesh, f);
        const pixel = ([u,v]) => [x+u*s,y-v*s];
        for (const [a,b,c] of geometry.triangles) {
            surface.moveTo(...pixel(a));surface.lineTo(...pixel(b));surface.lineTo(...pixel(c));surface.closePath();
        }
        for (const [start,end] of geometry.boundary) {
            boundary.moveTo(...pixel(start));boundary.lineTo(...pixel(end));
        }
        return this.projection = {mesh:this.mesh, face:f, x, y, scale:s, surface, boundary, triangles:geometry.triangles.length};
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
