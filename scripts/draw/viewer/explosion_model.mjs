const travel = (size, factor, min, max) => Math.max(min, Math.min(size * factor, max));
const stationary = [0, 0, 0];

// These offsets belong to the browser view. The stored vertices, part IDs,
// machining faces and export parameters remain the CAD engine's originals.
export function withExplosionVectors(model) {
    const {width, height, depth} = model.dimensions;
    const double = model.parameters?.configuration?.kind === "double";
    const side = travel(width, .12, 60, 200);
    const front = travel(depth, .40, 70, 180);
    const lift = travel(height, .14, 65, 170);
    const cabinet = new Map([
        ["top", [0, 0, lift]],
        ["bottom", [0, 0, -lift]],
        ["mount", [0, -travel(depth, .62, 85, 220), 0]],
    ]);
    const doors = new Map([["door", [-side, -front, 0]], ["door_right", [side, -front, 0]]]);
    const parts = new Map(model.parts.map(part => [part.id, part]));
    const boards = new Map(model.faces.map(face => [face.id, parts.get(face.part)]));
    const mounts = new Map(model.parameters?.accessories?.map(item => [item.id, boards.get(item.face)]));
    const offset = part => (double && (doors.get(part.group) || cabinet.get(part.id))) || part.explode || stationary;
    return {...model, parts: model.parts.map(part => {
        const host = mounts.get(part.accessoryId);
        return {...part, explode: offset(host && host.group === part.group ? host : part)};
    })};
}
