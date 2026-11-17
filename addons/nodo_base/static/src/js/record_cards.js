import { Component, proxy, types as t, useEffect, useProps } from "@odoo/owl";
import { Dialog } from "@web/core/dialog/dialog";
import { useLayoutEffect, useSubEnv } from "@web/owl2/utils";
import { SelectCreateDialog } from "@web/views/view_dialogs/select_create_dialog";

// 兼容历史消息里的应用路径。新引用统一使用 /odoo/<模型>/<编号>。
const PATH_MODELS = new Map(Object.entries({
    sales: "sale.order",
    crm: "crm.lead",
    purchase: "purchase.order",
    manufacturing: "mrp.production",
    contacts: "res.partner",
}));
const RECORD_PATH = /^\/odoo\/([a-z_][a-z0-9_.]*)\/(\d+)\/?$/;
const BODY_URLS = /https?:\/\/[^\s<>]+|(?<!\S)\/odoo\/[^\s<>]+/g;
const MAX_CARDS = 3;
const CACHE_MS = 5000;
const STATUS_TYPES = new Set(["warning", "info", "success", "muted"]);
export const RECORD_SERVICE = "nodo.discuss.record";

function recordKey({ model, id }) {
    return `${model},${id}`;
}

function parseRecordRef(source) {
    let href = source;
    if (source instanceof HTMLAnchorElement) {
        // Odoo uses the same contact URL for a person mention and a record link.
        const personMention = source.matches('.o_mail_redirect[data-oe-model="res.partner"]') &&
            source.textContent.trimStart().startsWith("@");
        if (personMention || source.matches(".o-discuss-mention, .o-discuss-readonly-mention")) {
            return null;
        }
        href = source.getAttribute("href");
    }
    if (!href?.includes("/odoo/")) {
        return null;
    }
    const url = URL.parse(href, window.location.origin);
    const match = url?.origin === window.location.origin && url.pathname.match(RECORD_PATH);
    if (!match) {
        return null;
    }
    const [, path, idText] = match;
    const model = PATH_MODELS.get(path) || path;
    const id = Number(idText);
    if (model.includes(".") && Number.isSafeInteger(id) && id > 0) {
        return { model, id };
    }
    return null;
}

export function extractRecordRefs(body) {
    const refs = new Map();
    if (!body?.innerHTML.includes("/odoo/")) {
        return [];
    }
    const nodes = document.createTreeWalker(body, NodeFilter.SHOW_ELEMENT | NodeFilter.SHOW_TEXT);
    for (let node = nodes.nextNode(); node && refs.size < MAX_CARDS; node = nodes.nextNode()) {
        let sources = [];
        if (node instanceof HTMLAnchorElement) {
            sources = [node];
        } else if (node.nodeType === Node.TEXT_NODE && !node.parentElement?.closest("a")) {
            sources = Array.from(node.nodeValue.matchAll(BODY_URLS), ([url]) =>
                url.replace(/[).,;!?，。；！？]+$/, "")
            );
        }
        for (const source of sources) {
            const ref = parseRecordRef(source);
            if (ref) {
                refs.set(recordKey(ref), ref);
                if (refs.size === MAX_CARDS) {
                    break;
                }
            }
        }
    }
    return [...refs.values()];
}

export function useRecordCardCache() {
    // Discuss and chat windows key the Thread component by its conversation, so reopening starts fresh.
    useSubEnv({ nodoRecordCardCache: new Map() });
}

async function loadCards(orm, cache, refs) {
    const now = Date.now();
    for (const [key, entry] of cache) {
        if (entry.expiresAt <= now) {
            cache.delete(key);
        }
    }
    const missing = refs.filter((ref) => !cache.has(recordKey(ref)));
    if (missing.length) {
        const batch = orm.silent.call(RECORD_SERVICE, "get_record_cards", [missing])
            .then((cards) => new Map(cards.map((card) => [recordKey(card), card])))
            .catch(() => new Map());
        for (const ref of missing) {
            const key = recordKey(ref);
            const entry = { expiresAt: Infinity };
            entry.promise = batch.then((cards) => {
                const card = cards.get(key);
                if (card) {
                    entry.expiresAt = Date.now() + CACHE_MS;
                } else {
                    cache.delete(key);
                }
                return card;
            });
            cache.set(key, entry);
        }
    }
    return (await Promise.all(refs.map((ref) => cache.get(recordKey(ref)).promise))).filter(Boolean);
}

export class NodoRecordCards extends Component {
    static template = "nodo_base.RecordCards";
    props = useProps({ message: t.object(), refs: t.array(t.object()) });
    bodyRef = useProps.static("bodyRef", t.signal(t.ref(HTMLDivElement)));

    setup() {
        const orm = this.env.services.orm;
        const cache = this.env.nodoRecordCardCache || new Map();
        this.state = proxy({ cards: [] });
        useEffect(() => {
            const refs = this.props.refs;
            let active = true;
            this.state.cards = [];
            loadCards(orm, cache, refs).then((cards) => {
                if (active) {
                    this.state.cards = cards;
                }
            });
            return () => {
                active = false;
            };
        });
        useLayoutEffect(
            (body, cards) => {
                const shown = new Set(cards.map(recordKey));
                const links = [];
                for (const link of body?.querySelectorAll("a[href]") || []) {
                    const ref = parseRecordRef(link);
                    if (ref && shown.has(recordKey(ref))) {
                        link.classList.add("o_nodo_link_as_card");
                        links.push(link);
                    }
                }
                return () => {
                    for (const link of links) {
                        link.classList.remove("o_nodo_link_as_card");
                    }
                };
            },
            () => [this.bodyRef(), this.state.cards, this.props.message.richBody, this.props.message.showTranslation]
        );
    }

    cardKey = recordKey;

    statusClass(card) {
        return STATUS_TYPES.has(card.status_type) ? `o_nodo_state_${card.status_type}` : "";
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

class RecordTypesDialog extends Component {
    static template = "nodo_base.RecordTypesDialog";
    static components = { Dialog };
    props = useProps({
        types: t.array(t.object()),
        select: t.function(),
        close: t.function(),
    });

    select(model) {
        this.props.close();
        this.props.select(model);
    }
}

export async function insertRecordReference(owner, { orm, dialog, notification }) {
    const types = await orm.silent.call(RECORD_SERVICE, "get_record_card_types", []);
    if (!types.length) {
        notification.add("当前没有可引用的单据类型。", { type: "info" });
        return;
    }
    const select = ({ model, label }) => dialog.add(SelectCreateDialog, {
        resModel: model,
        title: `引用${label}`,
        multiSelect: false,
        noCreate: true,
        onSelected: ([id]) => {
            if (id) {
                owner.addEmoji(` ${window.location.origin}/odoo/${model}/${id} `);
            }
        },
    });
    if (types.length === 1) {
        select(types[0]);
    } else {
        dialog.add(RecordTypesDialog, { types, select });
    }
}
