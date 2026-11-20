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
        [imports, imports + "\nimport {pickDrillPlane} from '@nodo/drill-pick';"],
        [props, "drill?:{pick:(point:ReturnType<typeof pickDrillPlane>)=>void};" + props],
        [dispatch, "   setRay(e);\n   const drill=live.current.drill;\n" +
            "   if(drill){drill.pick(pickDrillPlane(ray,live.current.model.faces,objects));return;}\n" +
            "   const accessory=accessories.select(ray);"],
        ["const rightPivot=", "const explodeUp=new THREE.Vector3(0,0,1);\n  const rightPivot="],
        // Apply each door's spread in cabinet axes, independent of hinge angle.
        [movingDoor, "o.group.position.applyAxisAngle(explodeUp,-door.rotation.z).sub(pivot);" +
            "else if(o.part.group==='door_right')o.group.position.applyAxisAngle(explodeUp,-rightDoor.rotation.z).sub(rightPivot);"],
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
        ["addScaledVector(direction,distance*1.2)", "addScaledVector(direction,distance*(separated.length?1.13:1.2))"],
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
