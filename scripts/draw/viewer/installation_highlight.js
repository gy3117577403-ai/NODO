import {BufferGeometry, Group, Line, LineBasicMaterial, LineDashedMaterial, Vector3} from "three";

export function createInstallationHighlight(scene) {
    const geometry = new BufferGeometry();
    const visible = new Line(geometry, new LineBasicMaterial({color: 0x188464, depthWrite: false}));
    const occluded = new Line(geometry, new LineDashedMaterial({color: 0x188464, dashSize: 10, gapSize: 7,
        transparent: true, opacity: .55, depthTest: false, depthWrite: false}));
    const guide = new Group();
    guide.matrixAutoUpdate = false;
    guide.visible = false;
    occluded.renderOrder = 2;
    visible.renderOrder = 3;
    guide.add(occluded, visible);
    scene.add(guide);

    let lastFace;
    return {
        update(face, objects) {
            const host = face && objects.find(object => object.part.id === face.part && object.group.visible);
            guide.visible = Boolean(host);
            if (!host) return;
            if (face !== lastFace) {
                const origin = new Vector3(...face.origin).addScaledVector(new Vector3(...face.normal), .45);
                const u = new Vector3(...face.uAxis).multiplyScalar(face.width);
                const v = new Vector3(...face.vAxis).multiplyScalar(face.height);
                geometry.setFromPoints([origin, origin.clone().add(u), origin.clone().add(u).add(v), origin.clone().add(v), origin]);
                geometry.computeBoundingSphere();
                occluded.computeLineDistances();
                lastFace = face;
            }
            host.mesh.updateWorldMatrix(true, false);
            guide.matrix.copy(host.mesh.matrixWorld);
            guide.matrixWorldNeedsUpdate = true;
        },
        dispose() {
            guide.removeFromParent();
            geometry.dispose();
            visible.material.dispose();
            occluded.material.dispose();
        },
    };
}
