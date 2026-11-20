import React from "react";
import {createRoot} from "react-dom/client";
import Viewer from "@jingneng/Viewer";
import {locateFace} from "@jingneng/coordinates";
export {checkHolePlacement} from "@jingneng/holePlacement";

const empty = [];
const noop = () => {};
const display = {edges: true, grid: false, transparent: false, dimensions: false};

// The released AE viewer owns its WebGL context, orbit controls, raycaster and
// disposal. NODO owns the CAD model, hole form and the lifetime of this host.
export function mount(host, selectFace) {
    const root = createRoot(host);
    return {
        update(model, open, paused, reset, parts, holePreview) {
            if (!model) {
                root.render(null);
                return;
            }
            root.render(<Viewer model={model} angle={open ? 70 : 0} explode={0}
                view="iso" reset={reset} paused={paused} selected={parts?.selected[0] ?? ""}
                hidden={parts?.hidden ?? empty} highlighted={parts?.selected} focusPart={parts?.focus}
                display={display} holeMode={false} holeOverlay={!!holePreview}
                holes={holePreview?.holes ?? empty} activeHole={holePreview?.active ?? null}
                editing={holePreview?.editing ?? null} holeIssue={holePreview?.issue ?? null}
                onHoleMove={noop} onHoleMoveEnd={noop}
                onClearSelection={parts?.clear}
                onEditHole={() => false} onPick={hit => {
                    if (parts) return parts.pick(hit.id);
                    const location = locateFace(hit, model.faces);
                    if (location) selectFace(location);
                }} />);
        },
        dispose() {
            root.unmount();
        },
    };
}
