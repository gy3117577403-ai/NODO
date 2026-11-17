import { computed, useEffect } from "@odoo/owl";
import { patch } from "@web/core/utils/patch";
import { registerComposerAction } from "@mail/core/common/composer_actions";
import { Message } from "@mail/core/common/message";
import { Thread } from "@mail/core/common/thread";
import { threadActionsRegistry } from "@mail/core/common/thread_actions";
import { MessagingMenu } from "@mail/core/public_web/messaging_menu/messaging_menu";
import { MessagingMenuTab } from "@mail/core/public_web/messaging_menu/messaging_menu_tab_model";
// 先加载上游的通话按钮定义和讨论列表补丁，再在下面调整，保证顺序正确
import "@mail/discuss/call/common/thread_actions";
import "@mail/discuss/core/public_web/messaging_menu_patch";

import { extractRecordRefs, insertRecordReference, NodoRecordCards, useRecordCardCache } from "./record_cards";

// ---------------------------------------------------------------------------
// 窄栏：不显示「会议」；音视频通话在内网环境验证可用前不开放
// ---------------------------------------------------------------------------
const HIDDEN_TAB_IDS = new Set(["meeting"]);
patch(MessagingMenuTab.prototype, {
    get canBeShown() {
        if (HIDDEN_TAB_IDS.has(this.id)) {
            return false;
        }
        return super.canBeShown;
    },
});

for (const actionId of ["call", "camera-call", "call-settings"]) {
    if (threadActionsRegistry.contains(actionId)) {
        threadActionsRegistry.remove(actionId);
    }
}

// ---------------------------------------------------------------------------
// 「消息」分栏按类型分组：私聊在上，下面各列最近 3 个频道和单据，点「全部」进入对应分栏
// ---------------------------------------------------------------------------
const GROUP_SIZE = 3;
patch(MessagingMenu.prototype, {
    setup() {
        super.setup(...arguments);
        this.nodoGroups = computed(() => {
            const empty = { channels: [], documents: [] };
            const state = this.state();
            const menu = this.store.messagingMenu;
            if (!menu || state.activeTab?.id !== "chat" || state.searchTerm || state.activePluginFilters.length) {
                return empty;
            }
            if (state.selectedFilter && !state.selectedFilter.isDefault) {
                return empty;
            }
            const channelTab = menu.channelTab?.canBeShown ? menu.channelTab : null;
            const documentTab = menu.notificationTab?.canBeShown ? menu.notificationTab : null;
            return {
                channelTab,
                documentTab,
                channels: channelTab ? channelTab.getSortedChannels().slice(0, GROUP_SIZE) : [],
                documents: documentTab ? documentTab.sortedMessages.slice(0, GROUP_SIZE) : [],
            };
        });
        useEffect(() => {
            const menu = this.store.messagingMenu;
            if (this.state().activeTab?.id !== "chat" || !menu) {
                return;
            }
            for (const tab of [menu.channelTab, menu.notificationTab]) {
                if (tab?.canBeShown && tab.getLoadStatus(undefined) === "new") {
                    tab.loadMore({});
                }
            }
        });
    },
});

// ---------------------------------------------------------------------------
// 消息：讨论主界面里自己发的消息靠右；正文里的单据链接显示为卡片
// ---------------------------------------------------------------------------
Message.components = { ...Message.components, NodoRecordCards };
patch(Thread.prototype, {
    setup() {
        super.setup(...arguments);
        useRecordCardCache();
    },
});
patch(Message.prototype, {
    setup() {
        super.setup(...arguments);
        this.nodoRecordRefs = computed(() => extractRecordRefs(this.message.bodyEl));
    },
    get attClass() {
        return { ...super.attClass, o_nodo_aligned_right: this.isAlignedRight && !this.env.inChatWindow };
    },
    get isAlignedRight() {
        return (
            super.isAlignedRight ||
            Boolean(
                this.env.inDiscussApp &&
                    !this.env.messageCard &&
                    this.props.message.isSelfAuthored &&
                    this.props.message.thread?.model === "discuss.channel"
            )
        );
    },
});

// ---------------------------------------------------------------------------
// 输入框「引用单据」：从已声明的类型中选单据
// ---------------------------------------------------------------------------
registerComposerAction("nodo-insert-record", {
    condition: ({ composer, store }) =>
        composer.targetThread?.model === "discuss.channel" && Boolean(store.env.services.action),
    disabledCondition: ({ owner }) => owner.areAllActionsDisabled,
    icon: "description",
    name: "引用单据",
    onSelected({ owner, store }) {
        return insertRecordReference(owner, store.env.services);
    },
    sequence: 25,
    sequenceQuick: 15,
});
