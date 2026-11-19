import { Component, proxy, useListener, usePlugin } from "@odoo/owl";
import { browser } from "@web/core/browser/browser";
import { OfflinePlugin } from "@web/core/offline/offline_plugin";
import { user } from "@web/core/user";
import { useService } from "@web/core/utils/hooks";
import { patch } from "@web/core/utils/patch";
import { render } from "@web/owl2/utils";
import { session } from "@web/session";
import { WebClient } from "@web/webclient/webclient";
import { groupApplications } from "./menu_groups";

class NodoApplicationSidebar extends Component {
    static template = "nodo_navigation.ApplicationSidebar";

    setup() {
        this.menu = useService("menu");
        this.command = useService("command");
        this.pwa = useService("pwa");
        this.ui = proxy(useService("ui"));
        this.offline = usePlugin(OfflinePlugin);
        this.storageKey = `nodo.navigation.expanded:${session.db}:${user.userId}`;
        this.state = proxy({ expanded: browser.localStorage.getItem(this.storageKey) === "1" });
        useListener(this.env.bus, "MENUS:APP-CHANGED", () => render(this));
    }

    get visible() {
        return !this.ui.isSmall && !this.pwa.isScopedApp;
    }

    get groups() {
        return groupApplications(this.menu.getApps());
    }

    get currentAppId() {
        return this.menu.getCurrentApp()?.id;
    }

    toggleExpanded() {
        this.state.expanded = !this.state.expanded;
        browser.localStorage.setItem(this.storageKey, this.state.expanded ? "1" : "0");
    }

    canOpen(app) {
        return Boolean(app.actionID) && (!this.offline.isOffline() || this.offline.isAvailableOffline(app.actionID));
    }

    openApp(app) {
        return this.menu.selectMenu(app);
    }

    openCommandPalette() {
        this.command.openMainPalette();
    }
}

patch(WebClient, {
    components: { ...WebClient.components, NodoApplicationSidebar },
});
