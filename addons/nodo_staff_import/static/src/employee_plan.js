import { Component, useProps } from "@odoo/owl";
import { registry } from "@web/core/registry";
import { SearchBar } from "@web/search/search_bar/search_bar";
import { selectionField, SelectionField } from "@web/views/fields/selection/selection_field";
import { standardFieldProps } from "@web/views/fields/standard_field_props";
import { KanbanController } from "@web/views/kanban/kanban_controller";
import { kanbanView } from "@web/views/kanban/kanban_view";
import { ListController } from "@web/views/list/list_controller";
import { listView } from "@web/views/list/list_view";
import { directoryCountLabel, StaffDirectoryControlPanel, StaffDirectoryLayout } from "./member_directory";

const DELAY_UNITS = { days: "天", weeks: "周", months: "个月" };
const EMPLOYEE_PLAN_CHOICES = {
    responsible_type: {
        on_demand: "启动时指定",
        other: "指定人员",
        role: "指定角色",
        manager: "直属上级",
        employee: "员工本人",
    },
    delay_unit: DELAY_UNITS,
    delay_from: { before_plan_date: "计划日期前", after_plan_date: "计划日期后" },
};

class EmployeePlanSelection extends SelectionField {
    get options() {
        const choices = EMPLOYEE_PLAN_CHOICES[this.props.name];
        return super.options.map(([value, label]) => [value, choices?.[value] ?? label]);
    }
}

class EmployeePlanScope extends Component {
    static template = "nodo_staff_import.EmployeePlanScope";
    props = useProps(standardFieldProps);

    get department() {
        return this.props.record.data[this.props.name]?.display_name;
    }
}

class EmployeePlanDeadline extends Component {
    static template = "nodo_staff_import.EmployeePlanDeadline";
    props = useProps(standardFieldProps);

    get label() {
        const { delay_count: count, delay_from: from, delay_unit: unit } = this.props.record.data;
        if (!count) {
            return "计划当天";
        }
        return `${EMPLOYEE_PLAN_CHOICES.delay_from[from]} ${count} ${DELAY_UNITS[unit]}`;
    }
}

const fields = registry.category("fields");
fields.add("nodo_employee_plan_selection", { ...selectionField, component: EmployeePlanSelection });
fields.add("nodo_employee_plan_scope", {
    component: EmployeePlanScope,
    supportedTypes: ["many2one"],
    isEmpty: () => false,
});
fields.add("nodo_employee_plan_deadline", {
    component: EmployeePlanDeadline,
    supportedTypes: ["integer"],
    fieldDependencies: [
        { name: "delay_from", type: "selection" },
        { name: "delay_unit", type: "selection" },
    ],
    isEmpty: () => false,
});

class EmployeePlanControlPanel extends StaffDirectoryControlPanel {
    static template = "nodo_staff_import.EmployeePlanControlPanel";
}

class EmployeePlanLayout extends StaffDirectoryLayout {
    static rosterLabel = "员工计划";
    static ControlPanel = EmployeePlanControlPanel;
}

class EmployeePlanSearchBar extends SearchBar {
    static template = "nodo_staff_import.EmployeePlanSearchBar";
}

class EmployeePlanListController extends ListController {
    static template = "nodo_staff_import.EmployeePlanList";
    static components = {
        ...ListController.components,
        Layout: EmployeePlanLayout,
        SearchBar: EmployeePlanSearchBar,
    };

    get className() {
        return `${super.className} o_nodo_staff_directory o_nodo_employee_plan_index`;
    }

    get planCountLabel() {
        return directoryCountLabel(this.model, "个计划");
    }

    get canCreatePlan() {
        return this.activeActions.create && !this.hasSelectedRecords;
    }
}

class EmployeePlanKanbanController extends KanbanController {
    static template = "nodo_staff_import.EmployeePlanKanban";
    static components = {
        ...KanbanController.components,
        Layout: EmployeePlanLayout,
        SearchBar: EmployeePlanSearchBar,
    };

    get className() {
        return `${super.className} o_nodo_staff_directory o_nodo_employee_plan_index`;
    }

    get planCountLabel() {
        return directoryCountLabel(this.model, "个计划");
    }

    get canCreatePlan() {
        return this.canCreate && !this.hasSelectedRecords;
    }
}

const views = registry.category("views");
views.add("nodo_employee_plan_list", { ...listView, Controller: EmployeePlanListController });
views.add("nodo_employee_plan_kanban", { ...kanbanView, Controller: EmployeePlanKanbanController });
