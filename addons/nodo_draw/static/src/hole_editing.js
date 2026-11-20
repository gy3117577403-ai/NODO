import {containsMaterial, facePoint, faceSurface} from "./mesh";

const axisSize = {u: "width", v: "height"};
const shapes = {circle: ["diameter"], rectangle: ["width", "height"], slot: ["width", "height"]};

// End-edge and center-line measurements are display coordinates. The draft and
// CAD service always use the canonical distances from the board's U/V origin.
export function holeCoordinate(value, board, axis, basis, toOrigin = false) {
    if (!Number.isFinite(value) || basis === "start") return value;
    const size = board[axisSize[axis]];
    const converted = basis === "end" ? size - value : value + (toOrigin ? size / 2 : -size / 2);
    return Number(converted.toFixed(10));
}

export function holeRecord(values, id) {
    const {face, type, u, v} = values;
    return {id, face, type, u, v, anchor: "left", anchorV: "bottom",
        ...Object.fromEntries(shapes[type].map(field => [field, values[field]]))};
}

export function sameHole(left, right) {
    return left.face === right.face && left.type === right.type && left.u === right.u && left.v === right.v &&
        shapes[left.type].every(field => left[field] === right[field]);
}

export function holeDimensionsReady(hole) {
    return shapes[hole.type].every(field => Number.isFinite(hole[field]) && hole[field] > 0) &&
        Number.isFinite(hole.u) && Number.isFinite(hole.v);
}

export function sameThickness(left, right) {
    const same = (a, b) => Object.keys(a).length === Object.keys(b).length &&
        Object.entries(a).every(([key, value]) => b[key] === value);
    const {parts: leftParts = {}, ...leftGroups} = left;
    const {parts: rightParts = {}, ...rightGroups} = right;
    return same(leftGroups, rightGroups) && same(leftParts, rightParts);
}
export function linkedHole(hole) { return Boolean(hole.ownerAccessory || hole.accessoryUsers?.length); }

export function openingAt(mesh, face, {u,v}, shapeTools) {
    for (const instance of mesh.parameters.accessories ?? []) {
        const opening = instance.definition?.templateOpening;
        if (opening?.face !== face.id || opening.templateId !== mesh.parameters.configuration?.templateId) continue;
        const [x,y] = facePoint(instance, face);
        if (shapeTools.holeContains({...opening, type:"rectangle", u:x, v:y}, face, u, v)) {
            return `此处是原图 ${opening.width} × ${opening.height} mm 开孔，供${instance.definition.name}使用。`;
        }
    }
    const installedCut = (mesh.parameters.holes ?? []).find(hole => hole.face === face.id && linkedHole(hole) &&
        shapeTools.holeContains(hole, face, u, v));
    if (installedCut) return "此处是附件关联孔位，请在装配中调整。";
    return "";
}

export function conflictsWithPlate(mesh, face, hole, shapeTools) {
    const surface = faceSurface(mesh, face);
    if (!surface.triangles.length) return false;
    // A saved independent cut is filled back into the editable sheet for this
    // test. Current custom holes are checked separately from the draft records.
    const saved = (mesh.parameters.holes ?? []).filter(row => row.face === face.id && !linkedHole(row) && /^H\d+$/.test(row.id));
    const refilled = ([u,v]) => saved.some(row => shapeTools.holeContains(row, face, u, v, .05));
    const contour = shapeTools.cutPoints(hole).map(([u,v]) => [hole.u+u,hole.v+v]);
    const hasMaterial = point => containsMaterial(surface, point) || refilled(point);
    if (!hasMaterial([hole.u,hole.v]) || contour.some(point => !hasMaterial(point))) return true;
    const [minU,maxU] = [Math.min(...contour.map(point => point[0])), Math.max(...contour.map(point => point[0]))];
    const [minV,maxV] = [Math.min(...contour.map(point => point[1])), Math.max(...contour.map(point => point[1]))];
    const contains = ([u,v]) => shapeTools.holeContains(hole, face, u, v);
    return surface.boundary.some(([a,b]) => {
        if (Math.max(a[0],b[0]) < minU || Math.min(a[0],b[0]) > maxU ||
            Math.max(a[1],b[1]) < minV || Math.min(a[1],b[1]) > maxV) return false;
        if (refilled(a) && refilled(b)) return false;
        return contains(a) || contains(b) || contour.some((point,index) =>
            shapeTools.segmentsCross(a,b,point,contour[(index+1)%contour.length]));
    });
}
