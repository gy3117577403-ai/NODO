import "@hr/views/form_view";
import "@mail/chatter/web/form_compiler";
import { registry } from "@web/core/registry";
import { createElement } from "@web/core/utils/xml";
import { buildM2OFieldDescription, Many2OneField } from "@web/views/fields/many2one/many2one_field";
import { FormCompiler } from "@web/views/form/form_compiler";

class StaffJobField extends Many2OneField {
    static template = "nodo_staff_import.StaffJobField";

    clearJob() {
        return this.props.record.update({ [this.props.name]: false, job_title: false });
    }
}

registry.category("fields").add("nodo_staff_job", buildM2OFieldDescription(StaffJobField));

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
