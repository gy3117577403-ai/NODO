"use strict";

// This preview uses fictional records. There are no API calls to the employee database.
const departments = [
  { id: "office", name: "总经办" },
  { id: "sales", parent: "office", name: "销售部", headcount: 18, jobs: ["销售专员", "商务助理", "销售主管"] },
  { id: "engineering", parent: "office", name: "技术部", headcount: 16, jobs: ["工艺技术", "技术核对员", "电气设计"] },
  { id: "purchasing", parent: "office", name: "采购部", headcount: 11, jobs: ["采购经办", "采购助理", "采购经理"] },
  { id: "production", parent: "office", name: "生产计划部", headcount: 3, jobs: ["生产协调", "计划跟单"] },
  { id: "warehouse", parent: "production", name: "仓库", headcount: 9, jobs: ["仓库管理员", "仓库主管"] },
  { id: "workshop", parent: "production", name: "车间" },
  { id: "sheet", parent: "workshop", name: "钣金组", headcount: 19, jobs: ["激光下料", "折弯操作", "焊接工"] },
  { id: "wire", parent: "workshop", name: "接线组", headcount: 20, jobs: ["接线操作", "接线组长"] },
  { id: "assembly", parent: "workshop", name: "装配组", headcount: 12, jobs: ["装配操作", "装配组长"] },
  { id: "quality", parent: "office", name: "质量部", headcount: 8, jobs: ["来料质检", "质量主管"] },
  { id: "administration", parent: "office", name: "人事行政", headcount: 5, jobs: ["人事专员", "行政助理"] },
  { id: "projects", name: "直属项目", headcount: 4, jobs: ["项目协调", "项目工程师"] },
];
const samplePeople = [
  { name: "闻若溪", department: "purchasing", job: "采购助理", review: "pending", account: "active" },
  { name: "乔青禾", department: "engineering", job: "电气设计", review: "complete", account: "active" },
  { name: "林修远", department: "production", job: "生产协调", review: "complete", account: "active" },
  { name: "杜明舟", department: "warehouse", job: "仓库主管", review: "complete", account: "none" },
  { name: "许见川", department: "purchasing", job: "采购经理", review: "complete", account: "active" },
  { name: "沈云岚", department: "sales", job: "销售专员", review: "pending", account: "none" },
  { name: "顾之遥", department: "sheet", job: "折弯操作", review: "complete", account: "none" },
  { name: "柏星禾", department: "quality", job: "", review: "pending", account: "none" },
  { name: "祝明珩", department: "wire", job: "接线操作", review: "complete", account: "none" },
  { name: "裴知言", department: "administration", job: "人事专员", review: "complete", account: "disabled" },
];
const departmentById = new Map(departments.map((item) => [item.id, item]));
const reviewLabels = { pending: "待复核", complete: "已复核" };
const accountLabels = { active: "已开通", none: "未开通", disabled: "已停用" };
const filters = [
  { id: "pending", label: "待复核", matches: (person) => person.review === "pending" },
  { id: "missing", label: "缺岗位", matches: (person) => !person.job },
  { id: "no-account", label: "未开通", matches: (person) => person.account === "none" },
];
const purchasePermissions = [
  { id: "view", label: "查看采购基础信息" },
  { id: "price", label: "查看采购价格" },
  { id: "draft", label: "录入采购草稿" },
  { id: "review", label: "技术核对" },
  { id: "confirm", label: "确认采购单" },
];
const detailOrder = ["profile", "account", "permissions"];
const archiveFieldLabels = { name: "姓名", number: "人员编号", department: "部门", job: "岗位" };
const archiveFields = Object.keys(archiveFieldLabels);
const elements = Object.fromEntries(Array.from(document.querySelectorAll("[id]"), (node) => [node.id, node]));
const state = {
  view: "employees",
  department: "all",
  expanded: new Set(["office", "production"]),
  filters: new Set(),
  query: "",
  page: 1,
  pageSize: Number(elements["page-size"].value),
  employeeId: null,
  detailTab: "profile",
  treeOpen: false,
};

