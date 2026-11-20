const stationary = [0, 0, 0];

// These offsets belong to the browser view. The stored vertices, part IDs,
// machining faces and export parameters remain the CAD engine's originals.
export function withExplosionVectors(model) {
    const {width, height, depth} = model.dimensions;
    const double = model.parameters?.configuration?.kind === "double";
    const gap = Math.min(width, height) * .22 + depth * .23;
    // Give the door leaves, shell and mounting plate separate silhouettes in
    // the overview. A double door leaves room for the plate below the left leaf.
    const cabinet = new Map([
        ["top", [0, 0, height * .44 + depth * .56]],
        ["bottom", double ? [width * .34, 0, -height * .64 - depth * .52] : [0, 0, -height * .51 - depth * .41]],
        ["mount", double ? [-width * .64, -depth * 1.2, -height * 1.32 - depth * .2] : [width + gap + depth * .72, -depth * .78, 0]],
    ]);
    const doors = new Map([
        ["door", [-(double ? width / 2 : width) - gap, -depth * .24, double ? height * .08 : 0]],
        ["door_right", [width / 2 + gap + depth * .8, -depth * .27, height * .1]],
    ]);
    const parts = new Map(model.parts.map(part => [part.id, part]));
    const boards = new Map(model.faces.map(face => [face.id, parts.get(face.part)]));
    const mounts = new Map(model.parameters?.accessories?.map(item => [item.id, boards.get(item.face)]));
    const offset = part => doors.get(part.group) ?? cabinet.get(part.id) ?? part.explode ?? stationary;
    return {...model, parts: model.parts.map(part => {
        const host = mounts.get(part.accessoryId);
        return {...part, explode: offset(host && host.group === part.group ? host : part)};
    })};
}
