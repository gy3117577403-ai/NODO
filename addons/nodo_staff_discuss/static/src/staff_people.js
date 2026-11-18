import { ResPartner } from "@mail/core/common/res_partner_model";
import { ChannelInvitation } from "@mail/discuss/core/common/channel_invitation";
import "@nodo_base/js/discuss_people";
import { patch } from "@web/core/utils/patch";

patch(ResPartner.prototype, {
    setup() {
        super.setup(...arguments);
        this.nodo_chat_department = "";
    },
});

patch(ChannelInvitation.prototype, {
    setup() {
        super.setup(...arguments);
        this.nodoDirectory.department = 0;
        this.nodoDirectory.departmentOptions = [];
        this.nodoDirectory.saving = false;
    },

    get nodoUsesStaffPicker() {
        return this.store.self_user?.share === false &&
            this.props.channel?.default_display_mode !== "video_full_screen";
    },

    get nodoUsesChatDirectory() {
        return this.nodoUsesStaffPicker || super.nodoUsesChatDirectory;
    },

    get nodoPeopleSearchFilters() {
        return {
            ...super.nodoPeopleSearchFilters,
            department_id: this.nodoDirectory.department || false,
        };
    },

    applyNodoPeopleSearchOptions(result) {
        super.applyNodoPeopleSearchOptions(result);
        this.nodoDirectory.departmentOptions = result.department_options;
    },

    selectNodoDepartment(event) {
        this.nodoDirectory.department = Number(event.target.value);
        this.queueNodoPeopleSearch();
    },

    get searchPlaceholder() {
        return this.nodoUsesStaffPicker ? "搜索姓名、部门或角色" : super.searchPlaceholder;
    },

    get inviteTitle() {
        if (this.nodoUsesStaffPicker && this.props.channel?.channel_type === "channel") {
            return "添加频道成员";
        }
        return super.inviteTitle;
    },

    get invitationButtonText() {
        if (this.nodoUsesStaffPicker && this.props.channel?.channel_type === "channel") {
            return this.nodoDirectory.saving ? "正在添加…" : "添加到频道";
        }
        return super.invitationButtonText;
    },

    get nodoStaffEmptyText() {
        if (this.searchStr || this.nodoDirectory.department || this.nodoDirectory.role) {
            return "没有找到符合筛选条件的同事。";
        }
        if (this.props.channel?.channel_type === "channel") {
            return "暂无已开通且符合频道权限的同事。";
        }
        return "没有找到可添加的同事。";
    },

    async onClickInvite() {
        const channel = this.props.channel;
        if (!this.nodoUsesStaffPicker || !["channel", "group"].includes(channel?.channel_type)) {
            return super.onClickInvite(...arguments);
        }
        if (this.nodoDirectory.saving || !this.selectedPartners.length) {
            return;
        }
        this.nodoDirectory.saving = true;
        try {
            const partnerIds = this.selectedPartners.map((partner) => partner.id);
            const result = await this.orm.call("discuss.channel", "nodo_add_staff_members", [[channel.id], partnerIds]);
            this.store.insert(result.store_data);
            this.notification.add(
                result.added_count ? `已添加 ${result.added_count} 位成员` : "所选同事已是成员",
                { type: "success" },
            );
            this.selectedPartners = [];
            this.props.close?.();
        } finally {
            this.nodoDirectory.saving = false;
        }
    },
});
