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
