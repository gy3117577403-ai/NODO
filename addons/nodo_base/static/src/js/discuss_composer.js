import { Attachment } from "@mail/core/common/attachment_model";
import { AttachmentUploadService } from "@mail/core/common/attachment_upload_service";
import { Composer } from "@mail/core/common/composer";
import { composerActionsRegistry } from "@mail/core/common/composer_actions";
import "@mail/discuss/voice_message/common/composer_actions_patch";
import { DiscussChannel } from "@mail/discuss/core/common/discuss_channel_model";
import { fields } from "@mail/model/export";
import { patch } from "@web/core/utils/patch";

patch(Composer.prototype, {
    get placeholder() {
        if (this.thread?.model === "discuss.channel") {
            return this.props.composer.message
                ? "Enter 保存，Shift + Enter 换行"
                : "输入消息，Enter 发送，Shift + Enter 换行";
        }
        return super.placeholder;
    },
});

for (const id of ["voice-start", "voice-recording", "create-poll"]) {
    if (composerActionsRegistry.contains(id)) {
        const action = composerActionsRegistry.get(id);
        composerActionsRegistry.add(id, {
            ...action,
            condition: (params) => params.composer.targetThread?.model !== "discuss.channel" &&
                action.condition(params),
        }, { force: true });
    }
}

patch(DiscussChannel.prototype, {
    setup() {
        super.setup(...arguments);
        this.nodo_file_limit_mb = undefined;
    },
});

patch(Attachment.prototype, {
    setup() {
        super.setup(...arguments);
        this.nodo_upload_percent = fields.Attr(null);
    },
});

patch(AttachmentUploadService.prototype, {
    setup() {
        super.setup(...arguments);
        this.fileUploadService.bus.addEventListener("FILE_UPLOAD_ADDED", ({ detail: { upload } }) => {
            const tmpId = Number(upload.data.get("temporary_id"));
            if (this.targetsByTmpId.get(tmpId)?.thread?.model !== "discuss.channel") {
                return;
            }
            const attachment = this.store["ir.attachment"].get(tmpId);
            if (attachment) {
                attachment.nodo_upload_percent = 0;
                upload.xhr.upload.addEventListener("progress", (event) => {
                    if (event.lengthComputable && event.total && attachment.exists()) {
                        attachment.nodo_upload_percent = Math.round(100 * event.loaded / event.total);
                    }
                });
            }
        });
    },

    async upload(thread, composer, file, options) {
        if (thread?.model === "discuss.channel") {
            const maxMb = thread.channel?.nodo_file_limit_mb ?? 50;
            if (file.size > maxMb * 1024 ** 2) {
                this.notificationService.add(`单个文件不能超过 ${maxMb} MB。`, { type: "warning" });
                return;
            }
        }
        return super.upload(thread, composer, file, options);
    },
});
