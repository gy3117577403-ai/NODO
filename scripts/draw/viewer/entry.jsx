import React from "react";
import {createRoot} from "react-dom/client";
import Viewer from "@jingneng/Viewer";
import {locateFace} from "@jingneng/coordinates";
import {withExplosionVectors} from "./explosion_model.mjs";
export {checkHolePlacement, holeContains} from "@jingneng/holePlacement";
export {cutPoints, segmentsCross} from "@jingneng/holeShape";

const empty = [];
const noop = () => {};
const display = {edges: true, grid: false, transparent: false, dimensions: false};
const drillingDisplay = {...display, dimensions: true};

// The released AE viewer owns its WebGL context, orbit controls, raycaster and
// disposal. NODO owns the CAD model, hole form and the lifetime of this host.
export function mount(host) {
    const root = createRoot(host);
    let camera = null;
    let sourceModel = null, viewModel = null;
    const readCamera = value => { camera = value; };
    return {
        camera() { return camera; },
        update(model, open, paused, reset, {parts, holePreview, drilling, orientation, explode = 0, catalogPreview = false, installationFace} = {}) {
            if (!model) {
                root.render(null);
                return;
            }
            if (sourceModel !== model) {
                sourceModel = model;
                viewModel = withExplosionVectors(model);
            }
            const drill = drilling && {
                pick: ({plane, surface, obstructed}) => drilling.pick(plane, surface && locateFace(surface, model.faces), obstructed),
            };
            root.render(<Viewer model={viewModel} angle={open ? 70 : 0} explode={explode} catalogPreview={catalogPreview}
                view={orientation?.view ?? "iso"} reset={reset} restoreRequest={orientation?.restore} onCamera={readCamera}
                paused={paused} selected={parts?.selected[0] ?? ""}
                hidden={parts?.hidden ?? empty} highlighted={parts?.selected} focusPart={parts?.focus}
                installationFace={installationFace}
                display={drill ? drillingDisplay : display} drill={drill}
                snapStep={drilling?.snap} holeMode={!!drill} holeOverlay={!!holePreview}
                holes={holePreview?.holes ?? empty} activeHole={holePreview?.active ?? null}
                editing={holePreview?.editing ?? null} holeIssue={holePreview?.issue ?? null}
                onHoleMove={drilling?.move ?? noop} onHoleMoveEnd={drilling?.end ?? noop}
                onClearSelection={parts?.clear} onEditHole={drilling?.edit ?? (() => false)}
                onPick={hit => parts?.pick?.(hit.id, locateFace(hit, model.faces)?.face)} />);
        },
        dispose() {
            root.unmount();
        },
    };
}
