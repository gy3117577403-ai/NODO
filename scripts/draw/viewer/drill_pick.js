import {Vector3} from "three";
import {intersectFace} from "@jingneng/HoleGizmo";

// A ray can hit a back wall through an opening or hit the lock in front of it.
// Keep the visible surface and the nearest eligible work plane as separate facts.
export function pickDrillPlane(ray, faces, objects) {
    const visible = objects.filter(object => object.group.visible);
    const [hit] = ray.intersectObjects(visible.map(object => object.mesh));
    const surface = hit?.face ? {
        id: hit.object.userData.id,
        point: hit.object.worldToLocal(hit.point.clone()).toArray(),
        normal: hit.face.normal.toArray(),
    } : null;
    let nearest = null;
    for (const face of faces) {
        const object = visible.find(item => item.part.id === face.part);
        if (!object) continue;
        const uv = intersectFace(ray.ray, face, object.mesh.matrixWorld);
        if (!uv || uv.u < 0 || uv.u > face.width || uv.v < 0 || uv.v > face.height) continue;
        const world = new Vector3(...face.origin)
            .addScaledVector(new Vector3(...face.uAxis), uv.u)
            .addScaledVector(new Vector3(...face.vAxis), uv.v)
            .applyMatrix4(object.mesh.matrixWorld);
        const distance = ray.ray.origin.distanceTo(world);
        if (!nearest || distance < nearest.distance) nearest = {...uv, face, distance};
    }
    if (!nearest) return {surface, plane:null, obstructed:false};
    const {face,u,v,distance} = nearest;
    // On the inner side of a sheet its solid surface can precede the nominal
    // work plane by its thickness divided by the angle of the ray.
    const obstructed = !!hit && hit.distance < distance - .1;
    return {surface, plane:{face:face.id, u, v}, obstructed};
}
