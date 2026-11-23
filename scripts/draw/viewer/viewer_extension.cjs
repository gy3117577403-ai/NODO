// Extend the pinned Viewer in NODO's bundle. Picking and framing use the live
// part transforms, while the desktop source and CAD meshes stay read-only.
module.exports = function extendViewer(source) {
    const imports = "import type {DisplayOptions} from './workbenchNavigation';";
    const props = "onPick:(pick:Pick)=>void;onClearSelection?";
    const dispatch = "   setRay(e);\n   const accessory=accessories.select(ray);";
    const movingDoor = "o.group.position.sub(pivot);else if(o.part.group==='door_right')o.group.position.sub(rightPivot);";
    const visibleBounds = "objects.filter(o=>o.group.visible&&(!focusIds||focusIds.includes(o.part.id))).forEach(o=>bounds.expandByObject(o.mesh));";
    const fitCorners = "for(const x of [bounds.min.x,bounds.max.x])for(const y of [bounds.min.y,bounds.max.y])for(const z of [bounds.min.z,bounds.max.z]){";
    const changes = [
        [imports, imports + "\nimport {pickDrillPlane} from '@nodo/drill-pick';\nimport {createInstallationHighlight} from '@nodo/installation-highlight';"],
        [props, "catalogPreview?:boolean;installationFace?:string;sheetSelection?:boolean;drill?:{pick:(point:ReturnType<typeof pickDrillPlane>)=>void};" + props],
        // On the usage table, tint the actual selected solids. For interior parts,
        // let the surrounding assembly show their installation position through the skin.
        ["const nextPartsKey=", "const nextPartsKey=String(!!p.sheetSelection)+"],
        ["if(nextPartsKey!==partsKey){", "if(nextPartsKey!==partsKey){\n" +
            "    const sheets=p.sheetSelection?p.highlighted:undefined;\n" +
            "    const interior=sheets?.some(id=>id==='mount'||id.startsWith('brace_'));"],
        ["const transparent=!!p.display?.transparent", "const dimmed=interior&&!sheets?.includes(o.part.id);\n" +
            "     const transparent=!!dimmed||!!p.display?.transparent"],
        ["o.mat.depthWrite=!transparent;", "o.mat.depthWrite=!transparent;\n" +
            "     if(!conflict&&sheets?.includes(o.part.id)){o.mat.color.setHex(0x35b38b);" +
            "o.mat.emissive.setHex(0x1a664b);o.edgeMat.color.setHex(0x0f6650);}\n" +
            "     else if(dimmed){o.mat.opacity=.17;o.edgeMat.opacity=.16;}"],
        ["const accessories=createAccessoryGizmo", "const installationHighlight=createInstallationHighlight(scene);\n  const accessories=createAccessoryGizmo"],
        ["renderer.render(scene,camera);", "installationHighlight.update(p.installationFace&&p.model.faces.find(face=>face.id===p.installationFace),objects);\n   renderer.render(scene,camera);"],
        ["gizmo.dispose();controls.removeEventListener", "gizmo.dispose();installationHighlight.dispose();controls.removeEventListener"],
        ["antialias:true,alpha:false", "antialias:true,alpha:!!props.catalogPreview"],
        ["renderer.setClearColor('#e9edef')", "renderer.setClearColor('#e9edef',props.catalogPreview?0:1)"],
        // Catalogue parts can be much smaller than a cabinet. Fit their real
        // bounds against the same frustum and leave clearance around the part.
        ["let distance=200;", "let distance=live.current.catalogPreview?controls.minDistance:200;"],
        [dispatch, "   setRay(e);\n   const drill=live.current.drill;\n" +
            "   if(drill){drill.pick(pickDrillPlane(ray,live.current.model.faces,objects));return;}\n" +
            "   const accessory=accessories.select(ray);"],
        ["const rightPivot=", "const explodeUp=new THREE.Vector3(0,0,1);\n  const rightPivot="],
        // Apply each door's spread in cabinet axes, independent of hinge angle.
        [movingDoor, "o.group.position.applyAxisAngle(explodeUp,-door.rotation.z).sub(pivot);" +
            "else if(o.part.group==='door_right')o.group.position.applyAxisAngle(explodeUp,-rightDoor.rotation.z).sub(rightPivot);"],
        // Consume the last orbit delta before placing the catalogue camera.
        ["const setCamera=(focusIds?:string[])=>{", "const setCamera=(focusIds?:string[])=>{\n" +
            "   if(live.current.catalogPreview){const damping=controls.enableDamping;" +
            "controls.enableDamping=false;controls.update();controls.enableDamping=damping;}"],
        [visibleBounds, "const spread=live.current.explode>0;\n   const separated=[] as THREE.Box3[];\n" +
            "   for(const o of objects){\n" +
            "    if(!o.group.visible||(focusIds&&!focusIds.includes(o.part.id)))continue;\n" +
            "    if(spread&&!focusIds){const box=new THREE.Box3().setFromObject(o.mesh);separated.push(box);bounds.union(box);}\n" +
            "    else bounds.expandByObject(o.mesh);\n   }"],
        ["new THREE.Vector3(.85,-1.35,.8).normalize()", "(spread?new THREE.Vector3(.7,-1.55,.72):new THREE.Vector3(.85,-1.35,.8)).normalize()"],
        // In the expanded model, corners of the combined bounds include large
        // empty areas. Fit each actual part box so the cabinet remains legible.
        [fitCorners, "for(const box of separated.length?separated:[bounds])" +
            "for(const x of [box.min.x,box.max.x])for(const y of [box.min.y,box.max.y])for(const z of [box.min.z,box.max.z]){"],
        ["addScaledVector(direction,distance*1.2)", "addScaledVector(direction,distance*(live.current.catalogPreview?1.32:separated.length?1.13:1.2))"],
    ];
    let text = source.toString("utf8");
    for (const [before, after] of changes) {
        const position = text.indexOf(before);
        if (position < 0 || text.indexOf(before, position + before.length) !== -1) {
            throw Error("京能原版视口的扩展位置不唯一");
        }
        text = text.replace(before, after);
    }
    return text;
};
