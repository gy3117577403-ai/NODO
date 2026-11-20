import {Component, signal, useListener, useProps} from "@odoo/owl";

export class ExplosionControls extends Component {
    static template = "nodo_draw.ExplosionControls";
    props = useProps({value: Number, change: Function, fit: Function, activate: {type: Function, optional: true}});
    opened = signal(false);
    root = signal.ref();
    trigger = signal.ref();

    setup() {
        useListener(document, "click", event => {
            if (this.opened() && !this.root()?.contains(event.target)) this.opened.set(false);
        });
        useListener(document, "keydown", event => {
            if (event.key !== "Escape" || !this.opened()) return;
            this.opened.set(false);
            this.trigger()?.focus();
        });
    }

    toggle() {
        if (!this.opened()) this.props.activate?.();
        this.opened.set(!this.opened());
    }

    setEndpoint(value) {
        this.props.change(value);
        this.props.fit();
    }
}
