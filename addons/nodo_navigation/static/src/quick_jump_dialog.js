import { Component, computed, signal, t, usePlugin, useProps } from "@odoo/owl";
import { Dialog } from "@web/core/dialog/dialog";
import { OfflinePlugin } from "@web/core/offline/offline_plugin";
import { useAutofocus, useService } from "@web/core/utils/hooks";
import { groupApplications } from "./menu_groups";
import { collectQuickJumpEntries, searchQuickJumpEntries } from "./quick_jump_search";

export class QuickJumpDialog extends Component {
    static template = "nodo_navigation.QuickJumpDialog";
    static components = { Dialog };
    props = useProps({ close: t.function() });
    query = signal("");
    opening = signal(false);
    searchInput = signal.ref();

    setup() {
        this.menu = useService("menu");
        const offline = usePlugin(OfflinePlugin);
        const entries = computed(() => {
            const apps = groupApplications(this.menu.getApps())
                .flatMap(({ items }) => items)
                .map(({ app, icon }) => ({ app: this.menu.getMenuAsTree(app.id), icon }));
            const entries = collectQuickJumpEntries(apps);
            return offline.isOffline()
                ? entries.filter(({ menu }) => offline.isAvailableOffline(menu.actionID))
                : entries;
        });
        this.results = computed(() => searchQuickJumpEntries(entries(), this.query()));
        useAutofocus({ ref: this.searchInput });
    }

    updateQuery(event) {
        this.query.set(event.target.value);
    }

    openFirstResult() {
        const [first] = this.results();
        if (first) {
            return this.openEntry(first);
        }
    }

    async openEntry({ menu }) {
        if (this.opening()) {
            return;
        }
        this.opening.set(true);
        try {
            // The action manager closes the dialog when navigation succeeds.
            // Leaving it open here preserves the query if the user stays on the form.
            await this.menu.selectMenu(menu);
        } finally {
            this.opening.set(false);
        }
    }
}
