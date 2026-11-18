import "@hr/views/form_view";
import "@mail/chatter/web/form_compiler";
import { registry } from "@web/core/registry";
import { createElement } from "@web/core/utils/xml";
import { FormCompiler } from "@web/views/form/form_compiler";

class StaffDetailCompiler extends FormCompiler {
    compileForm(node, params) {
        const form = super.compileForm(node, params);
        form.classList.add("o_nodo_staff_detail");
        return form;
    }

    compile(node, params) {
        const result = super.compile(node, params);
        const chatter = result.querySelector(".o-mail-Form-chatter");
        if (chatter) {
            const title = createElement("h2", { class: "o_nodo_staff_activity_title" });
            title.textContent = "活动记录";
            chatter.prepend(title);
        }
        return result;
    }
}

const views = registry.category("views");
views.add("nodo_staff_employee_form", {
    ...views.get("hr_employee_form"),
    Compiler: StaffDetailCompiler,
});
