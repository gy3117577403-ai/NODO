import { proxy } from "@odoo/owl";
import { ResPartner } from "@mail/core/common/res_partner_model";
import { threadActionsRegistry } from "@mail/core/common/thread_actions";
import { Thread } from "@mail/core/common/thread_model";
import "@mail/core/public_web/thread_model_patch";
import { ChannelInvitation } from "@mail/discuss/core/common/channel_invitation";
import "@mail/discuss/core/common/thread_actions";
import { ConfirmationDialog } from "@web/core/confirmation_dialog/confirmation_dialog";
import { patch } from "@web/core/utils/patch";

const PRESENCE_LABELS = { online: "在线", busy: "在线", away: "离开", offline: "离线" };

function isGroupChat(channel) {
    return channel?.channel_type === "group" && channel.default_display_mode !== "video_full_screen";
}

patch(ResPartner.prototype, {
    setup() {
        super.setup(...arguments);
        this.nodo_chat_roles = undefined;
    },

    get nodoChatRoleLabel() {
        if (Array.isArray(this.nodo_chat_roles)) {
            return this.nodo_chat_roles.join("、") || "未分配角色";
        }
    },

    get nodoChatPresenceLabel() {
        return PRESENCE_LABELS[this.imStatusUI];
    },
});

patch(ChannelInvitation.prototype, {
    setup() {
        super.setup(...arguments);
        this.nodoDirectory = proxy({ role: "", roleOptions: [], queryVersion: 0 });
    },

    get nodoUsesChatDirectory() {
        if (this.store.self_user?.share !== false) {
            return false;
        }
        const channel = this.props.channel;
        return !channel || channel.channel_type === "chat" || isGroupChat(channel);
    },

    get searchPlaceholder() {
        return this.nodoUsesChatDirectory ? "搜索姓名或角色" : super.searchPlaceholder;
    },

    get inviteTitle() {
        if (this.nodoUsesChatDirectory && this.props.channel?.channel_type === "group") {
            return "添加成员";
        }
        return super.inviteTitle;
    },

    get invitationButtonText() {
        if (this.nodoUsesChatDirectory && !this.props.channel) {
            return this.selectedPartners.length > 1 ? "创建群聊" : "发起私聊";
        }
        if (this.nodoUsesChatDirectory && this.props.channel?.channel_type === "group") {
            return "添加到群聊";
        }
        return super.invitationButtonText;
    },

    onInput() {
        if (!this.nodoUsesChatDirectory) {
            return super.onInput(...arguments);
        }
        this.searchStr = this.inputRef()?.value ?? "";
        this.queueNodoPeopleSearch();
    },

    selectNodoRole(role) {
        if (role === this.nodoDirectory.role) {
            return;
        }
        this.nodoDirectory.role = role;
        this.queueNodoPeopleSearch();
    },

    queueNodoPeopleSearch() {
        this.nodoDirectory.queryVersion++;
        this.selectablePartners = [];
        this.state.showingPartialResults = false;
        this.state.hasPendingRequest = true;
        this.debouncedFetchPartnersToInvite();
    },

    async fetchPartnersToInvite() {
        if (!this.nodoUsesChatDirectory) {
            return super.fetchPartnersToInvite(...arguments);
        }
        const { role, queryVersion } = this.nodoDirectory;
        const searchTerm = this.searchStr;
        const channel = this.props.channel;
        this.state.hasPendingRequest = true;
        try {
            const result = await this.sequential(() => this.orm.call("res.partner", "nodo_search_chat_people", [], {
                search_term: searchTerm,
                role,
                channel_id: channel?.id,
            }));
            if (!result || queryVersion !== this.nodoDirectory.queryVersion) {
                return;
            }
            this.store.insert(result.store_data);
            this.nodoDirectory.roleOptions = [{ key: "", label: "全部" }, ...result.role_options];
            const partners = result.partner_ids.map((id) => this.store["res.partner"].get(id));
            this.selectablePartners = this.suggestionService.sortPartnerSuggestions(partners, searchTerm, channel?.thread);
            this.state.showingPartialResults = result.has_more;
        } finally {
            if (queryVersion === this.nodoDirectory.queryVersion) {
                this.state.hasPendingRequest = false;
            }
        }
    },
});

patch(threadActionsRegistry.get("leave"), {
    name({ channel }) {
        if (channel?.channel_type === "channel") {
            return "退出频道";
        }
        return isGroupChat(channel) ? "退出群聊" : super.name;
    },
});

patch(Thread.prototype, {
    askLeaveConfirmation(body) {
        const isChannel = this.channel?.channel_type === "channel";
        if (!isChannel && !isGroupChat(this.channel)) {
            return super.askLeaveConfirmation(body);
        }
        const actionName = isChannel ? "退出频道" : "退出群聊";
        return new Promise((confirm) => {
            this.store.env.services.dialog.add(ConfirmationDialog, {
                title: actionName,
                body: isChannel ? "你是频道创建者。确定退出这个频道吗？" : "退出后，需再次受邀才能进入此群。确定退出吗？",
                confirmLabel: actionName,
                cancelLabel: "取消",
                confirm,
                cancel: () => {},
            });
        });
    },
});
