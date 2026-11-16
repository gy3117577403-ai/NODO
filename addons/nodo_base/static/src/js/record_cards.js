import { Component, onMounted, proxy, types as t, useProps } from "@odoo/owl";
import { formatMonetary } from "@web/views/fields/formatters";

// 消息里的单据链接（/odoo/<模型>/<编号>，或常用应用路径）识别为单据卡片
const PATH_MODELS = {
    sales: "sale.order",
    crm: "crm.lead",
    purchase: "purchase.order",
    manufacturing: "mrp.production",
    contacts: "res.partner",
};
const LINK_RE = /\/odoo\/([a-z_]+(?:\.[a-z_]+)+|sales|crm|purchase|manufacturing|contacts)\/(\d+)/g;
const MAX_CARDS = 3;

const MODEL_LABELS = {
    "crm.lead": "商机",
    "purchase.order": "采购单",
    "mrp.production": "生产订单",
    "res.partner": "联系人",
};
const SALE_STATES = {
    draft: ["报价单", "待提交", "o_nodo_state_warning"],
    sent: ["报价单", "已发送", "o_nodo_state_info"],
    sale: ["销售订单", "已确认", "o_nodo_state_success"],
    cancel: ["报价单", "已取消", "o_nodo_state_muted"],
};

/** 从消息正文中找出单据引用，去重，最多 3 个。 */
export function extractRecordRefs(body) {
    const refs = [];
    const seen = new Set();
    for (const match of String(body || "").matchAll(LINK_RE)) {
        const model = PATH_MODELS[match[1]] || match[1];
        const id = parseInt(match[2], 10);
        const key = `${model},${id}`;
        if (!seen.has(key)) {
            seen.add(key);
            refs.push({ model, id, key });
        }
        if (refs.length >= MAX_CARDS) {
            break;
        }
    }
    return refs;
}

const cache = new Map();

async function loadCard(orm, { model, id, key }) {
    if (!cache.has(key)) {
        cache.set(key, (async () => {
            try {
                if (model === "sale.order") {
                    const [rec] = await orm.silent.read(model, [id], ["name", "partner_id", "amount_total", "currency_id", "state"]);
                    if (!rec) {
                        return null;
                    }
                    const [label, stateLabel, stateClass] = SALE_STATES[rec.state] || ["报价单", "", ""];
                    const amount = formatMonetary(rec.amount_total, { currencyId: rec.currency_id && rec.currency_id[0] });
                    return {
                        key, model, id,
                        title: `${label} ${rec.name}`,
                        subtitle: [rec.partner_id && rec.partner_id[1], amount].filter(Boolean).join(" · "),
                        stateLabel, stateClass,
                    };
                }
                const [rec] = await orm.silent.read(model, [id], ["display_name"]);
                if (!rec) {
                    return null;
                }
                return { key, model, id, title: `${MODEL_LABELS[model] || "单据"} ${rec.display_name}`, subtitle: "", stateLabel: "", stateClass: "" };
            } catch {
                // 没有权限或单据已删除：不显示卡片，不弹错误
                return null;
            }
        })());
    }
    return cache.get(key);
}

export class NodoRecordCards extends Component {
    static template = "nodo_base.RecordCards";
    props = useProps({ message: t.object() });

    setup() {
        this.state = proxy({ cards: [] });
        onMounted(() => this.load());
    }

    async load() {
        const orm = this.env.services.orm;
        if (!orm) {
            return;
        }
        const refs = extractRecordRefs(this.props.message.body);
        const cards = await Promise.all(refs.map((ref) => loadCard(orm, ref)));
        this.state.cards = cards.filter(Boolean);
    }

    open(card) {
        this.env.services.action?.doAction({
            type: "ir.actions.act_window",
            res_model: card.model,
            res_id: card.id,
            views: [[false, "form"]],
            target: "current",
        });
    }
}
