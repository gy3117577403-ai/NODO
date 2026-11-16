import { patch } from "@web/core/utils/patch";
import { Message } from "@mail/core/common/message";
import { threadActionsRegistry } from "@mail/core/common/thread_actions";
import { MessagingMenuTab } from "@mail/core/public_web/messaging_menu/messaging_menu_tab_model";
// 先加载上游的通话按钮定义，再在下面移除，保证移除生效
import "@mail/discuss/call/common/thread_actions";

// 讨论窄栏不显示「会议」；音视频通话在内网环境验证可用前不开放
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

// 讨论主界面里，自己在聊天和频道中发的消息靠右（上游只在右下角小窗口里这样显示）
patch(Message.prototype, {
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
