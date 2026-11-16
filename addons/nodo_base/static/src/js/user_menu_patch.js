import { patch } from "@web/core/utils/patch";
import { UserMenu } from "@web/webclient/user_menu/user_menu";

// 用户菜单中指向外部站点或订阅推广的项目，NODO 不显示。
const HIDDEN_ITEM_IDS = new Set(["support", "mysubscription_user_menu"]);

patch(UserMenu.prototype, {
    getElements() {
        return super.getElements().filter((element) => !HIDDEN_ITEM_IDS.has(element.id));
    },
});
