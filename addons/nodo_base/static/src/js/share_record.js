import { Component, proxy, signal, types as t, useEffect, useProps } from "@odoo/owl";
import { Dialog } from "@web/core/dialog/dialog";
import { registry } from "@web/core/registry";
import { useDebounced } from "@web/core/utils/timing";

import { RECORD_SERVICE } from "./record_cards";

class ShareRecordDialog extends Component {
    static template = "nodo_base.ShareRecordDialog";
    static components = { Dialog };
    props = useProps({
        model: t.string(),
        id: t.number(),
        close: t.function(),
    });
    note = signal("");

    kinds = [
        { id: "person", label: "人员" },
        { id: "group", label: "群聊" },
        { id: "channel", label: "频道" },
    ];

    setup() {
        this.state = proxy({
            kind: "person", term: "", targets: null, selected: null, sending: false, error: "",
        });
        const search = useDebounced((kind, term) => this.loadTargets(kind, term), 200);
        useEffect(() => {
            search(this.state.kind, this.state.term);
        });
    }

    setKind(kind) {
        if (this.state.kind !== kind) {
            this.state.kind = kind;
            this.state.term = "";
            this.resetResults();
        }
    }

    onSearch(ev) {
        this.state.term = ev.target.value;
        this.resetResults();
    }

    resetResults() {
        this.state.targets = null;
        this.state.selected = null;
        this.state.error = "";
    }

    async loadTargets(kind, term) {
        const { orm } = this.env.services;
        let targets = [];
        let error = "";
        try {
            targets = await orm.silent.call(RECORD_SERVICE, "search_share_targets", [kind, term]);
        } catch {
            error = "暂时无法加载会话，请重试。";
        }
        if (this.state.kind === kind && this.state.term === term) {
            this.state.targets = targets;
            this.state.error = error;
        }
    }

    async send() {
        const { orm, notification, "mail.store": store } = this.env.services;
        const { selected, sending, kind } = this.state;
        if (!selected || sending) {
            return;
        }
        this.state.sending = true;
        this.state.error = "";
        let result;
        try {
            result = await orm.silent.call(
                RECORD_SERVICE, "share_record", [this.props.model, this.props.id, kind, selected, this.note()]
            );
        } catch (error) {
            this.state.error = error.data?.message || "暂时无法发到聊天，请重试。";
            this.state.sending = false;
            return;
        }
        this.props.close();
        const { channel_id: channelId } = result;
        const close = notification.add("已发到聊天。", {
            type: "success",
            sticky: true,
            buttons: [{
                name: "去看看",
                primary: true,
                async onClick() {
                    await store.fetchChannel(channelId);
                    store["discuss.channel"].get(channelId)?.open({ focus: true, bypassCompact: true });
                    close();
                },
            }],
        });
    }
}

registry.category("actions").add("nodo_share_record", (env, { params }) => {
    env.services.dialog.add(ShareRecordDialog, { model: params.model, id: params.id });
});
