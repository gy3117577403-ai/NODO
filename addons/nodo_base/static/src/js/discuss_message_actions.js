import { signal, useEffect } from "@odoo/owl";
import { Message } from "@mail/core/common/message";
import { Message as MessageModel } from "@mail/core/common/message_model";
import { Thread } from "@mail/core/common/thread_model";
import { messageActionsRegistry } from "@mail/core/common/message_actions";
import { fields } from "@mail/model/export";
import "@mail/core/public_web/message_actions_patch";
import "@mail/core/web/message_actions_patch";
import "@mail/discuss/core/common/message_actions";
import "@mail/discuss/core/common/message_model_patch";
import "@mail/discuss/core/public_web/message_actions";
import { ConfirmationDialog } from "@web/core/confirmation_dialog/confirmation_dialog";
import { user } from "@web/core/user";
import { patch } from "@web/core/utils/patch";

function isChatMessage(message) {
    return message.thread?.model === "discuss.channel";
}

patch(MessageModel.prototype, {
    setup() {
        super.setup(...arguments);
        this.nodo_removal = undefined;
        this.nodo_edit_deadline = fields.Datetime();
    },

    get nodoWithinEditTime() {
        const deadline = this.nodo_edit_deadline?.toMillis();
        return Boolean(this.isSelfAuthored && !this.nodo_removal && deadline > Date.now());
    },

    get editable() {
        return super.editable && (!isChatMessage(this) || this.nodoWithinEditTime);
    },

    showSeenIndicator(thread) {
        return thread?.model !== "discuss.channel" && super.showSeenIndicator(thread);
    },
});

patch(Thread.prototype, {
    setup() {
        super.setup(...arguments);
        this.nodoLastOwnChatMessage = this.computed(() =>
            this.channel?.channel_type === "chat" &&
            this.newestPersistentAllMessages.find(
                (message) => message.isSelfAuthored && message.message_type === "comment" &&
                    !message.isEmpty && !message.nodo_removal
            )
        );
    },
});

patch(Message.prototype, {
    setup() {
        super.setup(...arguments);
        this.nodoDeadlineReached = signal(false);
        useEffect(() => {
            this.nodoDeadlineReached.set(false);
            if (!isChatMessage(this.message) || !this.message.isSelfAuthored || this.message.nodo_removal) {
                return;
            }
            const remaining = this.message.nodo_edit_deadline?.toMillis() - Date.now();
            if (remaining > 0) {
                const timer = setTimeout(() => this.nodoDeadlineReached.set(true), remaining);
                return () => clearTimeout(timer);
            }
        });
    },

    get nodoShowSeen() {
        return !this.env.messageCard && !this.isEditing &&
            this.props.thread?.nodoLastOwnChatMessage?.eq?.(this.message);
    },

    get nodoWithinEditTime() {
        return !this.nodoDeadlineReached() && this.message.nodoWithinEditTime;
    },
});

function configure(id, changes) {
    if (messageActionsRegistry.contains(id)) {
        const definition = messageActionsRegistry.get(id);
        messageActionsRegistry.add(id, { ...definition, ...changes(definition) }, { force: true });
    }
}

const actionLabels = {
    reaction: "添加表情回应",
    reactions: "查看回应",
    "reply-to": "回复",
    pin: "置顶",
    unpin: "取消置顶",
    edit: "编辑",
    "copy-message": "复制文本",
    "copy-link": "复制消息链接",
    "set-new-message-separator": "标为未读",
    "mark-as-unread": "标为未读",
    "mark-as-read": "标为已读",
    download_files: "下载附件",
    "create-or-view-thread": ({ message }) => message.linkedSubChannel ? "查看讨论串" : "发起讨论串",
    "toggle-translation": ({ message }) => message.showTranslation ? "查看原文" : "翻译",
};

function actionName(name, params) {
    return typeof name === "function" ? name(params) : name;
}

for (const [id, label] of Object.entries(actionLabels)) {
    configure(id, (native) => ({
        name: (params) => actionName(isChatMessage(params.message) ? label : native.name, params),
        condition: (params) => native.condition(params) &&
            (!isChatMessage(params.message) || (!params.message.nodo_removal &&
                (id !== "edit" || params.owner.nodoWithinEditTime))),
    }));
}

for (const id of ["add-bookmark", "remove-bookmark", "forward", "end-poll"]) {
    configure(id, (native) => ({
        condition: (params) => !isChatMessage(params.message) && native.condition(params),
    }));
}

function canRecall({ owner, message }) {
    return owner.nodoWithinEditTime ?? message.nodoWithinEditTime;
}

configure("delete", (native) => ({
    condition: (params) => {
        const { message } = params;
        if (!isChatMessage(message)) {
            return native.condition(params);
        }
        return message.persistent && !message.isEmpty && !message.nodo_removal &&
            (canRecall(params) || user.isSystem);
    },
    name: (params) => isChatMessage(params.message)
        ? (canRecall(params) ? "撤回" : "管理员删除")
        : actionName(native.name, params),
    onSelected: (params) => {
        const { message, owner, store } = params;
        if (!isChatMessage(message)) {
            return native.onSelected(params);
        }
        const recall = canRecall(params);
        const { dialog, orm } = owner.env.services;
        dialog.add(ConfirmationDialog, {
            title: recall ? "撤回消息" : "管理员删除消息",
            body: recall ? "撤回后，会话成员会看到一条撤回提示。" : "删除后，会话成员会看到一条管理员删除提示。",
            confirmLabel: recall ? "撤回" : "管理员删除",
            confirmClass: "btn-danger",
            cancelLabel: "取消",
            confirm: async () => {
                const data = await orm.call("mail.message", "nodo_remove_discuss_message", [[message.id]]);
                store.insert(data);
            },
        });
    },
}));
