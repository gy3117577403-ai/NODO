import { Component, onMounted, signal, types as t, useProps, xml } from "@odoo/owl";
import { registry } from "@web/core/registry";
import { useService } from "@web/core/utils/hooks";
import { standardWidgetProps } from "@web/views/widgets/standard_widget_props";

class StaffDialog extends Component {
    static template = xml`<nodo-staff-supplement t-ref="this.host"/>`;
    host = signal.ref();
    props = useProps({
        employeeId: t.number(), context: t.object(), options: t.object(), close: t.function(),
    });
    setup() {
        this.orm = useService("orm");
        onMounted(() => this.host().open({
            ...this.props.options,
            onSave: (changes) => this.save(changes),
            onClose: (saved) => this.props.close({ saved }),
        }));
    }
    async save(changes) {
        if (Object.hasOwn(changes, "department")) changes.department = Number(changes.department);
        const initial = this.props.options.person;
        const original = Object.fromEntries(Object.keys(changes).map((key) => [key, initial[key]]));
        if (Object.hasOwn(changes, "job")) original.department = initial.department;
        try {
            await this.orm.silent.write("hr.employee", [this.props.employeeId], {
                nodo_supplement: { changes, original },
            }, { context: this.props.context });
        } catch (error) {
            const expected = /\.(AccessError|MissingError|UserError|ValidationError)$/.test(error.data?.name || "");
            const message = expected ? error.data.message : "暂时无法保存，请重试";
            throw Object.assign(new Error(message), {
                field: error.data?.context?.supplement_field,
            });
        }
    }
}

class EmployeeSupplement extends Component {
    static template = xml`
        <button t-if="this.props.record.resId and !this.props.readonly" type="button"
                class="btn btn-secondary text-nowrap" t-att-data-staff-supplement="this.props.record.resId"
                t-ref="this.trigger" t-on-click="this.open"
                t-att-disabled="this.opening()">补充信息</button>`;
    props = useProps(standardWidgetProps);
    trigger = signal.ref();
    opening = signal(false);

    setup() {
        this.orm = useService("orm");
        this.notification = useService("notification");
        this.dialog = useService("dialog");
    }

    async open() {
        if (this.opening()) return;
        this.opening.set(true);
        const record = this.props.record;
        try {
            // Follow the employee form's normal action-button save convention.
            if (await record.isDirty() && !await record.save()) return;
            const context = { ...record.context, version_id: record.data.version_id?.id };
            const [employee] = await this.orm.read("hr.employee", [record.resId], [
                "nodo_supplement", "company_id", "department_id", "write_date",
            ], { context });
            const person = employee.nodo_supplement;
            const departments = await this.orm.searchRead("hr.department", [
                ["company_id", "in", [false, employee.company_id[0]]],
            ], ["complete_name"], { context });
            const choices = departments.map((department) => ({ id: department.id, label: department.complete_name }));
            if (employee.department_id && !choices.some((item) => item.id === person.department)) {
                choices.push({ id: person.department, label: employee.department_id[1] });
            }
            choices.sort((a, b) => a.label.localeCompare(b.label, "zh-CN"));
            this.dialog.add(StaffDialog, {
                employeeId: record.resId, context,
                options: {
                    person: { ...person, canEditName: person.canEditName && !record._isReadonly("name") },
                    departments: choices,
                    avatarUrl: "/web/image/hr.employee/" + record.resId + "/avatar_128?unique=" + encodeURIComponent(employee.write_date),
                },
            }, {
                onClose: async ({ saved } = {}) => {
                    if (saved) {
                        this.notification.add("员工资料已保存", { type: "success" });
                        try { await record.load(); }
                        catch { this.notification.add("档案已保存，请刷新查看", { type: "warning" }); }
                    }
                    const entry = this.trigger() || document.querySelector('[data-staff-supplement="' + record.resId + '"]');
                    entry?.focus({ preventScroll: true });
                },
            });
        } catch (error) {
            this.notification.add(error.data?.message || "无法打开员工档案，请重试", { type: "danger" });
        } finally {
            this.opening.set(false);
        }
    }
}

registry.category("view_widgets").add("nodo_employee_supplement", { component: EmployeeSupplement });
