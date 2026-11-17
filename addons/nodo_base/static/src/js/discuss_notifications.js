import { computed, signal, useEffect, usePlugin } from "@odoo/owl";
import { OutOfFocusService } from "@mail/core/common/out_of_focus_service";
import { Settings } from "@mail/core/common/settings_model";
import { Store } from "@mail/core/common/store_service";
import { threadActionsRegistry } from "@mail/core/common/thread_actions";
import { MessagingMenu } from "@mail/core/public_web/messaging_menu/messaging_menu";
import { MessagingMenu as MessagingMenuRecord } from "@mail/core/public_web/messaging_menu/messaging_menu_model";
import { MessagingMenuTab } from "@mail/core/public_web/messaging_menu/messaging_menu_tab_model";
import { DiscussChannel } from "@mail/discuss/core/common/discuss_channel_model";
import { DiscussNotificationSettings } from "@mail/discuss/core/common/discuss_notification_settings";
import { htmlToTextContentInline } from "@mail/utils/common/format";
import { browser } from "@web/core/browser/browser";
import { isAndroid } from "@web/core/browser/feature_detection";
import { TitlePlugin } from "@web/core/browser/title_plugin";
import { registry } from "@web/core/registry";
import { patch } from "@web/core/utils/patch";
import { session } from "@web/session";
import "@mail/core/common/out_of_focus_service_patch";
import "@mail/discuss/core/common/thread_actions";
import "@mail/discuss/core/public_web/discuss_channel_model_patch";
import "@mail/discuss/core/public_web/messaging_menu_model_patch";
import "@mail/discuss/core/public_web/messaging_menu_tab_model_patch";

const ICON = "/nodo_base/static/img/nodo-icon-192.png";
const DENIED_HELP = "浏览器已阻止通知，请在地址栏的站点设置中将「通知」设为「允许」。";
const NOTIFICATION_LABELS = { all: "所有消息", mentions: "仅提及我时", no_notif: "不提醒" };
const MUTE_LABELS = {
    "15_mins": "15 分钟", "1_hour": "1 小时", "3_hours": "3 小时",
    "8_hours": "8 小时", "24_hours": "24 小时", forever: "直到手动关闭免打扰",
};

function isInternalWebClient(store) {
    return store.self_user?.share === false && Boolean(store.env.services.action);
}

function isFocused() {
    return !document.hidden && document.hasFocus();
}

function preferences(store) {
    return store.self_user?.res_users_settings_id;
}

async function savePreference(store, field, value) {
    const settings = preferences(store);
    const values = await store.env.services.orm.call(
        "res.users.settings", "set_res_users_settings", [[settings.id], { [field]: value }]
    );
    store["res.users.settings"].insert(values);
}

patch(MessagingMenuTab.prototype, {
    _computeCounter() {
        if (!isInternalWebClient(this.store) || !["chat", "channel"].includes(this.id)) {
            return super._computeCounter(...arguments);
        }
        const model = this.store["discuss.channel"];
        // A compact snapshot covers channels that haven't been opened or loaded in the sidebar.
        // After a channel is fetched, its member counter is updated by the native bus.
        let count = 0;
        for (const item of this.store.self_user.nodo_unread_channels ?? []) {
            if (item.tab === this.id && model.get(item.id)?.fetchChannelInfoState !== "fetched") {
                count += item.count;
            }
        }
        for (const channel of this.channels ?? []) {
            if (channel.fetchChannelInfoState === "fetched") {
                count += channel.self_member_id?.message_unread_counter ?? 0;
            }
        }
        return count;
    },
});

patch(MessagingMenuRecord.prototype, {
    _computeGlobalCounter() {
        if (!isInternalWebClient(this.store)) {
            return super._computeGlobalCounter(...arguments);
        }
        return this.visibleTabs.reduce((sum, tab) => sum + (tab.important ? tab.counter ?? 0 : 0), 0);
    },
});

patch(TitlePlugin.prototype, {
    setup() {
        this.nodoUnread = signal(null);
        const originalTitle = this.title;
        this.title = computed(() => {
            const count = this.nodoUnread();
            if (count === null) {
                return originalTitle();
            }
            const baseTitle = Object.values(this.titleParts()).join(" - ") || this.defaultTitle;
            return count ? `(${count}) NODO` : baseTitle;
        });
        super.setup(...arguments);
    },
});

