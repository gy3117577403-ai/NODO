// Extend the pinned Viewer at its pointer-up boundary. The desktop source stays
// read-only; Plane/Gizmo transforms use the fitted camera and live door matrices.
module.exports = function extendViewer(source) {
    const imports = "import type {DisplayOptions} from './workbenchNavigation';";
    const props = "onPick:(pick:Pick)=>void;onClearSelection?";
    const dispatch = "   setRay(e);\n   const accessory=accessories.select(ray);";
    const changes = [
        [imports, imports + "\nimport {pickDrillPlane} from '@nodo/drill-pick';"],
        [props, "drill?:{pick:(point:ReturnType<typeof pickDrillPlane>)=>void};" + props],
        [dispatch, "   setRay(e);\n   const drill=live.current.drill;\n" +
            "   if(drill){drill.pick(pickDrillPlane(ray,live.current.model.faces,objects));return;}\n" +
            "   const accessory=accessories.select(ray);"],
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
