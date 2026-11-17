import { expect, test } from "@odoo/hoot";
import { waitFor } from "@odoo/hoot-dom";
import { Component, computed, signal, xml } from "@odoo/owl";
import { defineMailModels } from "@mail/../tests/mail_test_helpers";
import { extractRecordRefs, NodoRecordCards } from "@nodo_base/js/record_cards";
import { mountWithCleanup } from "@web/../tests/web_test_helpers";

defineMailModels();

test.tags("nodo");
test("partner mentions do not generate a contact card beside a quotation", () => {
    const body = document.createElement("div");
    body.innerHTML = `
        112 <a href="/odoo/res.partner/6" class="o_mail_redirect"
               data-oe-id="6" data-oe-model="res.partner">@销售专员</a>
        <a href="/odoo/sale.order/1">S00001</a>
    `;

    expect(extractRecordRefs(body)).toEqual([{ model: "sale.order", id: 1 }]);
});

class RecordCardMessage extends Component {
    static components = { NodoRecordCards };
    static template = xml`
        <div class="o-mail-Message-body" t-ref="this.body">
            <a href="/odoo/res.partner/6" class="o_mail_redirect"
               data-oe-id="6" data-oe-model="res.partner">@销售专员</a>
            <a href="/odoo/res.partner/6" class="o_mail_redirect"
               data-oe-id="6" data-oe-model="res.partner">联系人资料</a>
            <a href="/odoo/sale.order/1">S00001</a>
            <NodoRecordCards t-if="this.body()" bodyRef="this.body" refs="this.refs()" message="this.message"/>
        </div>
    `;

    body = signal.ref();
    refs = computed(() => extractRecordRefs(this.body()));
    message = {};
}

test.tags("nodo");
test("a contact card for an explicit link leaves the mention for the same contact visible", async () => {
    const cards = [
        { model: "res.partner", id: 6, title: "联系人 销售专员" },
        { model: "sale.order", id: 1, title: "报价单 S00001" },
    ];
    await mountWithCleanup(RecordCardMessage, {
        noMainContainer: true,
        componentEnv: {
            services: {
                orm: {
                    silent: {
                        async call(model, method, [refs]) {
                            expect(model).toBe("nodo.discuss.record");
                            expect(method).toBe("get_record_cards");
                            expect(refs).toEqual(cards.map(({ model, id }) => ({ model, id })));
                            return cards;
                        },
                    },
                },
            },
        },
    });

    await waitFor('a[href="/odoo/sale.order/1"].o_nodo_link_as_card');
    expect(".o_nodo_record_card_title").toHaveCount(2);
    expect('a[href="/odoo/res.partner/6"].o_nodo_link_as_card').toHaveText("联系人资料");
    expect('a[href="/odoo/res.partner/6"]:not(.o_nodo_link_as_card)').toHaveText("@销售专员");
});