registry.category("services").add("nodo.discuss.title", {
    dependencies: ["mail.store", "title"],
    start(env, { "mail.store": store }) {
        const title = usePlugin(TitlePlugin);
        useEffect(() => {
            if (isInternalWebClient(store)) {
                title.nodoUnread.set(store.messagingMenu.globalCounter);
            }
        });
    },
});

patch(DiscussChannel.prototype, {
    get inChathubOnNewMessage() {
        return !isInternalWebClient(this.store) && super.inChathubOnNewMessage;
    },

    shouldNotifyMessageToUser(message) {
        if (isInternalWebClient(this.store)) {
            if (this.self_member_id?.mute_until_dt || (isFocused() && this.isDisplayed)) {
                return false;
            }
        }
        return super.shouldNotifyMessageToUser(message);
    },
});

patch(OutOfFocusService.prototype, {
    setup() {
        super.setup(...arguments);
        if (typeof BroadcastChannel === "function") {
            this.nodoFocusChannel = new BroadcastChannel(`nodo.discuss.focus:${session.db}:${session.uid}`);
            this.nodoFocusChannel.addEventListener("message", ({ data }) => {
                if (data?.request && isFocused()) {
                    this.nodoFocusChannel.postMessage({ focused: data.request });
                }
            });
        }
    },

    async nodoCanNotifyOnThisTab() {
        if (isFocused()) {
            return true;
        }
        if (!(await this.multiTab.isOnMainTab())) {
            return false;
        }
        const channel = this.nodoFocusChannel;
        if (!channel) {
            return true;
        }
        // The native main tab may be hidden while another tab is reading this conversation.
        const request = Math.random().toString(36);
        return new Promise((resolve) => {
            const finish = (canNotify) => {
                browser.clearTimeout(deadline);
                channel.removeEventListener("message", onReply);
                resolve(canNotify);
            };
            const onReply = ({ data }) => {
                if (data?.focused === request) {
                    finish(false);
                }
            };
            const deadline = browser.setTimeout(() => finish(true), 100);
            channel.addEventListener("message", onReply);
            channel.postMessage({ request });
        });
    },

    async notify(message, thread) {
        if (!isInternalWebClient(this.store) || !thread.channel) {
            return super.notify(...arguments);
        }
        if (this.contributingMessageLocalIds.has(message.localId)) {
            return;
        }
        this.contributingMessageLocalIds.add(message.localId);
        if (!(await this.nodoCanNotifyOnThisTab()) || !thread.channel.shouldNotifyMessageToUser(message)) {
            return;
        }

        const channel = thread.channel;
        const sender = message.authorName || "新消息";
        const desktopTitle = (channel.channel_type === "channel" && thread.displayName) || sender;
        const body = htmlToTextContentInline(message.previewText).replace(/\s+/g, " ").trim()
            .slice(0, 180) || "你收到了一条新消息。";
        const openConversation = () => this.env.services.action.doAction("mail.action_discuss", {
            additionalContext: { active_id: `discuss.channel_${channel.id}` },
        });
        const showToast = () => {
            this.nodoCloseToast?.();
            this.nodoCloseToast = this.notificationService.add(body, {
                title: sender,
                type: "info",
                className: "o_nodo_chat_notification",
                buttons: [{
                    name: "打开会话",
                    primary: true,
                    onClick: () => {
                        this.nodoCloseToast?.();
                        return openConversation();
                    },
                }],
            });
            this._playSound();
        };
        if (isFocused() && !this.store.discuss.isActive) {
            showToast();
            return;
        }
        if (!preferences(this.store)?.nodo_desktop_notifications || !this.canSendNativeNotification) {
            if (!this.store.discuss.isActive) {
                showToast();
            } else {
                this._playSound();
            }
            return;
        }
        // Keep the native service worker responsible for desktop delivery when subscribed.
        if (await this.hasServiceWorkInstalledAndPushSubscriptionActive().catch(() => false)) {
            return;
        }
        if (!channel.shouldNotifyMessageToUser(message)) {
            return;
        }
        try {
            const native = new browser.Notification(desktopTitle, { body, icon: ICON, silent: true });
            native.addEventListener("click", () => {
                window.focus();
                native.close();
                openConversation();
            });
            this._playSound();
        } catch {
            if (!this.store.discuss.isActive) {
                showToast();
            } else {
                this._playSound();
            }
        }
    },

    async _playSound() {
        if (!isInternalWebClient(this.store)) {
            return super._playSound(...arguments);
        }
        if (preferences(this.store)?.nodo_message_sound && this.canPlayAudio &&
            !(isAndroid() && this.canSendNativeNotification) &&
            (isFocused() || (await this.multiTab.isOnMainTab()))) {
            this.soundEffectService.play("new-message");
        }
    },
});

