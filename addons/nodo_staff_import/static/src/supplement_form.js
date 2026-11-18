/** @odoo-module ignore **/
// The employee form and the offline design preview use the same native dialog.
(() => {
    "use strict";
    if (customElements.get("nodo-staff-supplement")) return;
    const labels = { name: "姓名", number: "人员编号", department: "部门", job: "岗位" };
    const keys = Object.keys(labels);
    let serial = 0;

    class StaffSupplement extends HTMLElement {
        open({ person, departments, field, avatarUrl, onSave, onClose }) {
            const id = "nodo-staff-" + ++serial;
            const described = (key) => `id="${id}-${key}" name="${key}" aria-describedby="${id}-${key}-error"`;
            const error = (key) => `<p class="staff-error" id="${id}-${key}-error" role="alert" hidden></p>`;
            const input = (key) => `<input ${described(key)} autocomplete="off">`;
            this.innerHTML = `<dialog class="nodo-staff-dialog" aria-labelledby="${id}-title">
              <form class="staff-form" novalidate>
                <header class="staff-header"><h2 id="${id}-title">补充员工信息</h2>
                  <button type="button" data-close class="staff-close" aria-label="关闭补充员工信息"><span aria-hidden="true"></span></button>
                </header>
                <div class="staff-body">
                  <div class="staff-summary">
                    <div class="staff-avatar" aria-hidden="true"><span></span></div>
                    <div class="staff-identity">
                      <div class="staff-name"><label class="staff-visually-hidden" for="${id}-name">姓名</label>
                        <input ${described("name")} required autocomplete="off"><i aria-hidden="true"></i>
                      </div>${error("name")}
                      <div class="staff-source"><span>架构图编号</span><span class="staff-code"></span></div>
                    </div>
                    <span class="staff-review"></span>
                  </div>
                  <div class="staff-fields">
                    <div><label for="${id}-number">人员编号</label>${input("number")}${error("number")}</div>
                    <div><label for="${id}-department">部门</label>
                      <select ${described("department")} required></select>${error("department")}
                    </div>
                    <div><label for="${id}-job">岗位</label>${input("job")}${error("job")}</div>
                  </div>
                  <p class="staff-error staff-save-error" role="alert" tabindex="-1" hidden></p>
                </div>
                <footer class="staff-footer"><span class="staff-progress" role="status" aria-atomic="true"></span>
                  <button type="button" data-close class="staff-button">取消</button>
                  <button type="submit" class="staff-button staff-primary">保存</button>
                </footer>
              </form>
            </dialog>`;
            const dialog = this.querySelector("dialog");
            const form = dialog.querySelector("form");
            const controls = form.elements;
            const review = dialog.querySelector(".staff-review");
            review.textContent = person.reviewLabel;
            review.dataset.state = person.review;
            const source = dialog.querySelector(".staff-code");
            source.textContent = person.sourceNumber || "未记录";
            const avatar = dialog.querySelector(".staff-avatar");
            avatar.firstElementChild.textContent = Array.from(person.name || "")[0] || "员";
            if (avatarUrl) {
                const image = new Image();
                image.alt = "";
                image.onload = () => avatar.replaceChildren(image);
                image.src = avatarUrl;
            }
            const select = controls.namedItem("department");
            if (!person.department) select.add(new Option("请选择部门", ""));
            for (const department of departments) select.add(new Option(department.label, department.id));
            const initial = Object.fromEntries(keys.map((key) => [key, String(person[key] || "")]));
            for (const key of keys) controls.namedItem(key).value = initial[key];
            const name = controls.namedItem("name");
            name.readOnly = person.canEditName === false;
            if (name.readOnly) name.tabIndex = -1;
            const progress = dialog.querySelector(".staff-progress");
            const generalError = dialog.querySelector(".staff-save-error");
            const submit = dialog.querySelector('[type="submit"]');
            let saving = false;
            const values = () => Object.fromEntries(keys.map((key) => [key, controls.namedItem(key).value.trim()]));
            function updateProgress() {
                const data = values();
                const missing = keys.filter((key) => !data[key]);
                const message = missing.length ? "待补 " + missing.length + " 项" :
                    (form.querySelector('[aria-invalid="true"]') ? "资料待核对" : "资料已齐");
                if (progress.textContent !== message) progress.textContent = message;
                progress.title = missing.map((key) => labels[key]).join("、");
                name.title = data.name;
                name.parentElement.dataset.value = name.value;
                select.title = select.selectedOptions[0]?.text || "";
            }
            function showError(key, message) {
                const control = controls.namedItem(key);
                const hint = form.querySelector("#" + id + "-" + key + "-error");
                hint.textContent = message;
                hint.hidden = !message;
                if (message) {
                    control.setAttribute("aria-invalid", "true");
                    control.focus();
                } else control.removeAttribute("aria-invalid");
                updateProgress();
            }
            function setSaving(value) {
                saving = value;
                form.setAttribute("aria-busy", String(value));
                for (const control of controls) control.disabled = value;
                submit.textContent = value ? "保存中…" : "保存";
            }
            form.addEventListener("input", (event) => {
                if (keys.includes(event.target.name)) showError(event.target.name, "");
                generalError.hidden = true;
                updateProgress();
            });
            form.addEventListener("submit", async (event) => {
                event.preventDefault();
                if (saving) return;
                const data = values();
                if (!data.name) return showError("name", "请填写姓名");
                if (!data.department) return showError("department", "请选择部门");
                const changes = Object.fromEntries(keys.filter((key) => data[key] !== initial[key]).map((key) => [key, data[key]]));
                if (!Object.keys(changes).length) return dialog.close();
                generalError.hidden = true;
                setSaving(true);
                try {
                    await onSave(changes);
                } catch (failure) {
                    setSaving(false);
                    if (keys.includes(failure.field)) showError(failure.field, failure.message);
                    else {
                        generalError.textContent = failure.message || "保存失败，请重试";
                        generalError.hidden = false;
                        generalError.focus();
                    }
                    return;
                }
                dialog.close("saved");
            });
            for (const button of form.querySelectorAll("[data-close]")) {
                button.addEventListener("click", () => { if (!saving) dialog.close(); });
            }
            dialog.addEventListener("cancel", (event) => { if (saving) event.preventDefault(); });
            dialog.addEventListener("keydown", (event) => {
                if (event.key === "Tab" && !saving) {
                    const stops = Array.from(controls).filter((control) => !control.disabled && control.tabIndex >= 0);
                    const end = event.shiftKey ? stops[0] : stops.at(-1);
                    if (document.activeElement === end) {
                        event.preventDefault();
                        (event.shiftKey ? stops.at(-1) : stops[0]).focus();
                    }
                }
                if (event.key === "Escape" || event.key === "Tab" || event.isComposing) event.stopPropagation();
            });
            dialog.addEventListener("close", () => {
                const saved = dialog.returnValue === "saved";
                onClose(saved);
            }, { once: true });
            updateProgress();
            const first = field || keys.find((key) => !initial[key] && !controls.namedItem(key).readOnly) || "number";
            controls.namedItem(first).autofocus = true;
            dialog.showModal();
        }
    }
    customElements.define("nodo-staff-supplement", StaffSupplement);
})();
