import { Component, useProps } from "@odoo/owl";
import { registry } from "@web/core/registry";
import { SearchBar } from "@web/search/search_bar/search_bar";
import { standardFieldProps } from "@web/views/fields/standard_field_props";
import { KanbanController } from "@web/views/kanban/kanban_controller";
import { kanbanView } from "@web/views/kanban/kanban_view";
import { departmentNameStyle, directoryCountLabel, StaffDirectoryLayout } from "./member_directory";
import { DirectoryBoardControlPanel } from "./public_directory";

class DepartmentIdentity extends Component {
    static template = "nodo_staff_import.DepartmentIdentity";
    props = useProps(standardFieldProps);

    get path() {
        return this.props.record.data.nodo_directory_segments || [];
    }

    get department() {
        return this.path.at(-1);
    }

    get nameStyle() {
        return departmentNameStyle(this.department?.color);
    }

    get parentPath() {
        return this.path.slice(0, -1).map(({ name }) => name).join(" / ");
    }
}

registry.category("fields").add("nodo_department_identity", {
    component: DepartmentIdentity,
    supportedTypes: ["char"],
    fieldDependencies: [{ name: "nodo_directory_segments", type: "json" }],
});

class DepartmentDirectoryLayout extends StaffDirectoryLayout {
    static rosterLabel = "部门卡片";
    static ControlPanel = DirectoryBoardControlPanel;
}

class DepartmentDirectorySearchBar extends SearchBar {
    static template = "nodo_staff_import.DepartmentDirectorySearchBar";
}

class DepartmentDirectoryController extends KanbanController {
    static template = "nodo_staff_import.DepartmentDirectory";
    static components = {
        ...KanbanController.components,
        Layout: DepartmentDirectoryLayout,
        SearchBar: DepartmentDirectorySearchBar,
    };

    get className() {
        return `${super.className} o_nodo_staff_directory o_nodo_department_directory`;
    }

    get departmentCountLabel() {
        return directoryCountLabel(this.model, "个部门");
    }
}

registry.category("views").add("nodo_department_directory", {
    ...kanbanView,
    Controller: DepartmentDirectoryController,
});
