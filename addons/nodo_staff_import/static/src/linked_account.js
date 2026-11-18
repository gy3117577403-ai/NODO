import { Component, onMounted, onWillStart, signal, types as t, useProps } from "@odoo/owl";
import { registry } from "@web/core/registry";
import { useService } from "@web/core/utils/hooks";
import { standardWidgetProps } from "@web/views/widgets/standard_widget_props";

function errorMessage(error, fallback) {
    const expected = /\.(AccessError|MissingError|UserError|ValidationError)$/.test(error.data?.name || "");
    return expected ? error.data.message : fallback;
}

class LinkedRoleDialog extends Component {
    static template = "nodo_staff_import.LinkedRoleDialog";
    props = useProps({ account: t.object(), save: t.function(), close: t.function() });
    dialogRef = signal.ref();
    changes = signal({});
    saving = signal(false);
    problem = signal("");

    setup() {
        onMounted(() => this.dialogRef().showModal());
    }

    selection(role) {
        return this.changes()[role.id] ?? (role.direct.length > 1 ? -1 : role.direct[0] || 0);
    }

    change(role, event) {
        const next = { ...this.changes() };
        const value = Number(event.target.value);
        if (role.direct.length < 2 && value === (role.direct[0] || 0)) delete next[role.id];
        else next[role.id] = value;
        this.problem.set("");
        this.changes.set(next);
    }

    cancel(event) {
        event.preventDefault();
        if (!this.saving()) this.finish();
    }

    finish(roles) {
        this.dialogRef().close();
        this.props.close({ roles });
    }

    async submit(event) {
        event.preventDefault();
        if (this.saving() || !Object.keys(this.changes()).length) return;
        this.saving.set(true);
        this.problem.set("");
        const { roles } = this.props.account;
        const selected = roles.flatMap(role => {
            const changed = this.changes()[role.id];
            return changed === undefined ? role.direct : changed ? [changed] : [];
        });
        try {
            const verified = await this.props.save(roles.flatMap(role => role.direct), selected);
            this.finish(verified);
        } catch (error) {
            this.problem.set(errorMessage(error, "暂时无法保存角色，请重试"));
            requestAnimationFrame(() => this.dialogRef()?.querySelector(".staff-save-error")?.focus());
        } finally {
            this.saving.set(false);
        }
    }
}

class LinkedAccount extends Component {
    static template = "nodo_staff_import.LinkedAccount";
    props = useProps(standardWidgetProps);
    account = signal(null);
    problem = signal("");
    opening = signal(false);
    roleTrigger = signal.ref();

    setup() {
        this.orm = useService("orm");
        this.dialog = useService("dialog");
        this.action = useService("action");
        this.notification = useService("notification");
        onWillStart(async () => {
            try {
                this.account.set(await this.call("nodo_linked_account_info"));
            } catch (error) {
                this.problem.set(errorMessage(error, "暂时无法读取关联用户，请刷新后重试"));
            }
        });
    }

    call(method, ...args) {
        const { record } = this.props;
        return this.orm.silent.call("hr.employee", method, [[record.resId], ...args], { context: record.context });
    }

    get roleLabels() {
        return [...new Set(this.account().roles.flatMap(role => [
            ...role.choices.filter(choice => role.direct.includes(choice.id)).map(choice => choice.name),
            ...role.inherited,
        ]))];
    }

    editRoles() {
        const account = this.account();
        this.dialog.add(LinkedRoleDialog, {
            account,
            save: (original, selected) => this.call("nodo_save_linked_roles", account.userId, original, selected),
        }, {
            onClose: ({ roles } = {}) => {
                if (roles) {
                    this.account.set({ ...account, roles });
                    this.notification.add("业务角色已保存", { type: "success" });
                }
                this.roleTrigger()?.focus({ preventScroll: true });
            },
        });
    }

    async openAction(method) {
        if (this.opening()) return;
        this.opening.set(true);
        try {
            const action = await this.call(method, this.account().userId);
            await this.action.doAction(action);
        } catch (error) {
            this.notification.add(errorMessage(error, "暂时无法打开，请重试"), { type: "danger" });
        } finally {
            this.opening.set(false);
        }
    }
}

class PasswordAccountSummary extends Component {
    static template = "nodo_staff_import.PasswordAccountSummary";
    props = useProps(standardWidgetProps);
}

const widgets = registry.category("view_widgets");
widgets.add("nodo_linked_account", { component: LinkedAccount });
widgets.add("nodo_password_account_summary", { component: PasswordAccountSummary });