patch(Store.prototype, {
    onStarted() {
        super.onStarted(...arguments);
        this.env.bus.addEventListener("discuss.channel/delete", ({ detail: { channel } }) => {
            if (this.self_user?.nodo_unread_channels) {
                this.self_user.nodo_unread_channels = this.self_user.nodo_unread_channels.filter(
                    (item) => item.id !== channel.id
                );
            }
        });
        navigator.serviceWorker?.addEventListener("message", ({ data }) => {
            if (!isInternalWebClient(this) || data?.type !== "notification-display-request" ||
                data.payload.model !== "discuss.channel") {
                return;
            }
            const { correlationId, res_id } = data.payload;
            const channel = this["discuss.channel"].get(res_id);
            if (preferences(this)?.nodo_desktop_notifications === false ||
                channel?.self_member_id?.mute_until_dt || (isFocused() && !this.discuss.isActive)) {
                // A foreground page outside Discuss shows the native in-page toast.
                navigator.serviceWorker.controller?.postMessage({
                    type: "notification-display-response",
                    payload: { correlationId },
                });
            }
        });
    },

    onPushNotificationDisplayed({ model }) {
        if (model !== "discuss.channel" || !isInternalWebClient(this)) {
            return super.onPushNotificationDisplayed(...arguments);
        }
        // Web Push already carries the user's silent preference for system audio.
        this.updateAppBadge();
    },
});

patch(MessagingMenu.prototype, {
    get showPushPermissionRequest() {
        if (!isInternalWebClient(this.store)) {
            return super.showPushPermissionRequest;
        }
        const settings = preferences(this.store);
        return Boolean(settings?.nodo_desktop_notifications &&
            !settings.nodo_notification_hint_dismissed && !this.store.isNotificationPermissionDismissed &&
            this.notification.permission !== "granted" && this.showNotificationHubExtras);
    },

    get notificationRequest() {
        if (!isInternalWebClient(this.store)) {
            return super.notificationRequest;
        }
        let body = "开启桌面通知，及时收到新消息。";
        if (!window.isSecureContext) {
            body = "此地址无法启用桌面通知，请使用 HTTPS 地址。";
        } else if (!this.nodoCanRequestPermission) {
            body = DENIED_HELP;
        }
        return { ...super.notificationRequest, displayName: "打开通知", body };
    },

    get nodoCanRequestPermission() {
        return window.isSecureContext && Boolean(browser.Notification) &&
            this.notification.permission === "prompt";
    },

    async onNodoEnableNotifications() {
        if (this.nodoCanRequestPermission) {
            const permission = await browser.Notification.requestPermission();
            this.notification.permission = permission === "default" ? "prompt" : permission;
        }
    },

    async onNodoDismissNotificationHint() {
        if (isInternalWebClient(this.store)) {
            await savePreference(this.store, "nodo_notification_hint_dismissed", true);
        } else {
            this.store.isNotificationPermissionDismissed = true;
        }
    },
});

patch(DiscussNotificationSettings.prototype, {
    get nodoMessageSound() {
        return preferences(this.store)?.nodo_message_sound ?? this.store.settings.messageSound;
    },

    onChangeMessageSound(event) {
        if (!isInternalWebClient(this.store)) {
            return super.onChangeMessageSound(...arguments);
        }
        return savePreference(this.store, "nodo_message_sound", event.target.checked);
    },
});

patch(Settings.prototype, {
    get NOTIFICATIONS() {
        return super.NOTIFICATIONS.map((setting) => ({
            ...setting, name: NOTIFICATION_LABELS[setting.label],
        }));
    },

    get MUTES() {
        return super.MUTES.map((setting) => ({ ...setting, name: MUTE_LABELS[setting.label] }));
    },

    getMuteUntilText(date) {
        if (date && date.year > luxon.DateTime.now().year + 2) {
            return MUTE_LABELS.forever;
        }
        return date ? `免打扰至 ${date.toLocaleString(luxon.DateTime.DATETIME_MED)}` : undefined;
    },
});

threadActionsRegistry.get("notification-settings").name = ({ channel }) =>
    channel.channel_type === "channel" ? "通知设置" : "会话免打扰";
