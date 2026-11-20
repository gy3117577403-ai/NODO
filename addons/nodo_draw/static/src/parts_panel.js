import {Component, signal, useProps} from "@odoo/owl";

const sheetIds = new Set(["wrap", "top", "bottom", "mount", "door", "door_right"]);
const searchKey = value => value.trim().toLowerCase().replaceAll("×", "x");

function row(part, name = part.name) {
    return {id: part.id, name, code: part.code, color: part.color, ids: [part.id], children: []};
}

function partGroups(parts) {
    const sheets = [];
    const hardware = new Map();
    for (const part of parts) {
        if (sheetIds.has(part.id) || part.id.startsWith("brace_")) {
            sheets.push(row(part));
        } else {
            const key = JSON.stringify([part.name, part.code]);
            if (!hardware.has(key)) hardware.set(key, []);
            hardware.get(key).push(part);
        }
    }
    const fittings = [...hardware.values()].map(members => {
        const first = members[0];
        if (members.length === 1) return row(first);
        return {
            ...row(first), id: "group-" + first.id, ids: members.map(part => part.id),
            children: members.map((part, index) => row(part, `${part.name} ${index + 1}`)),
        };
    });
    fittings.sort((left, right) => Number(right.children.length > 0) - Number(left.children.length > 0));
    return [{name: "钣金件", rows: sheets}, {name: "结构五金", rows: fittings}];
}

export class PartsPanel extends Component {
    static template = "nodo_draw.PartsPanel";
    props = useProps({
        parts: Array, selected: Array, hidden: Array, select: Function, toggle: Function, showAll: Function,
    });
    query = signal("");
    expanded = signal([]);

    visibleGroups() {
        const query = searchKey(this.query());
        return partGroups(this.props.parts).map(group => {
            const rows = group.rows.filter(entry => searchKey(`${entry.name} ${entry.code ?? ""}`).includes(query));
            return {...group, rows, count: rows.reduce((total, entry) => total + entry.ids.length, 0)};
        }).filter(group => group.count);
    }
    toggleGroup(id) {
        const expanded = this.expanded();
        this.expanded.set(expanded.includes(id) ? expanded.filter(key => key !== id) : [...expanded, id]);
    }
    isSelected(entry) { return entry.ids.some(id => this.props.selected.includes(id)); }
    isHidden(entry) { return entry.ids.every(id => this.props.hidden.includes(id)); }
    visibilityLabel(entry) { return (this.isHidden(entry) ? "显示" : "隐藏") + entry.name; }
    swatch(color) { return color?.map(value => Math.round(value * 255)).join(","); }
}
