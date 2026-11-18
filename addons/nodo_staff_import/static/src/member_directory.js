import { Component, onMounted, onWillDestroy, onWillStart, signal, types as t, useProps } from "@odoo/owl";
import { EmployeeListController } from "@hr/views/hr_list_view";
import { registry } from "@web/core/registry";
import { user } from "@web/core/user";
import { useService } from "@web/core/utils/hooks";
import { useSubEnv } from "@web/owl2/utils";
import { standardFieldProps } from "@web/views/fields/standard_field_props";
import { ListRenderer } from "@web/views/list/list_renderer";
import { listView } from "@web/views/list/list_view";

class StaffMemberIdentity extends Component {
    static template = "nodo_staff_import.StaffMemberIdentity";
    props = useProps(standardFieldProps);
}

registry.category("fields").add("nodo_member_identity", {
    component: StaffMemberIdentity,
    supportedTypes: ["char"],
});

class MemberDialog extends Component {
    static template = "nodo_staff_import.MemberDialog";
    props = useProps({
        options: t.object(), departmentId: t.number().optional(),
        saveMember: t.function(), openEmployee: t.function(), close: t.function(),
    });
    dialogRef = signal.ref();
    draft = signal({ name: "", department: 0, number: "", job: 0 });
    problem = signal(null);
    matches = signal([]);
    saving = signal(false);

    setup() {
        const departmentId = this.props.departmentId;
        if (this.props.options.departments.some(({ id }) => id === departmentId)) {
            this.draft.set({ ...this.draft(), department: departmentId });
        }
        onMounted(() => this.dialogRef().showModal());
    }

    get jobs() {
        const departmentId = this.draft().department;
        return this.props.options.jobs.filter((job) => job.department_id[0] === departmentId);
    }

    changeField(event) {
        const { name } = event.target;
        const value = ["department", "job"].includes(name) ? Number(event.target.value) : event.target.value;
        const draft = { ...this.draft(), [name]: value };
        if (name === "department") draft.job = 0;
        this.draft.set(draft);
        this.matches.set([]);
        if (!this.problem()?.field || this.problem().field === name) this.problem.set(null);
    }

    showProblem(field, message, employeeId) {
        this.problem.set({ field, message, employeeId });
        requestAnimationFrame(() => {
            const target = field ? `[name="${field}"]` : ".staff-save-error";
            this.dialogRef()?.querySelector(target)?.focus();
        });
    }

    cancel(event) {
        event.preventDefault();
        if (!this.saving()) this.finish();
    }

    finish(result) {
        this.dialogRef().close();
        this.props.close({ result });
    }

    async viewExisting() {
        const employeeId = this.problem()?.employeeId;
        this.finish();
        await this.props.openEmployee(employeeId);
    }

    async submit(event) {
        event.preventDefault();
        if (this.saving()) return;
        const { name, number, department, job } = this.draft();
        if (!name.trim()) {
            this.showProblem("name", "请填写姓名");
            return;
        }
        if (!department) {
            this.showProblem("department", "请选择部门");
            return;
        }
        this.problem.set(null);
        this.saving.set(true);
        let result;
        try {
            result = await this.props.saveMember({
                name: name.trim(), number: number.trim(), department, job: job || false,
            }, Boolean(this.matches().length));
        } catch (error) {
            const context = error.data?.context;
            const expected = /\.(AccessError|UserError|ValidationError)$/.test(error.data?.name || "");
            this.showProblem(
                context?.supplement_field,
                expected ? error.data.message : "暂时无法添加，请重试",
                context?.employee_id
            );
        } finally {
            this.saving.set(false);
        }
        if (result?.matches) {
            this.matches.set(result.matches);
            requestAnimationFrame(() => this.dialogRef()?.querySelector(".staff-member-matches")?.focus());
        } else if (result?.id) {
            this.finish(result);
        }
    }
}

class StaffDirectoryController extends EmployeeListController {
    static template = "nodo_staff_import.StaffDirectory";
    openingMember = signal(false);
    recentMember = signal(null);

    setup() {
        super.setup();
        this.notification = useService("notification");
        useSubEnv({ nodoRecentMember: this.recentMember });
        onWillStart(async () => {
            this.nodoIsAdministrator = await user.hasGroup("base.group_system");
        });
        onWillDestroy(() => clearTimeout(this.recentMemberTimer));
    }

    get className() {
        return `${super.className} o_nodo_staff_directory`;
    }

    get nodoCanAddMember() {
        return this.nodoIsAdministrator && this.activeActions.create && !this.env.inDialog;
    }

    async createRecord(options) {
        if (this.nodoCanAddMember) return this.openMemberDialog();
        return super.createRecord(options);
    }

    async openMemberDialog() {
        if (this.openingMember() || this.offlinePlugin.isOffline()) return;
        this.openingMember.set(true);
        const context = this.props.context;
        try {
            const options = await this.orm.call("hr.employee", "nodo_member_options", [], { context });
            const departmentId = this.env.searchModel?.categories.find(
                (category) => category.fieldName === "department_id"
            )?.activeValueId || undefined;
            this.dialogService.add(MemberDialog, {
                options,
                departmentId,
                saveMember: (values, confirmed) => this.orm.silent.call(
                    "hr.employee", "nodo_add_member", [values, confirmed], { context }
                ),
                openEmployee: (id) => this.openMember(id),
            }, {
                onClose: async ({ result } = {}) => {
                    if (result) await this.memberAdded(result.id);
                    this.rootRef()?.querySelector(".o_nodo_add_member")?.focus({ preventScroll: true });
                },
            });
        } catch (error) {
            this.notification.add(error.data?.message || "暂时无法打开添加成员，请重试", { type: "danger" });
        } finally {
            this.openingMember.set(false);
        }
    }

    openMember(id) {
        return this.props.selectRecord(id, { activeIds: [id] });
    }

    async importMembers() {
        await this.actionService.doAction("nodo_staff_import.staff_import_action", {
            onClose: () => this.model.root.load(),
        });
    }

    async memberAdded(id) {
        const viewMember = { name: "查看成员", onClick: () => this.openMember(id) };
        try {
            const search = this.env.searchModel;
            if (search?.searchPanelInfo) {
                search.searchPanelInfo.shouldReload = true;
                await search._reloadSections();
            }
            await this.model.root.load();
        } catch {
            this.notification.add("成员已添加，名单未能刷新", { type: "warning", buttons: [viewMember] });
            return;
        }
        const row = this.model.root.records.find((record) => record.resId === id);
        if (row) {
            clearTimeout(this.recentMemberTimer);
            this.recentMember.set(id);
            this.recentMemberTimer = setTimeout(() => this.recentMember.set(null), 2600);
            requestAnimationFrame(() => {
                this.rootRef()?.querySelector(`tr[data-id="${row.id}"]`)?.scrollIntoView({ block: "nearest" });
            });
        }
        this.notification.add("成员已添加", { type: "success", buttons: row ? [] : [viewMember] });
    }
}

class StaffDirectoryRenderer extends ListRenderer {
    getRowClass(record) {
        const classes = super.getRowClass(record);
        return this.env.nodoRecentMember() === record.resId ? `${classes} o_nodo_staff_recent` : classes;
    }
}

registry.category("views").add("nodo_staff_directory", {
    ...listView,
    Controller: StaffDirectoryController,
    Renderer: StaffDirectoryRenderer,
    buttonTemplate: "nodo_staff_import.StaffDirectory.Buttons",
});