function createEmployeeSamples() {
  const people = [...samplePeople];
  const familyNames = ["魏", "裴", "陶", "苏", "柳", "简", "郁", "段", "季", "白", "夏", "陆", "岳", "谢", "姚", "柯", "俞", "程", "叶", "乔"];
  const givenNames = ["思远", "知夏", "明秋", "向庭", "庭安", "南舟", "映溪", "明晓"];
  let index = 0;
  for (const department of departments) {
    const assigned = samplePeople.filter((person) => person.department === department.id).length;
    const additional = (department.headcount || 0) - assigned;
    for (let offset = 0; offset < additional; offset += 1) {
      const needsReview = index % 4 === 0 || index % 13 === 0;
      people.push({
        name: familyNames[index % familyNames.length] + givenNames[Math.floor(index / familyNames.length)],
        department: department.id,
        job: index % 13 === 0 ? "" : department.jobs[offset % department.jobs.length],
        review: needsReview ? "pending" : "complete",
        account: index % 7 === 0 ? "active" : "none",
      });
      index += 1;
    }
  }
  return people.map((person, position) => {
    const id = position + 1;
    const digits = String(id).padStart(4, "0");
    const number = position % 19 === 7 ? "" : "E" + digits;
    const accountName = number ? number.toLowerCase() : "member" + id;
    return {
      ...person,
      id,
      number,
      sourceNumber: "ORG-" + digits,
      login: person.account !== "none" ? accountName + "@nodo.test" : "",
      review: number && person.job ? person.review : "pending",
      purchaseRole: initialPurchaseRole(person),
      permissions: {},
    };
  });
}

const employees = createEmployeeSamples();
const employeeById = new Map(employees.map((employee) => [employee.id, employee]));
let noticeTimer;

