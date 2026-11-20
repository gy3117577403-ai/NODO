import {Component, onMounted, onWillUnmount, signal, untrack, useEffect, useProps} from "@odoo/owl";

export const fitView = {zoom: 1, x: 0, y: 0};
const maxZoom = 8;
const zoomStep = 1.25;

export class DrawingViewport extends Component {
    static template = "nodo_draw.DrawingViewport";
    props = useProps({src: String, title: String, showTitle: Boolean, initialView: Object, remember: Function});
    surface = signal.ref();
    view = signal(fitView);
    status = signal("loading");

    setup() {
        this.view.set(this.props.initialView);
        useEffect(() => {
            const surface = this.surface();
            if (!surface) return;
            const observer = new ResizeObserver(() => this.moveTo(this.view()));
            observer.observe(surface);
            return () => observer.disconnect();
        });
    }

    imageLoaded(event) {
        const image = event.currentTarget;
        this.aspectRatio = image.naturalWidth / image.naturalHeight;
        this.moveTo(this.view());
        this.status.set("ready");
    }

    moveTo({zoom, x, y}) {
        const surface = this.surface();
        if (!surface || !this.aspectRatio) return;
        const {clientWidth: width, clientHeight: height} = surface;
        const sheetWidth = Math.min(width, height * this.aspectRatio) * zoom;
        const sheetHeight = sheetWidth / this.aspectRatio;
        // Keep enough of the drawing in view to grab it after panning.
        const limitX = (width + sheetWidth) / 2 - Math.min(48, width, sheetWidth);
        const limitY = (height + sheetHeight) / 2 - Math.min(48, height, sheetHeight);
        const next = {zoom, x: Math.max(-limitX, Math.min(limitX, x)), y: Math.max(-limitY, Math.min(limitY, y))};
        const previous = this.view();
        if (next.zoom === previous.zoom && next.x === previous.x && next.y === previous.y) return;
        this.view.set(next);
        this.props.remember(next);
    }

    zoomAt(factor, x = 0, y = 0) {
        const old = this.view();
        const zoom = Math.max(1, Math.min(maxZoom, old.zoom * factor));
        const ratio = zoom / old.zoom;
        this.moveTo({zoom, x: x + (old.x - x) * ratio, y: y + (old.y - y) * ratio});
    }

    zoomIn() { this.zoomAt(zoomStep); }
    zoomOut() { this.zoomAt(1 / zoomStep); }
    fit() { this.moveTo(fitView); }
    atZoomLimit() { return this.view().zoom >= maxZoom; }

    wheel(event) {
        if (!event.deltaY || this.status() !== "ready") return;
        const bounds = event.currentTarget.getBoundingClientRect();
        const unit = [1, 16, bounds.height][event.deltaMode] || 1;
        const factor = Math.exp(-event.deltaY * unit * .0025);
        this.zoomAt(factor, event.clientX - bounds.left - bounds.width / 2,
            event.clientY - bounds.top - bounds.height / 2);
    }

    beginPan(event) {
        if (!event.isPrimary || event.button !== 0 || this.status() !== "ready") return;
        this.drag = {id: event.pointerId, x: event.clientX, y: event.clientY, view: this.view()};
        event.currentTarget.setPointerCapture(event.pointerId);
    }

    pan(event) {
        const drag = this.drag;
        if (drag?.id !== event.pointerId) return;
        this.moveTo({zoom: drag.view.zoom, x: drag.view.x + event.clientX - drag.x,
            y: drag.view.y + event.clientY - drag.y});
    }

    endPan(event) {
        if (this.drag?.id === event.pointerId) this.drag = null;
    }

    imageStyle() {
        const {zoom, x, y} = this.view();
        const size = `${zoom * 100}%`;
        return `width:${size};height:${size};left:calc(50% + ${x}px);top:calc(50% + ${y}px)`;
    }
}

export class ArchivedCabinet extends Component {
    static template = "nodo_draw.ArchivedCabinet";
    props = useProps({src: String, revision: String});
    host = signal.ref();
    mesh = signal(null);
    error = signal("");
    opened = signal(false);
    reset = signal(0);

    setup() {
        const request = new AbortController();
        onMounted(() => this.loadModel(request.signal));
        onWillUnmount(() => request.abort());
        useEffect(() => {
            const host = this.host();
            if (!host) return;
            const viewer = window.nodoDrawAE0573.mount(host, () => {});
            this.viewer = viewer;
            untrack(() => this.updateViewer());
            return () => { this.viewer = null; viewer.dispose(); };
        });
        useEffect(() => this.updateViewer());
    }

    async loadModel(signal) {
        try {
            const response = await fetch(this.props.src, {signal});
            if (!response.ok) throw new Error();
            const mesh = await response.json();
            if (!signal.aborted) this.mesh.set(mesh);
        } catch {
            if (!signal.aborted) this.error.set("本版本三维暂时无法读取");
        }
    }

    updateViewer() {
        const mesh = this.mesh(), opened = this.opened(), reset = this.reset();
        this.viewer?.update(mesh, opened, false, reset);
    }
}
