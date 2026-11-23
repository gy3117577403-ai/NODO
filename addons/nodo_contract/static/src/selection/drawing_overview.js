const MINI_WIDTH = 122;
const MINI_HEIGHT = 90;

function clamp(value, low, high) {
    return Math.max(low, Math.min(high, value));
}

export function bindDrawingOverview(doc, application, centerAt) {
    const view = doc.defaultView;
    const viewer = application.pdfViewer;
    const container = viewer.container;
    const abort = new view.AbortController();
    const options = { signal: abort.signal };
    const panel = doc.createElement("div");
    panel.className = "o_nodo_drawing_overview";
    panel.hidden = true;
    const label = doc.createElement("div");
    label.textContent = "拖动视框";
    label.className = "o_nodo_drawing_overview_label";
    const map = doc.createElement("div");
    map.className = "o_nodo_drawing_overview_map";
    map.tabIndex = 0;
    map.setAttribute("role", "group");
    map.setAttribute("aria-label", "图纸导航，拖动视框或使用方向键移动原图");
    const marker = doc.createElement("div");
    marker.className = "o_nodo_drawing_overview_box";
    map.appendChild(marker);
    panel.append(label, map);
    container.parentElement.appendChild(panel);
    const style = doc.createElement("style");
    style.textContent = `
        .o_nodo_drawing_overview {
            position: absolute; bottom: 24px; right: 25px; z-index: 20;
            padding: 5px; border: 1px solid #bbc6c1; border-radius: 6px;
            background: #fbfcfb; box-shadow: 0 2px 8px #15241e30;
        }
        .o_nodo_drawing_overview_label {
            margin: 0 0 4px 2px; color: #36504a; font: 500 11px/14px system-ui, sans-serif;
        }
        .o_nodo_drawing_overview_map {
            position: relative; touch-action: none; overflow: hidden; cursor: grab;
            background: white; outline: 1px solid #dfe6e1; user-select: none;
        }
        .o_nodo_drawing_overview_map:focus-visible { outline: 2px solid #236457; }
        .o_nodo_drawing_overview_map[data-dragging] { cursor: grabbing; }
        .o_nodo_drawing_overview_map canvas {
            display: block; position: absolute; inset: 0; width: 100%; height: 100%; pointer-events: none;
        }
        .o_nodo_drawing_overview_box {
            position: absolute; box-sizing: border-box; border: 1.5px solid #216455;
            background: #286f5a26; pointer-events: none;
        }
    `;
    doc.head.appendChild(style);

    let animation = 0;
    let thumbnailTask;
    let thumbnailKey = "";
    let range;
    let drag;
    let disposed = false;

    function drawThumbnail(page, rotation, width, height) {
        const key = `${page.pageNumber}/${rotation}`;
        if (thumbnailKey === key) return;
        thumbnailKey = key;
        thumbnailTask?.cancel();
        const canvas = doc.createElement("canvas");
        const viewport = page.getViewport({ scale: 1, rotation });
        const target = page.getViewport({
            scale: Math.min(width / viewport.width, height / viewport.height) * 2, rotation,
        });
        canvas.width = Math.ceil(target.width);
        canvas.height = Math.ceil(target.height);
        canvas.setAttribute("aria-hidden", "true");
        map.querySelector("canvas")?.remove();
        map.prepend(canvas);
        thumbnailTask = page.render({ canvasContext: canvas.getContext("2d"), viewport: target, background: "white" });
        thumbnailTask.promise.catch(() => {
            if (!disposed && thumbnailKey === key) thumbnailKey = "";
        });
    }

    function update() {
        animation = 0;
        const pageView = viewer.getPageView(viewer.currentPageNumber - 1);
        const page = pageView?.pdfPage;
        const bounds = pageView?.div.getBoundingClientRect();
        if (!page || !bounds?.width || !container.clientWidth || !container.clientHeight ||
            (bounds.width <= container.clientWidth + 2 && bounds.height <= container.clientHeight + 2)) {
            panel.hidden = true;
            range = null;
            return;
        }
        const viewport = container.getBoundingClientRect();
        const width = Math.min(1, container.clientWidth / bounds.width);
        const height = Math.min(1, container.clientHeight / bounds.height);
        range = {
            x: clamp((viewport.left - bounds.left) / bounds.width, 0, 1 - width),
            y: clamp((viewport.top - bounds.top) / bounds.height, 0, 1 - height),
            width, height,
        };
        const scale = Math.min(MINI_WIDTH / bounds.width, MINI_HEIGHT / bounds.height);
        const mapWidth = bounds.width * scale;
        const mapHeight = bounds.height * scale;
        Object.assign(map.style, { width: `${mapWidth}px`, height: `${mapHeight}px` });
        Object.assign(marker.style, {
            left: `${range.x * 100}%`, top: `${range.y * 100}%`,
            width: `${width * 100}%`, height: `${height * 100}%`,
        });
        panel.hidden = false;
        drawThumbnail(page, (page.rotate + viewer.pagesRotation) % 360, mapWidth, mapHeight);
    }

    function schedule() {
        if (!animation) animation = view.requestAnimationFrame(update);
    }

    function pointerPoint(event) {
        const bounds = map.getBoundingClientRect();
        return [(event.clientX - bounds.left) / bounds.width, (event.clientY - bounds.top) / bounds.height];
    }

    function moveTo(x, y) {
        centerAt(clamp(x, range.width / 2, 1 - range.width / 2),
            clamp(y, range.height / 2, 1 - range.height / 2));
        schedule();
    }

    map.addEventListener("pointerdown", (event) => {
        if (event.button !== 0 || !range) return;
        map.focus({ preventScroll: true });
        const [x, y] = pointerPoint(event);
        const centerX = range.x + range.width / 2;
        const centerY = range.y + range.height / 2;
        const within = Math.abs(x - centerX) <= range.width / 2 && Math.abs(y - centerY) <= range.height / 2;
        drag = { id: event.pointerId, dx: within ? x - centerX : 0, dy: within ? y - centerY : 0 };
        map.setPointerCapture(event.pointerId);
        map.dataset.dragging = "";
        event.preventDefault();
        if (!within) moveTo(x, y);
    }, options);
    map.addEventListener("pointermove", (event) => {
        if (event.pointerId !== drag?.id || !range) return;
        const [x, y] = pointerPoint(event);
        moveTo(x - drag.dx, y - drag.dy);
    }, options);
    map.addEventListener("lostpointercapture", () => {
        drag = null;
        delete map.dataset.dragging;
    }, options);
    map.addEventListener("keydown", (event) => {
        const direction = { ArrowLeft: [-1, 0], ArrowRight: [1, 0], ArrowUp: [0, -1], ArrowDown: [0, 1] }[event.key];
        if (!direction || !range) return;
        event.preventDefault();
        event.stopPropagation();
        moveTo(range.x + range.width * (0.5 + 0.25 * direction[0]),
            range.y + range.height * (0.5 + 0.25 * direction[1]));
    }, options);
    const events = ["pagerendered", "pagechanging", "scalechanging", "rotationchanging", "documentinit"];
    for (const event of events) application.eventBus.on(event, schedule);
    container.addEventListener("scroll", schedule, { ...options, passive: true });
    const resize = new view.ResizeObserver(schedule);
    resize.observe(container);
    schedule();
    return () => {
        disposed = true;
        view.cancelAnimationFrame(animation);
        thumbnailTask?.cancel();
        abort.abort();
        resize.disconnect();
        for (const event of events) application.eventBus.off(event, schedule);
        panel.remove();
        style.remove();
    };
}