function escapeText(value) {
  const entities = { "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" };
  return String(value ?? "").replace(/[&<>"']/g, (character) => entities[character]);
}

function icon(name) {
  return '<span class="icon" aria-hidden="true">' + name + "</span>";
}

function departmentTrail(id) {
  const trail = [];
  let current = departmentById.get(id);
  while (current) {
    trail.unshift(current);
    current = departmentById.get(current.parent);
  }
  return trail;
}

function departmentName(id) {
  return departmentById.get(id)?.name || "全部部门";
}

function departmentPath(id) {
  return departmentTrail(id).map((item) => item.name).join(" / ");
}

function departmentEmployees(id = state.department) {
  return id === "all" ? employees : employees.filter((employee) =>
    departmentTrail(employee.department).some((department) => department.id === id)
  );
}

function childrenOf(id) {
  return departments.filter((department) => (department.parent || "all") === id);
}

function selectedEmployee() {
  return employeeById.get(state.employeeId);
}

function reviewTag(person) {
  return '<span class="tag ' + person.review + '">' + reviewLabels[person.review] + "</span>";
}

function accountState(person) {
  return '<span class="account-status ' + person.account +
    '"><span class="state-dot" aria-hidden="true"></span>' + accountLabels[person.account] + "</span>";
}

function avatar(person) {
  return '<span class="person-avatar" aria-hidden="true">' + escapeText(person.name[0]) + "</span>";
}

function renderBranch(department, depth) {
  const children = childrenOf(department.id);
  const expanded = state.expanded.has(department.id);
  const chosen = state.department === department.id;
  const disclosure = children.length
    ? '<button type="button" class="tree-disclosure" data-expand="' + department.id + '" aria-expanded="' + expanded +
      '" aria-controls="branch-' + department.id + '" aria-label="' + (expanded ? "收起" : "展开") + department.name + '">' +
      icon(expanded ? "expand_more" : "chevron_right") + "</button>"
    : '<span class="tree-disclosure" aria-hidden="true"></span>';
  const branch = children.length
    ? '<ul class="tree-group" id="branch-' + department.id + '"' + (expanded ? "" : " hidden") + ">" +
      children.map((child) => renderBranch(child, depth + 1)).join("") + "</ul>"
    : "";
  return '<li><div class="tree-row' + (chosen ? " selected" : "") + '" style="--depth:' + depth + '">' +
    disclosure + '<button type="button" class="tree-select" data-department="' + department.id +
    '"' + (chosen ? ' aria-current="true"' : "") + ' title="' + department.name + '">' +
    icon(children.length ? "folder" : "groups") + '<span class="tree-name">' + department.name +
    '</span><span class="tree-count">' + departmentEmployees(department.id).length + "</span></button></div>" + branch + "</li>";
}

function renderDepartmentTree() {
  const allSelected = state.department === "all";
  elements["department-tree"].innerHTML = '<ul class="tree-group"><li><div class="tree-row all-departments' +
    (allSelected ? " selected" : "") + '"><button class="tree-select" type="button" data-department="all"' +
    (allSelected ? ' aria-current="true"' : "") + ">" + icon("groups") +
    '<span class="tree-name">全部部门</span><span class="tree-count">' + employees.length +
    "</span></button></div></li>" + childrenOf("all").map((department) => renderBranch(department, 0)).join("") + "</ul>";
  const expanded = state.expanded.size > 0;
  const toggle = elements["collapse-branches"];
  toggle.setAttribute("aria-label", expanded ? "收起部门" : "展开部门");
  toggle.setAttribute("aria-expanded", expanded);
  toggle.title = expanded ? "收起部门" : "展开部门";
}

function supplementButton(person, field, label, className = "") {
  return '<button type="button" class="supplement-link truncate ' + className + '" data-supplement-field="' + field +
    '" aria-label="补充' + escapeText(person.name) + '的' + archiveFieldLabels[field] + '">' + label + "</button>";
}

function employeeRow(person) {
  const department = departmentById.get(person.department);
  const parent = departmentById.get(department.parent);
  const origin = parent && parent.id !== "office"
    ? '<span class="parent-department truncate">' + parent.name + "</span>"
    : "";
  const active = state.employeeId === person.id;
  const number = person.number ? '<span class="person-number truncate">' + escapeText(person.number) + "</span>" :
    supplementButton(person, "number", "编号待填写", "person-number");
  const job = person.job ? '<span class="truncate">' + escapeText(person.job) + "</span>" :
    supplementButton(person, "job", "待填写");
  return '<tr data-person="' + person.id + '" data-selected="' + active + '"><td><div class="person-cell">' +
    avatar(person) + '<div class="person-identity"><button type="button" class="person-open truncate" aria-label="查看' +
    escapeText(person.name) + '的员工详情" aria-expanded="' + active + '">' + escapeText(person.name) +
    "</button>" + number + '</div></div></td><td><div class="department-cell"><span class="truncate">' + department.name +
    "</span>" + origin + "</div></td><td>" + job + "</td><td>" +
    reviewTag(person) + "</td><td>" + accountState(person) + '</td><td class="open-cell">' +
    icon("chevron_right") + "</td></tr>";
}

function renderEmployees() {
  const search = state.query.trim().toLowerCase();
  const scope = departmentEmployees();
  const searchResults = scope.filter((person) =>
    [person.name, person.number, person.job].some((value) => value.toLowerCase().includes(search))
  );
  const activeFilters = filters.filter((filter) => state.filters.has(filter.id));
  const results = searchResults.filter((person) => activeFilters.every((filter) => filter.matches(person)));
  const pages = Math.max(1, Math.ceil(results.length / state.pageSize));
  state.page = Math.min(state.page, pages);
  const start = (state.page - 1) * state.pageSize;
  const visible = results.slice(start, start + state.pageSize);

  elements["scope-title"].textContent = state.department === "all" ? "全部员工" : departmentName(state.department);
  elements["scope-count"].hidden = state.department === "all";
  elements["scope-count"].textContent = scope.length + " 人";
  elements["quick-filters"].innerHTML = filters.map((filter) =>
    '<button class="filter" type="button" aria-pressed="' + state.filters.has(filter.id) +
    '" data-filter="' + filter.id + '">' + filter.label +
    '<span class="filter-count">' + searchResults.filter(filter.matches).length + "</span></button>"
  ).join("");
  elements["employee-rows"].innerHTML = visible.length
    ? visible.map(employeeRow).join("")
    : '<tr><td class="empty-state" colspan="6"><strong>没有符合条件的员工</strong>' +
      "<p>可更换搜索词，或清除当前筛选。</p>" +
      '<button type="button" class="button" id="reset-search">清除搜索和筛选</button></td></tr>';
  elements["result-summary"].textContent = results.length
    ? "显示 " + (start + 1) + "–" + (start + visible.length) + " 人，共 " + results.length + " 人"
    : "共 0 人";
  elements["page-counter"].textContent = state.page + " / " + pages;
  elements["previous-page"].disabled = state.page <= 1;
  elements["next-page"].disabled = state.page >= pages;
}

function renderDepartmentDetail() {
  const branch = state.department;
  const trail = departmentTrail(branch);
  const people = departmentEmployees(branch);
  const pending = people.filter((person) => person.review === "pending").length;
  const branches = childrenOf(branch);
  const list = branches.map((child) =>
    '<li><button type="button" data-department="' + child.id + '">' + icon("folder") +
    "<strong>" + child.name + '</strong><span class="subdepartment-count">' + departmentEmployees(child.id).length +
    " 人</span>" + icon("chevron_right") + "</button></li>"
  ).join("");
  const subdepartments = branches.length
    ? '<section class="subdepartment-section"><h3>下级部门与组</h3><ul class="subdepartment-list">' + list + "</ul></section>"
    : "";
  const direct = people.filter((person) => person.department === branch);
  const members = direct.slice(0, 5).map((person) =>
    '<li><span class="member-identity">' + avatar(person) + '<strong class="truncate">' + escapeText(person.name) +
    '</strong></span><span class="truncate">' + escapeText(person.job || "岗位待填写") + "</span>" + reviewTag(person) + "</li>"
  ).join("");
  const memberSection = branch === "all" ? "" :
    '<section class="member-section"><h3>直接归属员工<span class="member-total">' + direct.length + ' 人</span></h3>' +
    (members ? '<ul class="member-list">' + members + "</ul>" :
      '<p class="info-line">人员归属在下级部门。</p>') +
    (direct.length > 5 ? '<p class="info-line">显示前 5 人，点「查看员工」可查全名单。</p>' : "") +
    "</section>";
  elements["department-detail"].innerHTML = '<header class="department-detail-header"><div>' +
    (trail.length > 1 ? '<p class="breadcrumbs">' + trail.slice(0, -1).map((item) => item.name).join(" / ") + "</p>" : "") +
    '<h2 id="department-detail-title">' + departmentName(branch) +
    '</h2><p class="department-detail-meta">' + people.length + " 人 · " + pending + " 人待复核</p></div>" +
    '<button type="button" class="button" id="show-department-people">查看员工' + icon("chevron_right") +
    "</button></header>" + subdepartments + memberSection;
}

function fieldRows(rows) {
  return '<dl class="detail-fields">' + rows.map(([label, value]) =>
    "<div><dt>" + label + "</dt><dd>" + value + "</dd></div>"
  ).join("") + "</dl>";
}

function missingArchiveFields(values) {
  return archiveFields.filter((field) => !values[field]?.trim());
}

function profilePanel(person) {
  const incomplete = missingArchiveFields(person).map((field) => archiveFieldLabels[field]);
  const needsReview = person.review === "pending";
  const missing = '<span class="missing">待填写</span>';
  const profile = fieldRows([
    ["人员编号", person.number ? escapeText(person.number) : missing],
    ["部门路径", departmentPath(person.department)],
    ["岗位", person.job ? escapeText(person.job) : missing],
    ["档案来源", "组织架构图"],
  ]);
  const message = incomplete.length
    ? '<p class="callout">请先补齐' + incomplete.join("和") + "，再确认复核。</p>"
    : needsReview ? '<p class="info-line">确认编号、部门和岗位后，可标记为已复核。</p>' : "";
  elements["detail-actions"].innerHTML = '<button type="button" class="button" id="open-edit">补充信息</button>' +
    (needsReview ? '<button type="button" class="button button-primary" id="confirm-review"' +
      (incomplete.length ? " disabled" : "") + ">确认复核</button>" : "");
  elements["detail-actions"].hidden = false;
  return '<h3 class="detail-section-title">工作档案</h3>' + profile + message;
}

function accountPanel(person) {
  const rows = [["账号状态", accountState(person)]];
  if (person.login) rows.push(["登录名", escapeText(person.login)]);
  const note = person.account === "none"
    ? "档案已存在。需要登录时，由管理员在用户入口开通并配置权限。"
    : "系统管理员可在用户入口管理登录账号及公司范围。";
  return '<h3 class="detail-section-title">登录账号</h3>' + fieldRows(rows) + '<p class="info-line">' + note + "</p>";
}

function initialPurchaseRole(person) {
  if (person.department === "purchasing") {
    return person.job === "采购助理" ? "assistant" : "buyer";
  }
  return person.department === "engineering" ? "engineering" : "";
}

function rolePermissionDefaults(person) {
  if (person.purchaseRole === "assistant") return ["view", "price", "draft"];
  if (person.purchaseRole === "buyer") return ["view", "price", "draft", "confirm"];
  if (person.purchaseRole === "engineering") return ["view", "price", "review"];
  return [];
}

function permissionsPanel(person) {
  if (person.account === "none") {
    return '<h3 class="detail-section-title">采购协作</h3><p class="info-line">请先开通员工账号，再设置个人权限。</p>';
  }
  const defaults = rolePermissionDefaults(person);
  let scope = "授权公司";
  if (person.purchaseRole === "assistant") scope = "本人草稿";
  else if (person.purchaseRole === "engineering") scope = "本人负责的单据";
  const permissionAllowed = (id) => {
    const mode = person.permissions[id] || "inherit";
    return mode === "inherit" ? defaults.includes(id) : mode === "allow";
  };
  const canView = permissionAllowed("view");
  const choices = [["inherit", "岗位默认"], ["allow", "能"], ["deny", "否"]];
  return '<div class="permission-heading"><h3 class="detail-section-title">采购协作</h3><p>个人设定</p></div>' +
    purchasePermissions.map((permission) => {
      const value = person.permissions[permission.id] || "inherit";
      const viewRequired = permission.id !== "view" && !canView;
      const allowed = !viewRequired && permissionAllowed(permission.id);
      const source = viewRequired ? "基础查看已关闭" : (value === "inherit" ? "岗位默认" : "个人设定");
      const effective = (allowed ? '<strong class="allow">能</strong>' : "<strong>否</strong>") +
        (allowed && ["view", "price"].includes(permission.id) ? " · " + scope : "") +
        " · " + source;
      const options = choices.map(([key, label]) =>
        '<option value="' + key + '"' + (key === value ? " selected" : "") + ">" + label + "</option>"
      ).join("");
      return '<div class="permission-item"><div><label for="permission-' + permission.id + '">' + permission.label +
        "</label><p>" + effective + '</p></div><select class="permission-choice" id="permission-' + permission.id +
        '" data-permission="' + permission.id + '">' + options + "</select></div>";
    }).join("");
}

function renderEmployeeDetail() {
  const person = state.view === "employees" ? selectedEmployee() : null;
  elements["workspace-grid"].classList.toggle("has-detail", Boolean(person));
  elements["employee-detail"].hidden = !person;
  elements["drawer-backdrop"].hidden = !person;
  if (!person) return;

  const jobAndDepartment = [departmentName(person.department), person.job].filter(Boolean).join(" · ");
  elements["profile-heading"].innerHTML = avatar(person) + "<div><h3>" + escapeText(person.name) +
    "</h3><p>" + escapeText(jobAndDepartment) + "</p></div>" + reviewTag(person);
  for (const tab of detailOrder) {
    const button = elements["tab-" + tab];
    button.setAttribute("aria-selected", state.detailTab === tab);
    button.tabIndex = state.detailTab === tab ? 0 : -1;
  }
  const views = { profile: profilePanel, account: accountPanel, permissions: permissionsPanel };
  elements["detail-actions"].hidden = true;
  elements["detail-content"].setAttribute("aria-labelledby", "tab-" + state.detailTab);
  elements["detail-content"].innerHTML = views[state.detailTab](person);
}

function renderView() {
  const directory = state.view === "employees";
  elements["page-title"].textContent = directory ? "员工目录" : "部门";
  elements["directory-total"].textContent = employees.length + " 名员工 · " + departments.length + " 个部门与组";
  elements["directory-panel"].hidden = !directory;
  elements["department-detail"].hidden = directory;
  elements["workspace-grid"].classList.toggle("mobile-tree-open", state.treeOpen);
  elements["toggle-departments"].setAttribute("aria-expanded", state.treeOpen);
  document.querySelectorAll("[data-view]").forEach((button) => {
    if (button.dataset.view === state.view) button.setAttribute("aria-current", "page");
    else button.removeAttribute("aria-current");
  });
  renderDepartmentTree();
  if (directory) renderEmployees();
  else renderDepartmentDetail();
  renderEmployeeDetail();
}

function changeView(view) {
  state.view = view;
  state.employeeId = null;
  history.replaceState(null, "", "#" + view);
  renderView();
}

function chooseDepartment(id, returnFocus = false) {
  state.department = id;
  state.employeeId = null;
  state.page = 1;
  state.treeOpen = false;
  departmentTrail(id).forEach((department) => {
    if (childrenOf(department.id).length) state.expanded.add(department.id);
  });
  renderView();
  if (returnFocus) {
    const button = elements["department-tree"].querySelector('[data-department="' + id + '"]');
    if (button?.offsetWidth) button.focus();
    else elements["toggle-departments"].focus();
  }
}

function closeDetails() {
  const previous = state.employeeId;
  state.employeeId = null;
  renderEmployees();
  renderEmployeeDetail();
  document.querySelector('[data-person="' + previous + '"] .person-open')?.focus();
}

function notify(message) {
  const notice = elements.notice;
  clearTimeout(noticeTimer);
  notice.textContent = message;
  notice.hidden = false;
  noticeTimer = setTimeout(() => { notice.hidden = true; }, 2800);
}

function openEditDialog(employee, trigger, field) {
  const popup = document.createElement("nodo-staff-supplement");
  document.body.append(popup);
  popup.open({
    person: { ...employee, reviewLabel: reviewLabels[employee.review], canEditName: true },
    departments: departments.map((item) => ({ id: item.id, label: departmentPath(item.id) })),
    field,
    onSave(changes) {
      if (changes.number && employees.some((other) =>
        other.id !== employee.id && other.number.toLowerCase() === changes.number.toLowerCase()
      )) {
        throw Object.assign(new Error("此编号已被使用"), { field: "number" });
      }
      Object.assign(employee, changes, { review: "pending" });
    },
    onClose(saved) {
      popup.remove();
      if (saved) {
        renderView();
        notify("预览档案已更新");
      }
      const replacement = trigger.id === "open-edit"
        ? document.getElementById("open-edit")
        : document.querySelector('[data-person="' + employee.id + '"] .person-open');
      (trigger.isConnected ? trigger : replacement || elements["employee-search"]).focus({ preventScroll: true });
    },
  });
}

elements["employee-search"].addEventListener("input", (event) => {
  state.query = event.target.value;
  state.page = 1;
  renderEmployees();
});
elements["page-size"].addEventListener("change", (event) => {
  state.pageSize = Number(event.target.value);
  state.page = 1;
  renderEmployees();
});

document.addEventListener("click", (event) => {
  const control = event.target.closest("button, [data-person]");
  if (!control) return;
  if (control.dataset.view) {
    changeView(control.dataset.view);
  } else if (control.dataset.department) {
    chooseDepartment(control.dataset.department, true);
  } else if (control.dataset.expand) {
    const id = control.dataset.expand;
    if (!state.expanded.delete(id)) state.expanded.add(id);
    renderDepartmentTree();
    elements["department-tree"].querySelector('[data-expand="' + id + '"]')?.focus();
  } else if (control.dataset.filter) {
    const id = control.dataset.filter;
    if (!state.filters.delete(id)) state.filters.add(id);
    state.page = 1;
    renderEmployees();
    elements["quick-filters"].querySelector('[data-filter="' + id + '"]')?.focus();
  } else if (control.dataset.detailTab) {
    state.detailTab = control.dataset.detailTab;
    renderEmployeeDetail();
  } else if (control.dataset.supplementField) {
    const employee = employeeById.get(Number(control.closest("[data-person]").dataset.person));
    openEditDialog(employee, control, control.dataset.supplementField);
  } else if (control.closest("[data-person]")) {
    state.employeeId = Number(control.closest("[data-person]").dataset.person);
    state.detailTab = "profile";
    renderEmployees();
    renderEmployeeDetail();
    elements["close-employee"].focus();
  }
});

const actions = {
  "toggle-departments": () => {
    state.treeOpen = !state.treeOpen;
    renderView();
  },
  "collapse-branches": () => {
    if (state.expanded.size) state.expanded.clear();
    else departments.filter((department) => childrenOf(department.id).length).forEach((department) =>
      state.expanded.add(department.id));
    renderDepartmentTree();
  },
  "open-import": () => elements["import-dialog"].showModal(),
  "open-edit": (button) => openEditDialog(selectedEmployee(), button),
  "close-employee": closeDetails,
  "drawer-backdrop": closeDetails,
  "show-department-people": () => changeView("employees"),
  "previous-page": () => {
    state.page = Math.max(1, state.page - 1);
    renderEmployees();
  },
  "next-page": () => {
    state.page += 1;
    renderEmployees();
  },
  "reset-search": () => {
    state.query = "";
    state.filters.clear();
    state.page = 1;
    elements["employee-search"].value = "";
    renderEmployees();
    elements["employee-search"].focus();
  },
  "confirm-review": () => {
    const person = selectedEmployee();
    if (missingArchiveFields(person).length) return;
    person.review = "complete";
    renderEmployees();
    renderEmployeeDetail();
    notify("预览档案已标记为已复核");
  },
};
document.addEventListener("click", (event) => {
  const button = event.target.closest("button[id]");
  if (button && Object.hasOwn(actions, button.id)) actions[button.id](button);
});

elements["detail-content"].addEventListener("change", (event) => {
  const choice = event.target.closest("[data-permission]");
  if (!choice) return;
  selectedEmployee().permissions[choice.dataset.permission] = choice.value;
  renderEmployeeDetail();
  document.getElementById(choice.id)?.focus();
});


document.addEventListener("keydown", (event) => {
  if (
    event.key === "Escape" && selectedEmployee()
    && !document.querySelector("nodo-staff-supplement dialog[open]") && !elements["import-dialog"].open
  ) {
    closeDetails();
    return;
  }
  const tab = event.target.closest("[data-detail-tab]");
  if (!tab || !["ArrowLeft", "ArrowRight", "Home", "End"].includes(event.key)) return;
  event.preventDefault();
  const index = detailOrder.indexOf(tab.dataset.detailTab);
  const steps = { ArrowLeft: (index + 2) % 3, ArrowRight: (index + 1) % 3, Home: 0, End: 2 };
  state.detailTab = detailOrder[steps[event.key]];
  renderEmployeeDetail();
  elements["tab-" + state.detailTab].focus();
});

function renderLocation() {
  state.view = location.hash === "#departments" ? "departments" : "employees";
  state.employeeId = null;
  renderView();
  if (location.hash === "#supplement" && !document.querySelector("nodo-staff-supplement dialog[open]")) {
    elements["employee-rows"].querySelector("[data-supplement-field]")?.click();
  }
}

window.addEventListener("hashchange", renderLocation);
renderLocation();
