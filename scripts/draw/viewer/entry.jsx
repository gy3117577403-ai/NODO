import React from "react";
import {createRoot} from "react-dom/client";
import Viewer from "@jingneng/Viewer";
import {locateFace} from "@jingneng/coordinates";

const empty = [];
const noop = () => {};
const display = {edges: true, grid: false, transparent: false, dimensions: false};

// The released AE viewer owns its WebGL context, orbit controls, raycaster and
// disposal. NODO owns the CAD model, hole form and the lifetime of this host.
export function mount(host, selectFace) {
    const root = createRoot(host);
    return {
        update(model, open, paused, reset) {
            if (!model) {
                root.render(null);
                return;
            }
            root.render(<Viewer model={model} angle={open ? 70 : 0} explode={0}
                view="iso" reset={reset} paused={paused} selected="" hidden={empty}
                display={display} holeMode={false} holes={empty} activeHole={null}
                editing={null} holeIssue={null} onHoleMove={noop} onHoleMoveEnd={noop}
                onEditHole={() => false} onPick={hit => {
                    const location = locateFace(hit, model.faces);
                    if (location) selectFace(location);
                }} />);
        },
        dispose() {
            root.unmount();
        },
    };
}
