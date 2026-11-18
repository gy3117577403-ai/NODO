import { registry } from "@web/core/registry";
import { SearchBar } from "@web/search/search_bar/search_bar";
import { KanbanController } from "@web/views/kanban/kanban_controller";
import { kanbanView } from "@web/views/kanban/kanban_view";
import { directoryCountLabel, StaffDirectoryControlPanel, StaffDirectoryLayout } from "./member_directory";

export class DirectoryBoardControlPanel extends StaffDirectoryControlPanel {
    get showDirectoryPager() {
        return this.pagerProps?.total > 0;
    }
}

class PublicDirectoryLayout extends StaffDirectoryLayout {
    static rosterLabel = "员工目录";
    static ControlPanel = DirectoryBoardControlPanel;
}

class PublicDirectorySearchBar extends SearchBar {
    static template = "nodo_staff_import.PublicDirectorySearchBar";
}

class PublicDirectoryController extends KanbanController {
    static template = "nodo_staff_import.PublicDirectory";
    static components = {
        ...KanbanController.components,
        Layout: PublicDirectoryLayout,
        SearchBar: PublicDirectorySearchBar,
    };

    get className() {
        return `${super.className} o_nodo_staff_directory o_nodo_public_directory`;
    }

    get memberCountLabel() {
        return directoryCountLabel(this.model, "位成员");
    }
}

registry.category("views").add("nodo_public_directory", {
    ...kanbanView,
    Controller: PublicDirectoryController,
});
