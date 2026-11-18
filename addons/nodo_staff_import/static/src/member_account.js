import { Component, onMounted, signal, types as t, useProps } from "@odoo/owl";
import { registry } from "@web/core/registry";
import { useService } from "@web/core/utils/hooks";

class MemberAccountDialog extends Component {
    static template = "nodo_staff_import.MemberAccountDialog";
    props = useProps({ employee: t.object(), context: t.object(), close: t.function() });
    dialogRef = signal.ref();
    login = signal("");
    problem = signal(null);
    saving = signal(false);

    setup() {
        this.orm = useService("orm");
        onMounted(() => this.dialogRef().showModal());
    }

    changeLogin(event) {
        this.login.set(event.target.value);
        this.problem.set(null);
    }

    showProblem(field, message) {
        this.problem.set({ field, message });
        requestAnimationFrame(() => {
            const target = field ? '[name="login"]' : ".staff-save-error";
            this.dialogRef()?.querySelector(target)?.focus();
        });
    }

    cancel(event) {
        event.preventDefault();
        if (!this.saving()) this.finish(false);
    }

    finish(saved) {
        this.dialogRef().close();
        this.props.close({ saved });
    }

    async submit(event) {
        event.preventDefault();
        if (this.saving()) return;
        const login = this.login().trim();
        if (!login) {
            this.showProblem(true, "请填写登录名");
            return;
        }
        this.problem.set(null);
        this.saving.set(true);
        try {
            await this.orm.silent.call("hr.employee", "nodo_create_member_account", [
                [this.props.employee.id], login,
            ], { context: this.props.context });
        } catch (error) {
            const expected = /\.(AccessError|MissingError|UserError|ValidationError)$/.test(error.data?.name || "");
            this.showProblem(error.data?.context?.supplement_field === "login",
                expected ? error.data.message : "暂时无法开通账号，请重试");
            return;
        } finally {
            this.saving.set(false);
        }
        this.finish(true);
    }
}

registry.category("actions").add("nodo_staff_open_account", async (env, action, options) => {
    const { dialog, notification } = env.services;
    const result = await new Promise((resolve) => {
        dialog.add(MemberAccountDialog, { employee: action.params, context: action.context }, { onClose: resolve });
    });
    if (!result?.saved) {
        requestAnimationFrame(() => {
            document.querySelector('button[name="action_nodo_open_member_account"]:not(:disabled)')?.focus();
        });
        return;
    }
    try {
        await options.onClose?.();
        notification.add("账号已开通", { type: "success" });
    } catch {
        notification.add("账号已开通，刷新员工档案后查看", { type: "warning" });
    }
});
