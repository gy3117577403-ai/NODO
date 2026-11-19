import { Component, computed, signal, t, usePlugin, useProps } from "@odoo/owl";
import { Dialog } from "@web/core/dialog/dialog";
import { OfflinePlugin } from "@web/core/offline/offline_plugin";
import { useAutofocus, useService } from "@web/core/utils/hooks";
import { groupApplications } from "./menu_groups";
import { collectQuickJumpEntries, groupQuickJumpFunctions, searchQuickJumpEntries } from "./quick_jump_search";

export class QuickJumpDialog extends Component {
    static template = "nodo_navigation.QuickJumpDialog";
    static components = { Dialog };
    props = useProps({ close: t.function() });
    query = signal("");
    selectedAppId = signal(null);
    opening = signal(false);
    searchInput = signal.ref();
    content = signal.ref();

    setup() {
        this.menu = useService("menu");
        const offline = usePlugin(OfflinePlugin);
        this.appGroups = computed(() => groupApplications(this.menu.getApps()));
        const entries = computed(() => {
            const apps = this.appGroups()
                .flatMap(({ items }) => items)
                .map(({ app, icon }) => ({ app: this.menu.getMenuAsTree(app.id), icon }));
            const entries = collectQuickJumpEntries(apps);
            return offline.isOffline()
                ? entries.filter(({ menu }) => offline.isAvailableOffline(menu.actionID))
                : entries;
        });
        this.selectedApp = computed(() => this.menu.getApps().find(({ id }) => id === this.selectedAppId()));
        this.results = computed(() => searchQuickJumpEntries(entries(), this.query()));
        this.functionGroups = computed(() => {
            if (this.query().trim()) {
                const results = this.results();
                return results.length ? [{ id: "results", entries: results }] : [];
            }
            const appId = this.selectedAppId();
            const groups = groupQuickJumpFunctions(entries(), appId);
            const home = entries().find(({ menu }) => menu.id === appId);
            if (home) {
                groups.unshift({ id: "home", entries: [{ ...home, label: "打开应用首页" }] });
            }
            return groups;
        });
        useAutofocus({ ref: this.searchInput });
    }

    updateQuery(event) {
        this.query.set(event.target.value);
        this.content()?.scrollTo(0, 0);
    }

    browseApp(appId) {
        this.selectedAppId.set(appId);
        this.content()?.scrollTo(0, 0);
        this.searchInput()?.focus({ preventScroll: true });
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
