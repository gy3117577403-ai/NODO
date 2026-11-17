import { ResUsers } from "@mail/core/common/res_users_model";
import { threadActionsRegistry } from "@mail/core/common/thread_actions";
import { DiscussChannel } from "@mail/discuss/core/common/discuss_channel_model";
import "@mail/discuss/core/public_web/discuss_command_palette";
import { MessagingMenuEmptyChannel } from "@mail/discuss/core/public_web/messaging_menu_empty_channel";
import "@mail/discuss/core/public_web/thread_actions";
import { registry } from "@web/core/registry";
import { patch } from "@web/core/utils/patch";
import { useEnv } from "@web/owl2/utils";

patch(ResUsers.prototype, {
    setup() {
        super.setup(...arguments);
        this.nodo_can_manage_channels = false;
    },
});

patch(DiscussChannel.prototype, {
    setup() {
        super.setup(...arguments);
        this.nodo_restrict_posting = false;
        this.nodo_can_post = undefined;
        this.onChange(
            () => {
                const policyChannel = this.parent_channel_id || this;
                return [this.isDisplayed, policyChannel, policyChannel.nodo_restrict_posting, policyChannel.nodo_can_post];
            },
            function refreshPostingPermission(isDisplayed, policyChannel, restricted, canPost) {
                if (isDisplayed && restricted && canPost == null) {
                    this.store.fetchChannel(policyChannel.id);
                }
            },
            { immediate: true }
        );
    },

    get nodoPostingBlocked() {
        return (this.nodo_restrict_posting && this.nodo_can_post !== true) ||
            Boolean(this.parent_channel_id?.nodoPostingBlocked);
    },

    get composerHidden() {
        return this.nodoPostingBlocked || super.composerHidden;
    },

    get composerHiddenText() {
        return this.nodoPostingBlocked ? "本频道仅管理员可发言" : super.composerHiddenText;
    },

    get canCreateSubChannels() {
        return !this.nodoPostingBlocked && super.canCreateSubChannels;
    },
});

patch(MessagingMenuEmptyChannel.prototype, {
    getFollowersText(channel) {
        return `${channel.member_count} 位成员`;
    },
});

patch(threadActionsRegistry.get("join-channel"), { name: "加入频道" });

// The shortcut and the channel sidebar have separate entry points for channel creation.
const conversationCommands = registry.category("command_provider").get("find_or_start_conversation");
patch(conversationCommands, {
    async provide(options) {
        const canCreate = useEnv().services["mail.store"].self_user?.nodo_can_manage_channels;
        const commands = await super.provide(options);
        return canCreate ? commands : commands.filter(
            (command) => !command.className?.includes("o-mail-DiscussCommand-createChannel")
        );
    },
});
